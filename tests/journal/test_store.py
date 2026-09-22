# Spec: Genesis Markdown/70-Schemas/Trade Journal Schema.md
"""The four properties the store enforces rather than trusts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from genesis.journal.schema import Evidence, Hypothesis, Lesson, Observation
from genesis.journal.store import INSIGHT_MINER, JournalStore
from tests.journal.conftest import entry


def test_entries_round_trip_and_are_idempotent(store) -> None:
    made = store.put_entry(entry())
    store.put_entry(made)
    assert len(store) == 1
    assert store.entry(made.id).r_multiple == made.r_multiple


def test_machine_fields_cannot_be_updated(store) -> None:
    made = store.put_entry(entry())
    with pytest.raises(Exception, match="immutable"):
        store.conn.execute(
            "UPDATE journal_entry SET r_multiple = 99 WHERE id = ?", (made.id,)
        )


def test_entries_cannot_be_deleted(store) -> None:
    store.put_entry(entry())
    with pytest.raises(Exception, match="permanent"):
        store.conn.execute("DELETE FROM journal_entry")


def test_the_human_half_is_writable_and_merges_on_read(store) -> None:
    made = store.put_entry(entry())
    store.patch_human(made.id, emotion_entry="calm", notes="clean", tags=["orb"])
    back = store.entry(made.id)
    assert back.emotion_entry == "calm"
    assert back.notes == "clean"
    assert back.tags == ("orb",)
    # And the machine half is untouched by the merge.
    assert back.r_multiple == made.r_multiple
    assert back.entry_price == made.entry_price


def test_the_frozen_body_never_contains_the_reflection(store) -> None:
    """One immutable copy of what was observed; one mutable copy of what was thought."""
    made = store.put_entry(entry())
    store.patch_human(made.id, notes="I felt fine about it")
    body = store.conn.execute(
        "SELECT body FROM journal_entry WHERE id = ?", (made.id,)
    ).fetchone()["body"]
    assert "I felt fine about it" not in body


def test_entries_come_back_oldest_first(store) -> None:
    """Every sequence effect is unanswerable from a list in reverse."""
    for i in range(5):
        store.put_entry(entry(index=i))
    ordered = store.entries()
    assert ordered == sorted(ordered, key=lambda e: e.exit_ts)


def test_unprompted_empties_once_asked(store) -> None:
    made = store.put_entry(entry())
    assert [e.id for e in store.unprompted()] == [made.id]
    store.patch_human(made.id)
    assert store.unprompted() == []


def test_only_the_insight_miner_may_write_a_lesson(store) -> None:
    from genesis.errors import FatalError

    lesson = Lesson(title="t", finding="f", evidence=Evidence(observations=25))
    with pytest.raises(FatalError, match="single-writer"):
        store.put_lesson(lesson, written_by="performance-analyst")
    assert store.lessons() == []
    store.put_lesson(lesson, written_by=INSIGHT_MINER)
    assert len(store.lessons()) == 1


def test_a_forbidden_write_raises_rather_than_silently_doing_nothing(store) -> None:
    """`INSERT OR IGNORE` skips a CHECK violation instead of raising.

    So the constraint alone would have made a forbidden write look like it
    succeeded while writing nothing — the worst of both outcomes, and invisible.
    """
    from genesis.errors import FatalError

    lesson = Lesson(title="t", finding="f", evidence=Evidence(observations=25))
    with pytest.raises(FatalError):
        store.put_lesson(lesson, written_by="chart-markup")
    assert store.counts()["lesson"] == 0


def test_superseding_replaces_rather_than_accumulates(store) -> None:
    first = store.put_lesson(
        Lesson(key="k", title="t", finding="old", evidence=Evidence(observations=25))
    )
    store.put_lesson(
        Lesson(
            key="k", title="t", finding="new", evidence=Evidence(observations=30),
            supersedes=first.id,
        )
    )
    active = store.lessons()
    assert len(active) == 1
    assert active[0].finding == "new"
    # History is kept, not deleted.
    assert store.counts()["lesson"] == 2
    assert store.lesson(first.id).status == "active"  # the object is unchanged
    assert store.lesson_by_key("k").finding == "new"


def test_a_hypothesis_accumulates_on_its_key(store) -> None:
    """The compounding mechanism: seen again means bigger, not duplicated."""
    for n in (5, 9, 14):
        store.record_hypothesis(
            Hypothesis(key="k", title="t", finding="f", evidence=Evidence(observations=n))
        )
    assert store.counts()["hypothesis"] == 1
    assert store.hypothesis("k").evidence.observations == 14
    assert store.hypotheses(ready_only=True) == []


def test_a_ready_hypothesis_promotes_and_keeps_the_trail(store) -> None:
    store.record_hypothesis(
        Hypothesis(key="k", title="t", finding="f", evidence=Evidence(observations=25))
    )
    ready = store.hypotheses(ready_only=True)
    assert len(ready) == 1
    lesson = store.promote("k", ready[0].promote())
    assert store.hypothesis("k").promoted_to == lesson.id
    assert store.hypotheses() == []


def test_observations_are_append_only(store) -> None:
    made = store.record(Observation(kind="level.outcome", subject="x", outcome="held"))
    with pytest.raises(Exception, match="append-only"):
        store.conn.execute(
            "UPDATE observation SET outcome = 'broke' WHERE id = ?", (made.id,)
        )


def test_outcome_rate_splits_by_derivation(level_outcomes) -> None:
    """The finding the whole charting family is built to make possible."""
    rate = level_outcomes.outcome_rate("level.outcome", good=["held", "reclaimed"])
    assert rate["n"] == 40
    assert rate["by_source"]["anchored-vwap"]["rate"] == pytest.approx(0.7)
    assert rate["by_source"]["trendline"]["rate"] == pytest.approx(0.4)


def test_an_empty_sample_has_no_rate_rather_than_zero(store) -> None:
    """A rate of zero and no data are different facts."""
    assert store.outcome_rate("level.outcome", good=["held"])["rate"] is None


def test_observation_kind_matches_by_prefix(store) -> None:
    store.record(Observation(kind="level.touched", subject="x"))
    store.record(Observation(kind="level.outcome", subject="x"))
    store.record(Observation(kind="trade.closed", subject="y"))
    assert len(store.observations(kind="level")) == 2
