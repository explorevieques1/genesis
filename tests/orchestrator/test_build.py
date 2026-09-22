# Spec: Genesis Markdown/10-Architecture/Voice Stack.md
"""Assembly. The wiring is the thing most likely to be silently wrong.

Every component here is unit-tested elsewhere; what this file asserts is that
they are actually *connected* -- the failure where each part works and the
system does nothing, which no amount of component testing catches.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genesis.bus.bus import TaskBus
from genesis.config import load_config
from genesis.orchestrator import build as build_module
from genesis.orchestrator.build import build_voice_loop
from genesis.orchestrator.verbosity import Verbosity


class FakeDetector:
    """Stands in for local Whisper, which is a 40 MB download and a GPU-less
    second of load time -- neither of which belongs in a wiring test."""

    aliases = ("genesis",)

    def __init__(self, *_a, **_k) -> None:
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def detect(self, pcm: bytes, sample_rate: int):  # noqa: ARG002
        return None

    def transcribe(self, pcm: bytes, sample_rate: int) -> str:  # noqa: ARG002
        return ""


@pytest.fixture(autouse=True)
def no_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_module, "LocalWhisperWake", FakeDetector)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)


@pytest.fixture
def config():
    return load_config(None)


@pytest.fixture
def bus(tmp_path: Path) -> TaskBus:
    b = TaskBus(tmp_path / "genesis.db")
    yield b
    b.close()


def test_a_bus_less_build_still_produces_a_working_loop(config) -> None:
    """Voice is a surface, not the spine: no bus means a quieter Genesis, not
    a broken one."""
    stack = build_voice_loop(config, silent=True)
    assert stack.loop is not None
    assert stack.recorder is None
    assert any("no task bus" in n for n in stack.notes)
    stack.close()


def test_with_a_bus_everything_is_wired(config, bus: TaskBus) -> None:
    stack = build_voice_loop(config, silent=True, bus=bus)
    try:
        assert stack.recorder is not None, "turns would not be recorded"
        assert stack.tools is not None, "there would be nothing to dispatch onto"
        assert stack.loop.runner is not None
        assert stack.loop.earcons is not None
        assert stack.loop.verbosity is not None
        assert stack.loop.policy is not None
        assert stack.registry is not None
    finally:
        stack.close()


def test_rolloff_reaches_the_episodic_log_through_the_assembled_stack(
    config, bus: TaskBus
) -> None:
    stack = build_voice_loop(config, silent=True, bus=bus)
    try:
        stack.memory.max_turns = 1
        stack.memory.add_turn("user", "what's my exposure")
        stack.memory.add_turn("genesis", "Two positions.")
        assert bus.log.by_kind("conversation.rolloff"), "rolled turns were dropped"
    finally:
        stack.close()


def test_a_second_session_restores_the_first_ones_summary(config, bus: TaskBus) -> None:
    first = build_voice_loop(config, silent=True, bus=bus)
    first.recorder.on_turn(
        type("T", (), {"heard": "how did semis close", "intent": "directed", "spoken": "Down 1%.",
                       "path": "llm", "source": "llm:test", "fields": {}, "wake_ms": 0.0,
                       "stt_ms": 0.0, "total_ms": 0.0, "trace_id": ""})()
    )
    first.close()

    second = build_voice_loop(config, silent=True, bus=bus)
    try:
        assert any("restored the conversation" in n for n in second.notes)
        assert "how did semis close" in second.memory.transcript()
    finally:
        second.close()


def test_verbosity_comes_from_config(config, bus: TaskBus) -> None:
    stack = build_voice_loop(config, silent=True, bus=bus)
    try:
        assert stack.verbosity.level is Verbosity.BRIEF  # the shipped default
    finally:
        stack.close()


def test_the_earcons_are_rendered_before_the_microphone_opens(config, bus: TaskBus) -> None:
    """Cold-start latency destroys the voice budget, and an earcon that has to
    be computed before it can be heard is not an earcon."""
    stack = build_voice_loop(config, silent=True, bus=bus)
    try:
        assert len(stack.loop.earcons._cache) == 7
    finally:
        stack.close()


def test_silent_mode_reaches_the_earcons_too(config, bus: TaskBus) -> None:
    stack = build_voice_loop(config, silent=True, bus=bus)
    try:
        assert stack.loop.earcons.enabled is False
    finally:
        stack.close()


# --------------------------------------------------------------------------
# The tool surface
# --------------------------------------------------------------------------


class _FakeGateway:
    """Just enough gateway for the wiring assertions."""

    def __init__(self, granted=("srv.a", "srv.b")):
        self._granted = tuple(granted)

    def tools_for(self, agent):  # noqa: ARG002
        return self._granted


def test_without_a_gateway_the_orchestrator_has_no_bridge(config) -> None:
    """A tool-less build is the quieter configuration, not a broken one --
    but it must say so rather than look identical to a working one."""
    stack = build_voice_loop(config, silent=True)
    assert stack.bridge is None
    assert any("without tools" in n for n in stack.notes)


def test_a_gateway_gives_the_orchestrator_a_bridge(config) -> None:
    stack = build_voice_loop(config, silent=True, gateway=_FakeGateway())
    assert stack.bridge is not None
    assert stack.bridge.agent == "orchestrator"
    assert any("can reach 2 tools" in n for n in stack.notes)


def test_a_gateway_that_grants_nothing_is_reported_not_hidden(config) -> None:
    """The failure that looks like success: the gateway is up, the allow-list
    is empty, and every answer is silently tool-less."""
    stack = build_voice_loop(config, silent=True, gateway=_FakeGateway(granted=()))
    assert any("granted no tools" in n for n in stack.notes)


def test_the_bridge_reaches_the_reasoner_not_just_the_stack(config) -> None:
    """The stack field is for inspection; what matters is that the answer path
    actually has it."""
    stack = build_voice_loop(config, silent=True, gateway=_FakeGateway())
    reasoner = stack.loop.reasoner
    if reasoner is not None:  # absent when no ANTHROPIC_API_KEY is set
        assert reasoner.bridge is stack.bridge
