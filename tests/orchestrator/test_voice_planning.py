# Spec: Genesis Markdown/10-Architecture/Orchestrator.md
"""The answer ladder, end to end: reflex, then plan, then large tier.

Same fakes as ``tests/test_voice_loop.py`` -- no microphone, no speaker, no
network -- with a real bus and a scripted planning model behind them.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from genesis.bus.bus import TaskBus
from genesis.bus.task import TaskState
from genesis.llm.backend import Completion
from genesis.memory.working import WorkingMemory
from genesis.orchestrator.answers import Answer, TrivialAnswerer
from genesis.orchestrator.intent import IntentClassifier
from genesis.orchestrator.loop import VoiceLoop
from genesis.orchestrator.planner import Planner
from genesis.orchestrator.registry import Capability, CapabilityRegistry
from genesis.orchestrator.runner import PlanRunner
from genesis.orchestrator.tools import OrchestratorTools
from genesis.voice.capture import Microphone
from genesis.voice.echo import EchoFilter
from genesis.voice.player import NullPlayer
from genesis.voice.speaker import Speaker
from genesis.voice.wake import WakeGate

from test_voice_loop import FakeDetector, FakeTTS

SCAN = (
    '{"tasks": [{"id": "t1", "type": "screen.sector", "agent": "screener", '
    '"args": {"sector": "semiconductors"}}], "speak_after": "t1"}'
)


class ScriptedBackend:
    model = "fake-small"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 256, temperature: float = 0.0) -> Completion:  # noqa: ARG002
        self.calls += 1
        return Completion(text=self.reply, model=self.model, latency_ms=1.0)


class FixedReasoner:
    def __init__(self, text: str = "I don't have an agent for that yet.") -> None:
        self.text = text
        self.calls = 0

    def answer(self, text: str, *, context: str = "") -> Answer:  # noqa: ARG002
        self.calls += 1
        return Answer(self.text, "llm:fake")


@pytest.fixture
def bus(tmp_path: Path) -> TaskBus:
    b = TaskBus(tmp_path / "genesis.db")
    yield b
    b.close()


def build(script: dict[bytes, str], *, bus: TaskBus, reply: str = SCAN, registered: bool = True):
    registry = CapabilityRegistry()
    if registered:
        registry.register(
            Capability(
                agent="screener",
                family="research",
                summary="Runs saved scans across the universe.",
                task_types=("screen.sector",),
            )
        )
    echo = EchoFilter()
    tts = FakeTTS()
    memory = WorkingMemory()
    tools = OrchestratorTools(bus)
    backend = ScriptedBackend(reply)
    reasoner = FixedReasoner()
    turns: list = []
    loop = VoiceLoop(
        mic=Microphone(),
        gate=WakeGate(FakeDetector(script)),
        speaker=Speaker([tts], NullPlayer(), echo=echo),
        classifier=IntentClassifier(echo=echo),
        memory=memory,
        answerer=TrivialAnswerer(),
        planner=Planner(backend, registry),
        runner=PlanRunner(tools, memory=memory, await_ms=50),
        reasoner=reasoner,
        on_turn=turns.append,
    )
    return loop, turns, tts, backend, reasoner, tools


def test_a_request_with_an_agent_for_it_becomes_a_dispatched_plan(bus: TaskBus) -> None:
    audio = b"P1"
    loop, turns, tts, _backend, reasoner, _tools = build(
        {audio: "Genesis, screen semiconductors for me"}, bus=bus
    )
    loop._handle(audio)

    assert turns[0].path == "planned"
    assert turns[0].fields["plan_tasks"] == 1
    assert "I'll tell you when it's done" in turns[0].spoken
    assert tts.said, "the acknowledgement never reached the voice"
    assert reasoner.calls == 0, "the large tier was paid for work the plan took"

    pending = bus.by_state(TaskState.PENDING)
    assert [t.type for t in pending] == ["screen.sector"]
    assert pending[0].args == {"sector": "semiconductors"}


def test_a_trivial_question_never_reaches_the_planner(bus: TaskBus) -> None:
    audio = b"P2"
    loop, turns, _tts, backend, reasoner, _tools = build(
        {audio: "Genesis, what time does the market open?"}, bus=bus
    )
    loop._handle(audio)
    assert backend.calls == 0 and reasoner.calls == 0
    assert "market" in turns[0].spoken.lower()


def test_an_unplannable_request_falls_through_to_the_large_tier(bus: TaskBus) -> None:
    audio = b"P3"
    loop, turns, _tts, _backend, reasoner, _tools = build(
        {audio: "Genesis, what do you make of all this?"}, bus=bus, reply='{"tasks": []}'
    )
    loop._handle(audio)
    assert reasoner.calls == 1
    assert turns[0].fields["plan"] == "no registered agent can do that"
    assert turns[0].spoken == "I don't have an agent for that yet."


def test_with_no_agents_registered_planning_costs_nothing(bus: TaskBus) -> None:
    audio = b"P4"
    loop, turns, _tts, backend, reasoner, _tools = build(
        {audio: "Genesis, screen semiconductors for me"}, bus=bus, registered=False
    )
    loop._handle(audio)
    assert backend.calls == 0, "a model was called with nothing to plan for"
    assert reasoner.calls == 1
    assert turns[0].fields["plan"] == "no agents are registered to plan for"


def test_a_broken_planner_still_answers(bus: TaskBus) -> None:
    """Orchestrator acceptance: with the planner deliberately broken, requests
    still get answered."""
    audio = b"P5"
    loop, turns, _tts, _backend, reasoner, _tools = build(
        {audio: "Genesis, screen semiconductors for me"}, bus=bus, reply="I'd love to help!"
    )
    loop._handle(audio)
    assert reasoner.calls == 1
    assert turns[0].spoken == "I don't have an agent for that yet."


def test_a_finished_plan_is_announced_while_the_loop_is_idle(bus: TaskBus) -> None:
    audio = b"P6"
    loop, turns, tts, _backend, _reasoner, tools = build(
        {audio: "Genesis, screen semiconductors for me"}, bus=bus
    )
    loop._handle(audio)
    tts.said.clear()

    # The daemon finishes the work a moment later.
    task = bus.by_state(TaskState.PENDING)[0]
    bus.complete(task.id, {"spoken_summary": "Four candidates. Top is NVDA."})

    loop._announce_completions()
    assert tts.said == ["Four candidates. Top is NVDA."]
    assert turns[-1].intent == "plan.done"
    # A volunteered result opens a follow-up window: "what's the invalidation?"
    # will not carry the wake word.
    assert loop.classifier.follow_up_open


def test_nothing_is_announced_while_genesis_is_speaking(bus: TaskBus) -> None:
    audio = b"P7"
    loop, _turns, tts, _backend, _reasoner, _tools = build(
        {audio: "Genesis, screen semiconductors for me"}, bus=bus
    )
    loop._handle(audio)
    task = bus.by_state(TaskState.PENDING)[0]
    bus.complete(task.id, {"spoken_summary": "Four candidates."})
    tts.said.clear()

    class Speaking:
        speaking = True

        def stop(self) -> None: ...

    loop.speaker = Speaking()
    loop._announce_completions()
    assert tts.said == []
