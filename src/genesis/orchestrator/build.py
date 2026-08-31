# Spec: Genesis Markdown/10-Architecture/Voice Stack.md
"""Assembling the voice loop from config.

One place where :class:`~genesis.config.Config` becomes running components, so
that the CLI, the daemon and the tests all get the same wiring. The ordering
here is not incidental: every slow thing is warmed *before* the microphone
opens, because LLM Model Tiers is explicit that cold starts destroy the Voice
Stack budget, and the first thing you say should not be the request that pays
for a 40-second model load.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from genesis.bus.bus import TaskBus
from genesis.config import Config
from genesis.errors import DegradedError
from genesis.memory.working import WorkingMemory
from genesis.orchestrator.answers import TrivialAnswerer
from genesis.orchestrator.intent import IntentClassifier
from genesis.orchestrator.loop import VoiceLoop
from genesis.orchestrator.planner import Planner
from genesis.orchestrator.record import VoiceRecorder
from genesis.orchestrator.registry import CapabilityRegistry
from genesis.orchestrator.runner import PlanRunner
from genesis.orchestrator.tools import OrchestratorTools
from genesis.orchestrator.verbosity import VerbosityControl
from genesis.voice.capture import SAMPLE_RATE, Microphone
from genesis.voice.earcons import EarconPlayer
from genesis.voice.echo import EchoFilter
from genesis.voice.policy import Presence, SpeechPolicy
from genesis.voice.player import NullPlayer, Player
from genesis.voice.speaker import Speaker, default_backends
from genesis.voice.stt import ScribeSTT
from genesis.voice.wake import LocalWhisperWake, WakeGate

__all__ = ["VoiceStack", "build_voice_loop"]


@dataclass
class VoiceStack:
    """The assembled parts, so callers can inspect and shut them down."""

    loop: VoiceLoop
    speaker: Speaker
    memory: WorkingMemory
    gate: WakeGate
    notes: list[str]
    """Degradations found while assembling -- reported, never swallowed."""

    tools: OrchestratorTools | None = None
    registry: CapabilityRegistry | None = None
    recorder: VoiceRecorder | None = None
    verbosity: VerbosityControl | None = None
    policy: SpeechPolicy | None = None

    def close(self) -> None:
        self.loop.stop()


def build_voice_loop(
    config: Config,
    *,
    silent: bool = False,
    on_turn=None,
    wake_model: str = "tiny.en",
    bus: TaskBus | None = None,
    registry: CapabilityRegistry | None = None,
    supervisor=None,
    scheduler=None,
    kill_switch=None,
) -> VoiceStack:
    """Build the loop described by ``config``.

    Missing optional pieces degrade rather than raise: no API key means local
    transcription and no cloud voice, which is a quieter Genesis rather than a
    broken one.
    """
    notes: list[str] = []
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        notes.append("ELEVENLABS_API_KEY not set - cloud voice and Scribe unavailable")

    voice_id = config.identity.voice_id
    if not voice_id:
        notes.append("identity.voice_id is unset - using the premade fallback voice")

    echo = EchoFilter()
    player = NullPlayer() if silent else Player(sample_rate=24_000)
    backends = default_backends(voice_id or "", api_key=api_key) if api_key else []
    if not backends:
        notes.append("no TTS backend available - Genesis will answer silently")
        from genesis.voice.tts import PiperTTS  # noqa: F401  (documents the fallback slot)

    speaker = Speaker(backends or [_SilentBackend()], player, echo=echo)

    detector = LocalWhisperWake(config.identity.wake_word, model_size=wake_model)
    detector.load()  # slow, deliberate, and before the mic opens
    gate = WakeGate(detector, sample_rate=SAMPLE_RATE)

    stt = None
    if api_key and config.voice.stt == "elevenlabs":
        try:
            stt = ScribeSTT(api_key=api_key)
        except DegradedError as exc:
            notes.append(f"Scribe unavailable: {exc.reason}")

    # Durable conversation. Working Memory is explicit that rolloff is
    # summarisation rather than deletion, and that a restart restores a
    # summary -- both need the Episodic Log, so a bus-less build gets neither
    # and says so instead of silently dropping turns.
    recorder = VoiceRecorder(bus.log) if bus is not None else None
    memory = WorkingMemory(on_rolloff=recorder.on_rolloff if recorder else None)
    if recorder is not None:
        summary = recorder.restore_summary()
        if summary:
            memory.restore(summary=summary)
            notes.append("restored the conversation summary from the last session")
    else:
        notes.append("no task bus - turns are not recorded and roll off is dropped")

    verbosity = VerbosityControl(config.identity.verbosity)
    policy = SpeechPolicy(Presence())
    earcons = EarconPlayer(player, enabled=not silent)
    earcons.warm()  # rendered before the mic opens, never on the latency path

    # The large tier -- the fail-open answer path. Absent means a quieter
    # Genesis, not a broken one, so a missing key is a note rather than a raise.
    reasoner = None
    if config.llm.large.backend == "anthropic":
        try:
            from genesis.llm.anthropic_backend import AnthropicBackend
            from genesis.orchestrator.reasoner import Reasoner

            reasoner = Reasoner(
                AnthropicBackend(config.llm.large.model), verbosity=verbosity
            )
        except DegradedError as exc:
            notes.append(f"large tier unavailable: {exc.reason}")
    elif config.llm.large.backend != "none":
        notes.append(f"large tier backend {config.llm.large.backend!r} is not wired yet")

    # The planning path. Both halves or neither: a planner with no bus has
    # nowhere to dispatch, and a runner with no planner has nothing to run.
    #
    # The registry is empty until Phase 4 registers a read-only agent, and an
    # empty registry means the planner declines *without calling a model*. So
    # wiring this in now costs one SQLite handle and zero tokens per turn --
    # and the day the screener is registered, planning starts working with no
    # further change here.
    registry = registry if registry is not None else CapabilityRegistry()
    tools: OrchestratorTools | None = None
    planner = None
    runner = None
    if bus is not None:
        tools = OrchestratorTools(
            bus,
            supervisor=supervisor,
            scheduler=scheduler,
            kill_switch=kill_switch,
            approval_mode=config.approval.mode,
        )
        runner = PlanRunner(tools, memory=memory)
        if config.llm.small.backend == "anthropic":
            try:
                from genesis.llm.anthropic_backend import AnthropicBackend

                planner = Planner(
                    AnthropicBackend(config.llm.small.model),
                    registry,
                    verbosity=config.identity.verbosity,
                )
            except DegradedError as exc:
                notes.append(f"planner unavailable: {exc.reason}")
        elif config.llm.small.backend != "none":
            notes.append(f"small tier backend {config.llm.small.backend!r} is not wired yet")
        if planner is not None and not registry:
            notes.append("no agents registered - the planner will decline until Phase 4")
    else:
        notes.append("no task bus - planning is off, answers come from the large tier")

    classifier = IntentClassifier(wake_word=config.identity.wake_word, echo=echo)
    loop = VoiceLoop(
        mic=Microphone(),
        gate=gate,
        speaker=speaker,
        classifier=classifier,
        memory=memory,
        answerer=TrivialAnswerer(),
        planner=planner,
        runner=runner,
        reasoner=reasoner,
        earcons=earcons,
        verbosity=verbosity,
        policy=policy,
        stt=stt,
        on_turn=_fanout(recorder.on_turn if recorder else None, on_turn),
    )
    return VoiceStack(
        loop=loop,
        speaker=speaker,
        memory=memory,
        gate=gate,
        notes=notes,
        tools=tools,
        registry=registry,
        recorder=recorder,
        verbosity=verbosity,
        policy=policy,
    )


def _fanout(*sinks):
    """Combine turn sinks, skipping the ones that are not wired.

    The recorder and the console printer both want every turn, and neither
    should have to know about the other. A raising sink is swallowed rather
    than propagated -- one of these writes to a database, and the other is a
    print statement, and neither is worth ending a conversation over.
    """
    live = [s for s in sinks if s is not None]
    if not live:
        return None
    if len(live) == 1:
        return live[0]

    def emit(turn) -> None:  # noqa: ANN001
        for sink in live:
            try:
                sink(turn)
            except Exception:  # noqa: BLE001 - voice is a surface, not the spine
                pass

    return emit


class _SilentBackend:
    """Produces no audio. Keeps the Speaker's contract when nothing is wired."""

    sample_rate = 24_000

    def stream(self, text: str):  # noqa: ANN201, ARG002
        return iter(())
