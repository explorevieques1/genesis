# Spec: Genesis Markdown/70-Schemas/Trade Journal Schema.md
"""The machine/human split, and the thresholds enforced by the type."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from genesis.journal.schema import (
    HARD_LIMIT_N,
    LESSON_N,
    Evidence,
    Hypothesis,
    JournalEntry,
    Lesson,
    Observation,
    PlanAdherence,
)
from tests.journal.conftest import entry


def test_an_entry_with_no_human_input_is_still_valid() -> None:
    """The design, not a fallback: journaling fails when it demands effort."""
    made = entry()
    assert made.has_human_input is False
    assert made.r_multiple is not None


def test_human_patch_cannot_reach_a_machine_field() -> None:
    made = entry()
    with pytest.raises(ValueError, match="cannot set machine fields"):
        made.human_patch(entry_price=999.0)
    with pytest.raises(ValueError, match="cannot set machine fields"):
        made.human_patch(r_multiple=99.0)


def test_human_patch_records_when_it_was_asked() -> None:
    """Marking on the ask is what makes 'once, and skippable' literal."""
    patched = entry().human_patch(notes="")
    assert patched.prompted_at is not None
    assert patched.has_human_input is False


def test_an_exit_before_the_entry_is_rejected() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="precedes entry"):
        JournalEntry(
            symbol="NVDA", direction="long", entry_price=100.0, entry_ts=now,
            exit_price=101.0, exit_ts=now - timedelta(hours=1), qty=10,
        )


def test_a_risk_engine_resize_is_not_a_discipline_failure() -> None:
    """The schema's own worked example: size_as_planned false, plan_followed true."""
    adherence = PlanAdherence(
        entry_in_zone=True, size_as_planned=False, stop_as_planned=True,
        exit_as_planned=True,
    )
    assert adherence.followed is True


def test_a_stop_moved_against_is_always_a_deviation() -> None:
    assert PlanAdherence(stop_moved=True).followed is False


def test_unchecked_fields_are_not_failures() -> None:
    """An entry with no planned stop cannot have deviated from one."""
    assert PlanAdherence().followed is True


def test_a_lesson_needs_twenty_observations() -> None:
    with pytest.raises(ValidationError, match=f"at least {LESSON_N}"):
        Lesson(title="t", finding="f", evidence=Evidence(observations=LESSON_N - 1))


def test_a_hard_limit_needs_thirty_and_a_human() -> None:
    """A wall the risk engine enforces is a different class of claim."""
    with pytest.raises(ValidationError, match=f"at least {HARD_LIMIT_N}"):
        Lesson(
            title="t", finding="f", enforcement="hard_limit",
            evidence=Evidence(observations=HARD_LIMIT_N - 1), approved_by_human=True,
        )
    with pytest.raises(ValidationError, match="human approval"):
        Lesson(
            title="t", finding="f", enforcement="hard_limit",
            evidence=Evidence(observations=HARD_LIMIT_N + 5),
        )


def test_evidence_carries_its_qualifier() -> None:
    assert "indicative" in Evidence(observations=6).qualifier()
    assert "indicative" not in Evidence(observations=40).qualifier()
    assert Evidence(observations=0).qualifier() == "no observations"


def test_a_hypothesis_becomes_ready_and_promotes_with_its_evidence() -> None:
    small = Hypothesis(key="k", title="t", finding="f", evidence=Evidence(observations=8))
    assert small.ready is False
    grown = small.model_copy(update={"evidence": Evidence(observations=LESSON_N + 1)})
    assert grown.ready is True
    lesson = grown.promote()
    assert lesson.evidence.observations == LESSON_N + 1
    assert lesson.key == "k"


def test_an_observation_kind_must_be_namespaced() -> None:
    with pytest.raises(ValidationError, match="namespaced"):
        Observation(kind="something", subject="x")
