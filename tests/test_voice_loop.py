# Spec: Genesis Markdown/10-Architecture/Orchestrator.md
"""The voice loop's acceptance criteria, with the audio faked out.

Nothing here touches a microphone, a speaker, or the network. The pieces that
would (wake detection, STT, TTS) are replaced by stubs, which is possible only
because each of them sits behind a narrow interface -- and is the reason they
do.
"""

from __future__ import annotations

import time

from genesis.memory.working import WorkingMemory
from genesis.orchestrator.answers import TrivialAnswerer
from genesis.orchestrator.intent import Intent, IntentClassifier
from genesis.orchestrator.loop import VoiceLoop
from genesis.voice.capture import Microphone
from genesis.voice.echo import EchoFilter
from genesis.voice.player import NullPlayer
from genesis.voice.reflex import Reflex
from genesis.voice.speaker import Speaker
from genesis.voice.stt import Transcript
from genesis.voice.wake import WakeGate


class FakeDetector:
    """Stands in for local Whisper. ``script`` maps audio bytes to a transcript."""

    aliases = ("genesis",)

    def __init__(self, script: dict[bytes, str]) -> None:
        self.script = script

    def transcribe(self, pcm: bytes, sample_rate: int) -> str:  # noqa: ARG002
        return self.script.get(pcm, "")

    def detect(self, pcm: bytes, sample_rate: int):  # noqa: ARG002
        from genesis.voice.wake import WakeHit

        text = self.script.get(pcm, "")
        return WakeHit(text, 0.0) if "genesis" in text.lower() else None


class FakeSTT:
    """A Scribe stand-in that 'improves' the local transcript."""

    def __init__(self) -> None:
        self.calls: list[bytes] = []

    def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:  # noqa: ARG002
        self.calls.append(pcm)
        return Transcript(text="what time does the market open", source="scribe")


class FakeTTS:
    sample_rate = 24_000

    def __init__(self) -> None:
        self.said: list[str] = []

    def stream(self, text: str):
        self.said.append(text)
        yield b"\x00\x00" * 100


def build(script: dict[bytes, str], *, stt=None):
    echo = EchoFilter()
    tts = FakeTTS()
    speaker = Speaker([tts], NullPlayer(), echo=echo)
    memory = WorkingMemory()
    turns: list = []
    loop = VoiceLoop(
        mic=Microphone(),
        gate=WakeGate(FakeDetector(script)),
        speaker=speaker,
        classifier=IntentClassifier(echo=echo),
        memory=memory,
        answerer=TrivialAnswerer(),
        stt=stt,
        on_turn=turns.append,
    )
    return loop, turns, memory, tts


def test_a_directed_question_is_answered_aloud():
    audio = b"A"
    loop, turns, memory, tts = build({audio: "Genesis, what time does the market open?"})
    loop._handle(audio)

    assert turns[0].intent == Intent.DIRECTED.value
    assert turns[0].spoken
    assert "market" in turns[0].spoken.lower()
    assert tts.said, "nothing reached the voice"
    assert len(memory.turns()) == 2  # the question and the answer


def test_ambient_conversation_produces_no_action():
    """Voice UX: ten minutes of ambient conversation produces zero unprompted
    speech. The loop must buffer it and stay silent."""
    audio = b"B"
    loop, turns, memory, tts = build({audio: "I think semiconductors are extended here"})
    loop._handle(audio)

    assert turns[0].intent == Intent.AMBIENT.value
    assert turns[0].spoken == ""
    assert tts.said == []
    assert memory.turns() == []          # nothing entered the conversation
    assert "semiconductors" in memory.ambient.context()


def test_ambient_audio_never_leaves_the_machine():
    """The wake gate is the boundary. Un-addressed audio must never reach STT."""
    audio = b"C"
    stt = FakeSTT()
    loop, _turns, _memory, _tts = build({audio: "just chatting about the weather"}, stt=stt)
    loop._handle(audio)
    assert stt.calls == [], "un-addressed audio was sent to the cloud"


def test_addressed_audio_does_reach_stt():
    audio = b"D"
    stt = FakeSTT()
    loop, turns, _memory, _tts = build({audio: "Genesis what time does the market open"}, stt=stt)
    loop._handle(audio)
    assert stt.calls == [audio]
    assert turns[0].source == "scribe"


def test_halt_fires_without_any_model_and_cuts_speech():
    audio = b"E"
    loop, turns, _memory, tts = build({audio: "Genesis, halt"})
    fired: list[Reflex] = []
    loop._on_reflex = fired.append
    loop._handle(audio)

    assert fired == [Reflex.HALT]
    assert turns[0].intent == Intent.STOP.value
    assert turns[0].path == "reflex"
    assert tts.said == []          # a reflex speaks nothing
    assert turns[0].total_ms < 50  # no network, no model


