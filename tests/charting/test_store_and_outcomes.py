# Spec: Genesis Markdown/10-Architecture/Markup Spec.md
"""Storage, lineage, expiry — and scoring a spec against what price did next."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from genesis.charting.compose import compose_default
from genesis.charting.levels import compute_levels
from genesis.charting.outcomes import evaluate
from genesis.charting.store import SpecStore
from genesis.charting.structure import read_structure


@pytest.fixture
def store(tmp_path) -> SpecStore:
    made = SpecStore(tmp_path / "charting.db")
    yield made
    made.close()


def _spec(bars, **kwargs):
    return compose_default(bars, compute_levels(bars), read_structure(bars), **kwargs)


def test_a_spec_round_trips(store, trending) -> None:
    spec = _spec(trending)
    store.put(spec)
    loaded = store.get(spec.id)
    assert loaded is not None
    assert loaded.id == spec.id
    assert [a.label for a in loaded.annotations] == [a.label for a in spec.annotations]


def test_storing_twice_is_idempotent(store, trending) -> None:
    """Agent Contract: same task id, same result, no duplicated side effects."""
    spec = _spec(trending)
    store.put(spec)
    store.put(spec)
    assert len(store) == 1


def test_specs_cannot_be_updated_or_deleted(store, trending) -> None:
    """Enforced by the database, not by convention."""
    spec = store.put(_spec(trending))
    with pytest.raises(Exception, match="immutable"):
        store.conn.execute(
            "UPDATE markup_spec SET symbol = 'X' WHERE id = ?", (spec.id,)
        )
    with pytest.raises(Exception, match="immutable"):
        store.conn.execute("DELETE FROM markup_spec")


def test_latest_returns_the_child_not_the_parent(store, trending) -> None:
    parent = store.put(_spec(trending))
    child = store.put(parent.remark())
    assert store.latest(trending.symbol, trending.timeframe).id == child.id


def test_latest_follows_the_chain_not_the_clock(store, trending) -> None:
    """Re-marks within one millisecond must not make `latest` a coin flip.

    A re-mark keeps its parent's `as_of`, so the two tie on time and the tie
    falls to the ULID — whose ordering inside a millisecond is random. Selecting
    the leaf structurally is what makes a rapid re-mark extend the chain instead
    of branching it.
    """
    spec = store.put(_spec(trending))
    for _ in range(5):
        spec = store.put(spec.remark())
    assert store.latest(trending.symbol, trending.timeframe).id == spec.id
    assert len(store.lineage(spec.id)) == 6


def test_lineage_walks_the_parent_chain(store, trending) -> None:
    first = store.put(_spec(trending))
    second = store.put(first.remark())
    third = store.put(second.remark())
    assert [s.id for s in store.lineage(third.id)] == [third.id, second.id, first.id]


def test_active_excludes_superseded_specs(store, trending) -> None:
    """Watching a parent and its child fires two alerts for one price."""
    parent = store.put(_spec(trending))
    store.put(parent.remark())
    active = store.active(trending.last_time)
    assert len(active) == 1
    assert active[0].parent == parent.id


def test_expiry_is_by_the_timeframes_own_relevance_window(store, trending) -> None:
    """A 5-minute level is stale in a day; a daily one is not."""
    spec = store.put(_spec(trending))
    assert store.active(spec.as_of)
    assert not store.active(spec.as_of + timedelta(days=400))


def test_the_vision_cache_is_invalidated_by_a_changed_render(store, trending) -> None:
    spec = store.put(_spec(trending))
    store.cache_vision(spec.id, "sha256:aaa", {"patterns": []})
    assert store.vision(spec.id, "sha256:aaa") is not None
    assert store.vision(spec.id, "sha256:bbb") is None


# ----------------------------------------------------------------------
# Outcomes
# ----------------------------------------------------------------------


def test_a_spec_with_no_bars_after_it_scores_nothing(store, trending) -> None:
    spec = _spec(trending)
    outcome = evaluate(spec, trending)
    assert outcome.bars_since == 0
    assert outcome.hold_rate is None
    assert "nothing to score" in outcome.summary()


def test_untested_levels_are_excluded_from_the_hold_rate(trending) -> None:
    """Reporting them as failures would drag every aggregate down."""
    past = trending.tail(len(trending) - 40)
    # Build a spec as of an earlier point, then score against the full frame.
    spec = _spec(trending.tail(len(trending) - 40))
    outcome = evaluate(spec, trending)
    tested = [level for level in outcome.levels if level.outcome != "untested"]
    if tested:
        assert 0.0 <= outcome.hold_rate <= 1.0
    else:
        assert outcome.hold_rate is None


def test_a_level_price_never_reached_is_untested(make_frame) -> None:
    import numpy as np

    from genesis.charting.spec import BarsRef, Level, MarkupSpec

    frame = make_frame(np.linspace(100, 110, 120))
    spec = MarkupSpec.build(
        symbol="TEST", timeframe="1D", as_of=frame.times[60],
        bars_ref=BarsRef(source="test", **{"from": "2025-01-01", "to": "2025-06-01"}),
        annotations=[
            Level(price=500.0, label="FAR", type="resistance", why="never reached"),
        ],
    )
    outcome = evaluate(spec, frame)
    assert outcome.levels[0].outcome == "untested"
    assert outcome.hold_rate is None
