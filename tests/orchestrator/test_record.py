# Spec: Genesis Markdown/40-Memory/Working Memory.md
"""What gets written down, and — more importantly — what does not."""

from __future__ import annotations

from pathlib import Path

import pytest

from genesis.memory.episodic import EpisodicLog
from genesis.memory.working import WorkingMemory
from genesis.orchestrator.loop import Turn
from genesis.orchestrator.record import VoiceRecorder


@pytest.fixture
def log(tmp_path: Path) -> EpisodicLog:
    lg = EpisodicLog(tmp_path / "genesis.db")
    yield lg
    lg.close()


@pytest.fixture
def recorder(log: EpisodicLog) -> VoiceRecorder:
    return VoiceRecorder(log)


# -- privacy ------------------------------------------------------------------


def test_ambient_speech_is_counted_never_quoted(recorder: VoiceRecorder, log: EpisodicLog) -> None:
    """The wake gate keeps un-addressed audio off the network. Writing its
    transcript to disk would give that most of its value away."""
    recorder.on_turn(Turn(heard="I think semis are extended here", intent="ambient"))
    entry = log.by_kind("voice.ambient")[0]
    assert entry.payload["words"] == 6
    assert "semis" not in str(entry.payload)
    assert "semis" not in (entry.summary or "")


def test_a_directed_turn_is_recorded_in_full(recorder: VoiceRecorder, log: EpisodicLog) -> None:
    recorder.on_turn(
        Turn(
            heard="what time does the market open",
            intent="directed",
            path="trivial",
            spoken="The market opens at 09:30.",
            source="calendar",
            total_ms=12.5,
        )
    )
    entry = log.by_kind("voice.turn")[0]
    assert entry.payload["heard"] == "what time does the market open"
    assert entry.payload["spoken"] == "The market opens at 09:30."
    assert entry.payload["path"] == "trivial"
    assert entry.payload["total_ms"] == 12.5


def test_an_echo_turn_is_recorded_without_the_text(recorder: VoiceRecorder, log: EpisodicLog) -> None:
    recorder.on_turn(Turn(heard="The market opens at 09:30.", intent="echo"))
    entry = log.by_kind("voice.echo")[0]
    assert "09:30" not in str(entry.payload)


# -- the trace ----------------------------------------------------------------


def test_a_reflex_is_recorded_as_a_reflex(recorder: VoiceRecorder, log: EpisodicLog) -> None:
    recorder.on_turn(Turn(heard="Genesis halt", intent="stop", path="reflex", fields={"reflex": "halt"}))
    entry = log.by_kind("voice.reflex")[0]
    assert entry.payload["reflex"] == "halt"


def test_a_planned_turn_records_the_bus_trace(recorder: VoiceRecorder, log: EpisodicLog) -> None:
    # The link between "what I said" and "the tasks it produced".
    recorder.on_turn(
        Turn(heard="screen semis", intent="directed", path="planned", source="plan:tr_123:running")
    )
    assert log.by_kind("voice.turn")[0].payload["plan_id"] == "tr_123"


def test_a_declined_plan_records_why(recorder: VoiceRecorder, log: EpisodicLog) -> None:
    recorder.on_turn(
        Turn(
            heard="find me something good",
            intent="directed",
            spoken="I don't have an agent for that yet.",
            fields={"plan": "no agents are registered to plan for"},
        )
    )
    assert log.by_kind("voice.turn")[0].payload["plan"] == "no agents are registered to plan for"


def test_a_degraded_turn_is_flagged_degraded(recorder: VoiceRecorder, log: EpisodicLog) -> None:
    recorder.on_turn(Turn(heard="hello", intent="directed", fields={"stt_degraded": "Scribe timed out"}))
    assert log.by_kind("voice.turn")[0].degraded is True


def test_a_turn_that_raised_is_recorded_as_an_error(recorder: VoiceRecorder, log: EpisodicLog) -> None:
    recorder.on_turn(Turn(intent="error", path="exception", fields={"error": "RuntimeError()"}))
    assert log.by_kind("voice.error")[0].degraded is True


# -- rolloff is summarisation, not deletion -----------------------------------


def test_turns_rolling_out_of_working_memory_are_preserved(
    recorder: VoiceRecorder, log: EpisodicLog
) -> None:
    memory = WorkingMemory(max_turns=2, on_rolloff=recorder.on_rolloff)
    memory.add_turn("user", "what's the open")
    memory.add_turn("genesis", "09:30.")
    memory.add_turn("user", "and the close")

    assert len(memory.turns()) == 2  # the live buffer stayed capped
    rolled = log.by_kind("conversation.rolloff")[0]
    assert rolled.payload["turns"] == [{"speaker": "user", "text": "what's the open"}]


# -- restart continuity -------------------------------------------------------


def test_a_restart_restores_a_summary_not_the_transcript(
    recorder: VoiceRecorder, log: EpisodicLog
) -> None:
    for heard in ("what's my exposure", "how did semis close"):
        recorder.on_turn(Turn(heard=heard, intent="directed", spoken="..."))

    summary = recorder.restore_summary()
    assert summary is not None
    assert "what's my exposure" in summary and "how did semis close" in summary

    memory = WorkingMemory()
    memory.restore(summary=summary)
    assert len(memory.turns()) == 1  # one summary, not two verbatim exchanges


def test_a_first_run_has_nothing_to_restore(recorder: VoiceRecorder) -> None:
    assert recorder.restore_summary() is None


def test_ambient_speech_never_reaches_the_restart_summary(
    recorder: VoiceRecorder,
) -> None:
    recorder.on_turn(Turn(heard="my wife is asking about dinner", intent="ambient"))
    assert recorder.restore_summary() is None


# -- never break the conversation ---------------------------------------------


def test_a_broken_log_does_not_break_the_turn(tmp_path: Path) -> None:
    log = EpisodicLog(tmp_path / "genesis.db")
    log.close()  # the database is gone underneath it
    recorder = VoiceRecorder(log)
    recorder.on_turn(Turn(heard="hello", intent="directed"))  # must not raise
    assert recorder.restore_summary() is None