def test_a_follow_up_needs_no_wake_word():
    first, second = b"F", b"G"
    loop, turns, _memory, _tts = build({
        first: "Genesis, what time does the market open?",
        second: "and when does it close",
    })
    loop._handle(first)
    loop._handle(second)
    assert turns[1].intent == Intent.FOLLOW_UP.value
    assert turns[1].spoken


def test_the_follow_up_window_closes():
    first, second = b"H", b"I"
    loop, turns, _memory, _tts = build({
        first: "Genesis, what time does the market open?",
        second: "so anyway I was saying about the weather",
    })
    loop._handle(first)
    loop.classifier.close_follow_up()
    loop._handle(second)
    assert turns[1].intent == Intent.AMBIENT.value


def test_an_unhandled_request_still_gets_an_answer():
    """The planner's fail-open rule: never leave the user unanswered."""
    audio = b"J"
    loop, turns, _memory, tts = build({audio: "Genesis, find me a long setup in semis"})
    loop._handle(audio)
    assert turns[0].spoken
    assert tts.said


def test_a_failing_turn_does_not_kill_the_loop():
    audio = b"K"
    loop, turns, _memory, _tts = build({audio: "Genesis, what time does the market open?"})

    def boom(text):  # noqa: ANN001, ARG001
        raise RuntimeError("planner exploded")

    loop.answerer.answer = boom
    loop._segments.put(audio)
    import threading

    worker = threading.Thread(target=loop._run_worker, daemon=True)
    loop._stop.clear()
    worker.start()
    time.sleep(0.4)
    loop._stop.set()
    worker.join(timeout=1)
    assert turns and turns[0].intent == "error"


def test_the_follow_up_window_does_not_swallow_a_conversation():
    """Found by the live end-to-end test: Genesis answered, the window opened,
    and the next two sentences of human-to-human conversation were answered
    too. Voice UX's "zero unprompted speech" outranks the window."""
    first, chat = b"L", b"M"
    loop, turns, _memory, tts = build({
        first: "Genesis, what time does the market open?",
        chat: "I really think semiconductors are extended here honestly",
    })
    loop._handle(first)
    loop._handle(chat)          # immediately, well inside the window

    assert turns[1].intent == Intent.AMBIENT.value
    assert turns[1].path == "window-too-long"
    assert len(tts.said) == 1, "Genesis answered the room"


def test_a_short_follow_up_is_still_understood():
    first, follow = b"N", b"O"
    loop, turns, _memory, _tts = build({
        first: "Genesis, what time does the market open?",
        follow: "and when does it close",
    })
    loop._handle(first)
    loop._handle(follow)
    assert turns[1].intent == Intent.FOLLOW_UP.value
    assert turns[1].spoken


class FakeReasoner:
    """Stands in for the large tier."""

    def __init__(self, reply: str | None = "Semis are extended on the weekly.") -> None:
        self.reply = reply
        self.calls: list[str] = []

    def answer(self, text: str, *, context: str = ""):  # noqa: ARG002
        self.calls.append(text)
        if self.reply is None:
            return None
        from genesis.orchestrator.answers import Answer

        return Answer(self.reply, "llm:claude-opus-5")


def test_the_calendar_answers_before_the_large_tier_is_asked():
    """LLM Model Tiers' "default down": only what the reflex declines costs a
    hosted round trip."""
    audio = b"P"
    loop, turns, _memory, _tts = build({audio: "Genesis, what time does the market open?"})
    loop.reasoner = FakeReasoner()
    loop._handle(audio)
    assert loop.reasoner.calls == [], "a deterministic answer still hit the model"
    assert turns[0].source == "calendar"


def test_what_the_calendar_declines_reaches_the_large_tier():
    audio = b"Q"
    loop, turns, _memory, tts = build({audio: "Genesis, what do you make of semis here?"})
    loop.reasoner = FakeReasoner()
    loop._handle(audio)
    assert loop.reasoner.calls, "the fail-open path was never taken"
    assert turns[0].source == "llm:claude-opus-5"
    assert tts.said


def test_a_dead_large_tier_still_answers_something():
    """Never leave the user unanswered -- and never hang the voice on it."""
    audio = b"R"
    loop, turns, _memory, tts = build({audio: "Genesis, what do you make of semis here?"})
    loop.reasoner = FakeReasoner(reply=None)
    loop._handle(audio)
    assert turns[0].spoken
    assert turns[0].source == "unhandled"
    assert tts.said
