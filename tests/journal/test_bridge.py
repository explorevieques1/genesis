# Spec: Genesis Markdown/20-Agents/Journal/Journal Family.md
"""The loop that is already running: charting outcomes into the journal."""

from __future__ import annotations

import numpy as np
import pytest

from genesis.charting.bars import Bars
from genesis.charting.compose import compose_default
from genesis.charting.levels import compute_levels
from genesis.charting.outcomes import evaluate
from genesis.charting.source import StaticBarSource
from genesis.charting.server import ChartingService
from genesis.charting.store import SpecStore
from genesis.charting.structure import read_structure
from genesis.journal.bridge import record_idea_outcome, record_spec_outcome
from genesis.journal.patterns import level_quality


@pytest.fixture
def bars(make_frame):
    return make_frame(np.linspace(100, 160, 240) + 3.0 * np.sin(np.arange(240) / 9.0))


def test_a_scored_spec_becomes_one_observation_per_level(store, bars) -> None:
    spec = compose_default(bars, compute_levels(bars), read_structure(bars))
    outcome = evaluate(spec, bars)
    written = record_spec_outcome(store, outcome)
    assert written == len(spec.levels())
    assert store.counts()["observation"] == written


def test_the_derivation_is_the_source_not_the_symbol(store, bars) -> None:
    """The question is not "do my levels hold" but "which kind of level holds"."""
    spec = compose_default(bars, compute_levels(bars), read_structure(bars))
    record_spec_outcome(store, evaluate(spec, bars))
    sources = {o.source for o in store.observations(kind="level.outcome")}
    assert sources
    assert all(s not in ("NVDA", "TEST") for s in sources)


def test_untested_levels_are_recorded_too(store, bars) -> None:
    """Excluding them would quietly inflate every hold rate."""
    spec = compose_default(bars, compute_levels(bars), read_structure(bars))
    record_spec_outcome(store, evaluate(spec, bars))
    outcomes = {o.outcome for o in store.observations(kind="level.outcome")}
    assert "untested" in outcomes


def test_diff_spec_records_outcomes_through_the_service(store, bars, tmp_path) -> None:
    """The wiring, end to end: scoring a chart teaches the journal something."""
    specs = SpecStore(tmp_path / "charting.db")
    service = ChartingService(
        StaticBarSource({(bars.symbol, bars.timeframe): bars}),
        specs, chart_dir=tmp_path, journal=store,
    )
    spec_id = service.chart(bars.symbol, bars.timeframe)["spec"]
    assert store.counts()["observation"] == 0
    service.diff_spec(spec_id)
    assert store.counts()["observation"] > 0
    specs.close()


def test_the_level_quality_finding_falls_out_of_the_loop(store) -> None:
    """Charting Family's stated distinctive edge, computed from recorded rows."""
    from genesis.journal.schema import Observation

    for i in range(12):
        store.record(
            Observation(
                kind="level.outcome", subject=f"level:X:{i}",
                outcome="held" if i < 9 else "broke", source="anchored-vwap",
            )
        )
    for i in range(12):
        store.record(
            Observation(
                kind="level.outcome", subject=f"level:Y:{i}",
                outcome="held" if i < 4 else "broke", source="trendline",
            )
        )
    found = level_quality([], observations=store.observations(kind="level.outcome"))
    assert found is not None
    assert "anchored-vwap" in found.finding and "trendline" in found.finding


def test_a_skipped_idea_leaves_a_record(store) -> None:
    record_idea_outcome(store, "idea_1", taken=False, realised_r=0.9, confidence=0.75)
    record_idea_outcome(store, "idea_2", taken=True, realised_r=0.1, confidence=0.72)
    outcomes = {o.outcome for o in store.observations(kind="idea")}
    assert outcomes == {"skipped", "taken"}


def test_a_level_fire_is_recorded_as_it_happens(store, bars, tmp_path) -> None:
    from genesis.agents.charting.level_watcher import LevelWatcherAgent

    specs = SpecStore(tmp_path / "charting.db")
    spec = compose_default(bars, compute_levels(bars), read_structure(bars))
    specs.put(spec)

    watcher = LevelWatcherAgent(
        StaticBarSource({(bars.symbol, bars.timeframe): bars}),
        specs, journal=store, clock=lambda: bars.last_time,
    )
    watcher.start()
    fires = watcher.poll()
    if fires:
        assert store.counts()["observation"] == len(fires)
        kinds = {o.kind for o in store.observations(kind="level")}
        assert all(k.startswith("level.") for k in kinds)
    specs.close()


# -- marks: the one thing in the journal a person authors ---------------------


def test_a_marked_range_becomes_an_observation(store) -> None:
    from genesis.journal.bridge import marks, record_mark

    obs = record_mark(
        store, kind="idea", symbol="nvda", timeframe="1h",
        start=1_700_000_000, end=1_700_086_400, note="base building on the 4h",
        drawing_id="drw_1",
    )
    assert obs.kind == "mark.idea" and obs.subject == "NVDA" and obs.outcome == "idea"
    assert obs.detail["start"] < obs.detail["end"] and obs.detail["note"]
    assert obs.source == "operator"
    assert [o.id for o in marks(store, symbol="NVDA")] == [obs.id]


def test_a_mark_on_a_trade_reaches_only_the_human_half(store) -> None:
    """The frozen machine record is what the Performance Analyst trusts."""
    from tests.journal.conftest import entry as make_entry

    from genesis.journal.bridge import record_mark

    entry = store.put_entry(make_entry())

    obs = record_mark(
        store, kind="exit", symbol=entry.symbol, timeframe="1d",
        start=1_700_000_000, end=1_700_086_400, note="took it off early",
        entry_id=entry.id,
    )
    after = store.entry(entry.id)
    assert f"mark:{obs.id}" in after.tags
    assert "took it off early" in after.notes
    assert after.entry_price == entry.entry_price and after.r_multiple == entry.r_multiple


def test_a_mark_refuses_nonsense(store) -> None:
    from genesis.journal.bridge import record_mark

    for bad in (
        {"kind": "musing", "symbol": "NVDA"},                     # not a mark kind
        {"kind": "entry", "symbol": ""},                          # no instrument
        {"kind": "entry", "symbol": "NVDA", "end": 1_600_000_000},  # ends before it starts
    ):
        with pytest.raises(ValueError):
            record_mark(store, timeframe="1h", start=1_700_000_000,
                        end=bad.pop("end", 1_700_086_400), **bad)
