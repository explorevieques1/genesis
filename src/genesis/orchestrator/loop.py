# Spec: Genesis Markdown/10-Architecture/Orchestrator.md
"""The voice loop -- Phase 2's spine.

Wires the pieces Voice Stack draws as a pipeline::

    mic -> ring buffer -> VAD -> wake gate -> [audio may now leave]
        -> STT -> intent -> answer -> TTS -> speakers
                                        |
                                   echo filter

Three structural commitments, each traceable to a line in the notes:

**The fast path never waits for the slow path.** Barge-in, reflexes and the
kill phrase are handled on the audio thread or immediately after it, with no
transcription, no network and no model in the way. Understanding what you said
happens afterwards, on a worker thread, where it is allowed to take a second.

**Audio does not leave the machine before the gate opens.** The loop never
touches the ring buffer directly; it hands segments to
:class:`~genesis.voice.wake.WakeGate` and receives them back only if a *local*
model heard the wake word, or if a follow-up window is already open because
Genesis just spoke to you.

**Nothing here can hang the voice.** Every outward call is wrapped: a Scribe
failure falls back to the local transcript, a TTS failure falls through the
speaker's own chain, and an unexpected exception in a turn is logged and
dropped rather than killing the loop. Voice Stack: *"Never hard-fail the whole
system on a voice fault. Voice is a surface, not the spine."*
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from genesis.errors import DegradedError
from genesis.ids import new_trace_id
from genesis.memory.working import WorkingMemory
from genesis.orchestrator.answers import TrivialAnswerer
from genesis.orchestrator.intent import Intent, IntentClassifier
from genesis.voice.capture import Microphone
from genesis.voice.earcons import Earcon
from genesis.voice.policy import REQUESTED, Presence, SpeechPolicy
from genesis.voice.reflex import Reflex
from genesis.voice.speaker import Speaker
from genesis.voice.vad import SpeechEvent, Vad, rms
from genesis.voice.wake import WakeGate

__all__ = ["VoiceLoop", "Turn"]


@dataclass
class Turn:
    """One pass through the loop, for the trace and for tests."""

    heard: str = ""
    intent: str = ""
    path: str = ""
    spoken: str = ""
    source: str = ""
    #: One id per turn, shared by the working-memory turn, the spoken output
    #: and the Episodic Log entry, so a single utterance is one thread in the
    #: trace rather than four unrelated rows.
    trace_id: str = ""
    wake_ms: float = 0.0
    stt_ms: float = 0.0
    total_ms: float = 0.0
    fields: dict = field(default_factory=dict)


class VoiceLoop:
    """The always-on listener.

    ``on_turn`` receives a completed :class:`Turn` -- the daemon uses it to
    write the Episodic Log, tests use it to assert.
    """

    def __init__(
        self,
        *,
        mic: Microphone,
        gate: WakeGate,
        speaker: Speaker,
        classifier: IntentClassifier,
        memory: WorkingMemory,
        answerer: TrivialAnswerer | None = None,
        planner=None,
        runner=None,
        reasoner=None,
        earcons=None,
        verbosity=None,
        policy: SpeechPolicy | None = None,
        stt=None,
        vad: Vad | None = None,
        on_turn: Callable[[Turn], None] | None = None,
        on_reflex: Callable[[Reflex], None] | None = None,
        min_utterance_sec: float = 0.4,
        max_utterance_sec: float = 15.0,
    ) -> None:
        self.mic = mic
        self.gate = gate
        self.speaker = speaker
        self.classifier = classifier
        self.memory = memory
        self.answerer = answerer or TrivialAnswerer()
        #: The middle rung of the answer ladder: deterministic answer, then a
        #: planned task list, then the large tier. Both halves are optional and
        #: absent together -- a planner with nothing to dispatch to would only
        #: ever decline, so ``build_voice_loop`` wires neither or both.
        self.planner = planner
        self.runner = runner
        #: Non-verbal status (Voice UX). Optional: with none wired the loop
        #: is silent in the same places, never broken.
        self.earcons = earcons
        #: Voice UX's switchable verbosity. Sits at the top of the answer
        #: ladder because "be brief" is a command about the system, not a
        #: question about the market.
        self.verbosity = verbosity
        #: Whether an unprompted event earns the voice at all.
        self.policy = policy or SpeechPolicy(Presence())
        #: The fail-open path (Orchestrator.md): anything the deterministic
        #: answerer declines goes here rather than going unanswered. Optional --
        #: with no reasoner the loop says so plainly instead of pretending.
        self.reasoner = reasoner
        self.stt = stt
        self.vad = vad or Vad()
        self._on_turn = on_turn
        self._on_reflex = on_reflex
        self.min_utterance_sec = min_utterance_sec
        self.max_utterance_sec = max_utterance_sec

        self._segments: queue.Queue[bytes] = queue.Queue(maxsize=8)
        self._current: list[bytes] = []
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        #: Frames of loud speech seen while Genesis is talking. Barge-in needs
        #: a few in a row -- see :meth:`_maybe_barge_in`.
        self._loud_while_speaking = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self.mic._on_frame = self._on_frame  # noqa: SLF001 - the mic is ours
        self._stop.clear()
        self._worker = threading.Thread(target=self._run_worker, name="voice-loop", daemon=True)
        self._worker.start()
        self.mic.open()

    def stop(self) -> None:
        self._stop.set()
        self.mic.close()
        self.speaker.stop()
        if self._worker is not None:
            self._worker.join(timeout=2.0)

    def __enter__(self) -> VoiceLoop:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- the audio thread --------------------------------------------------

    def _on_frame(self, frame: bytes) -> None:
        """Runs on PortAudio's thread. Must stay trivial."""
        if self.speaker.speaking:
            self._maybe_barge_in(frame)
            # Do not accumulate our own voice into an utterance.
            return

        self._loud_while_speaking = 0
        event = self.vad.push(frame)
        if event is SpeechEvent.STARTED:
            self._current = [frame]
        elif event is SpeechEvent.CONTINUING:
            self._current.append(frame)
            if len(self._current) * 0.02 > self.max_utterance_sec:
                self._flush()
        elif event is SpeechEvent.ENDED:
            self._current.append(frame)
            self._flush()

    def _maybe_barge_in(self, frame: bytes) -> None:
        """Cut speech when the user talks over it.

        Without acoustic echo cancellation the microphone also hears the
        speakers, so a bare VAD trip would make Genesis interrupt itself --
        exactly the failure Voice Stack records from the reference
        implementation. Two mitigations, both cheap:

        * a **raised threshold** while speaking, so room-level playback bleed
          does not clear the bar;
        * **three consecutive** loud frames (~60 ms), so a transient does not
          either.

        This is a mitigation, not a solution. The real fix is AEC or a headset,
        and until one is in place a loud speaker in an untreated room can still
        trigger a false barge-in. It fails in the safe direction -- a false
        barge-in costs a sentence, whereas a swallowed "stop" costs the
        interrupt working at all.
        """
        if rms(frame) < max(self.vad.start_threshold * 2.5, 0.05):
            self._loud_while_speaking = 0
            return
        self._loud_while_speaking += 1
        if self._loud_while_speaking >= 3:
            self._loud_while_speaking = 0
            self.speaker.stop()
            self.vad.reset()

    def _flush(self) -> None:
        if not self._current:
            return
        segment = b"".join(self._current)
        self._current = []
        if len(segment) / 2 / self.mic.sample_rate < self.min_utterance_sec:
            return  # a cough, a door, a keyboard
        try:
            self._segments.put_nowait(segment)
        except queue.Full:
            # Shedding is correct under load: the newest speech matters more
            # than a backlog, and blocking here would stall the audio thread.
            pass

    # -- the worker thread -------------------------------------------------

    def _run_worker(self) -> None:
        while not self._stop.is_set():
            try:
                segment = self._segments.get(timeout=0.2)
            except queue.Empty:
                # Idle. This is where a plan that outlived its await window
                # gets spoken -- on the thread that already owns the speaker,
                # rather than from a second thread racing it for the output.
                self._announce_completions()
                continue
            try:
                self._handle(segment)
            except Exception as exc:  # noqa: BLE001 - a bad turn must not end the loop
                self._emit(Turn(heard="", intent="error", path="exception", fields={"error": repr(exc)}))

    def _handle(self, segment: bytes) -> None:
        started = time.monotonic()
        turn = Turn(trace_id=new_trace_id())

        # 1. Local transcription and the wake decision, on this machine only.
        t0 = time.monotonic()
        woken, local_text = self.gate.examine(segment)
        turn.wake_ms = (time.monotonic() - t0) * 1000
        turn.heard = local_text
        if not local_text.strip():
            return

        # Presence, before classification: ambient chatter is the *strongest*
        # evidence you are in the room, precisely because it was not addressed
        # to Genesis. Voice UX's "speaks if you're present" depends on this.
        self.policy.presence.heard_something()

        directed_by_window = self.classifier.follow_up_open

        # 2. Classify. Reflexes and echo resolve here without any network.
        result = self.classifier.classify(local_text, ambient_context=self.memory.ambient.context())
        turn.intent = result.intent.value
        turn.path = result.path

        if result.intent is Intent.STOP and result.reflex is not None:
            self.speaker.stop()
            if self._on_reflex is not None:
                self._on_reflex(result.reflex)
            turn.fields["reflex"] = result.reflex.value
            turn.total_ms = (time.monotonic() - started) * 1000
            self._emit(turn)
            return

        if result.intent is Intent.ECHO:
            turn.total_ms = (time.monotonic() - started) * 1000
            self._emit(turn)
            return

        if not (result.actionable or (woken and directed_by_window)):
            # Ambient: buffer it, do nothing, never persist it.
            self.memory.ambient.add(local_text)
            turn.total_ms = (time.monotonic() - started) * 1000
            self._emit(turn)
            return

        # 3. Only now may the audio leave the machine.
        text = local_text
        if woken and self.stt is not None:
            claimed = self.gate.take()
            if claimed is not None:
                audio, _ = claimed
                t0 = time.monotonic()
                try:
                    transcript = self.stt.transcribe(audio, self.mic.sample_rate)
                    if transcript.text.strip():
                        text = transcript.text
                        turn.source = transcript.source
                except DegradedError as exc:
                    # The local transcript is already in hand. Keep going.
                    turn.source = "local"
                    turn.fields["stt_degraded"] = exc.reason
                turn.stt_ms = (time.monotonic() - t0) * 1000
        turn.heard = text

        self.memory.add_turn("user", text, trace_id=turn.trace_id)
        ambient = self.memory.ambient.context()
        if ambient:
            turn.fields["ambient_used"] = ambient
        self.memory.ambient.clear()

        # 4. Answer. Trivial questions never reach a model.
        answer = self.verbosity.answer(text) if self.verbosity is not None else None
        if answer is not None:
            turn.path = "verbosity"
            turn.fields["verbosity"] = self.verbosity.level.wire_name
        if answer is None:
            answer = self.answerer.answer(text)

        # 4b. Plan. Anything the reflex declined gets one attempt at a task
        # list before the large tier does the work itself. A decline here is
        # normal and cheap -- with no agents registered the planner returns
        # without calling a model at all.
        if answer is None and self.planner is not None and self.runner is not None:
            outcome = self.planner.plan(text, context=ambient)
            turn.fields["plan"] = outcome.reason
            if outcome.plan is not None:
                turn.fields["plan_tasks"] = len(outcome.plan.tasks)
                turn.path = "planned"
                # Voice Stack: anything needing agents blows the 1.5 s budget,
                # so acknowledge *before* the work, not after. The tone fires
                # here, ahead of the await window, because that is the whole
                # point of having one.
                self._earcon(Earcon.ACKNOWLEDGED)
                answer = self.runner.run(outcome.plan)

        if answer is None and self.reasoner is not None:
            # Default down, then escalate: the calendar reflex gets first
            # refusal, and only what it declines costs a hosted round trip.
            answer = self.reasoner.answer(text, context=ambient)
        if answer is None:
            # Nothing deterministic fit and the large tier is unavailable or
            # declined. Say so rather than going quiet -- the fail-open rule is
            # that the user is never left unanswered.
            reply = "I can't reach my reasoning model right now."
            source = "unhandled"
        else:
            reply = answer.text
            source = answer.source

        turn.spoken = reply
        turn.source = turn.source or source
        self.memory.add_turn("genesis", reply, trace_id=turn.trace_id)

        spoken = self.speaker.say(reply, trace_id=turn.trace_id)
        turn.fields["outcome"] = spoken.outcome.value
        # 5. Leave the door open for a follow-up without the wake word.
        self.classifier.open_follow_up()

        turn.total_ms = (time.monotonic() - started) * 1000
        self._emit(turn)

    def _announce_completions(self) -> None:
        """Speak plans that finished after their await window closed.

        Deliberately quiet while Genesis is already speaking, and deliberately
        one sentence per plan: a backtest finishing is worth an interruption,
        and four of them at once is not.
        """
        if self.runner is None or self.speaker.speaking:
            return
        try:
            answers = self.runner.collect()
        except Exception as exc:  # noqa: BLE001 - never end the loop over this
            self._emit(Turn(intent="error", path="collect", fields={"error": repr(exc)}))
            return

        for answer in answers:
            if not self.policy.should_speak(REQUESTED):
                # Cannot happen with the shipped table -- work you asked for is
                # ALWAYS -- but the gate is here rather than assumed, so a
                # future policy change cannot make this the one path that
                # ignores it.
                self._emit(Turn(intent="plan.done", path="withheld", source=answer.source))
                continue
            if answer.source.endswith(":failed"):
                self._earcon(Earcon.COMPONENT_DOWN)
            turn = Turn(
                intent="plan.done",
                path="announce",
                spoken=answer.text,
                source=answer.source,
                trace_id=new_trace_id(),
            )
            self.memory.add_turn("genesis", answer.text, trace_id=turn.trace_id)
            spoken = self.speaker.say(answer.text, trace_id=turn.trace_id)
            turn.fields["outcome"] = spoken.outcome.value
            # A result you did not ask for still opens a follow-up window: the
            # natural next thing you say is "what's the invalidation?", and it
            # will not carry the wake word.
            self.classifier.open_follow_up()
            self._emit(turn)

    def _earcon(self, earcon: Earcon) -> None:
        if self.earcons is not None:
            self.earcons.play(earcon)

    def _emit(self, turn: Turn) -> None:
        if self._on_turn is not None:
            self._on_turn(turn)
