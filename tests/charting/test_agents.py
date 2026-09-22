# Spec: Genesis Markdown/20-Agents/Charting/Charting Family.md
"""The five agents, against static bars and stub models."""

from __future__ import annotations

import json

import pytest

from genesis.agents.base import TaskFailure, TaskResult
from genesis.agents.charting import (
    ChartMarkupAgent,
    DataVizAgent,
    LevelWatcherAgent,
    MultiTimeframeAgent,
    PatternRecognitionAgent,
)
from genesis.agents.charting.fleet import CAPABILITIES, build_fleet, register
from genesis.bus.task import Lane, Task
from genesis.charting.source import StaticBarSource
from genesis.charting.store import SpecStore
from genesis.llm.backend import Completion
from genesis.orchestrator.registry import CapabilityRegistry


class StubBackend:
    """A model that says what the test needs it to say, once."""

    model = "stub"

    def __init__(self, text: str = "{}", *, raises: Exception | None = None) -> None:
        self.text = text
        self.raises = raises
        self.calls = 0

    def complete(self, prompt, *, system=None, max_tokens=None, **kwargs):
        self.calls += 1
        if self.raises:
            raise self.raises
        return Completion(text=self.text, model=self.model, latency_ms=1.0)

    def see(self, prompt, images, *, system=None, max_tokens=None, **kwargs):
        self.calls += 1
        if self.raises:
            raise self.raises
        return Completion(text=self.text, model=self.model, latency_ms=1.0)


@pytest.fixture
def frames(trending, ranging, falling, intraday):
    return {
        ("TEST", "1D"): trending,
        ("TEST", "1W"): ranging,
        ("TEST", "1M"): falling,
        ("TEST", "5m"): intraday,
        ("XLU", "1D"): trending,
        ("XLK", "1D"): falling,
        ("XLF", "1D"): ranging,
    }


@pytest.fixture
def source(frames):
    return StaticBarSource(frames)


@pytest.fixture
def store(tmp_path):
    made = SpecStore(tmp_path / "charting.db")
    yield made
    made.close()


def _task(task_type: str, agent: str, **args) -> Task:
    return Task(id="t1", type=task_type, lane=Lane.USER, agent=agent, args=args)


# ----------------------------------------------------------------------
# Chart Markup
# ----------------------------------------------------------------------


def test_chart_markup_produces_a_spec_an_image_and_a_sentence(source, store, tmp_path):
    agent = ChartMarkupAgent(source, store, chart_dir=tmp_path)
    agent.start()
    result = agent.run_task(_task("chart.markup", "chart-markup", symbol="TEST"))
    assert isinstance(result, TaskResult)
    assert result.data["markup_spec_id"]
    assert result.data["image_path"]
    assert result.spoken_summary
    assert store.get(result.data["markup_spec_id"]) is not None


def test_chart_markup_needs_a_symbol(source, store, tmp_path):
    agent = ChartMarkupAgent(source, store, chart_dir=tmp_path)
    agent.start()
    result = agent.run_task(_task("chart.markup", "chart-markup"))
    assert isinstance(result, TaskFailure)
    assert result.failure_class == "fatal"


def test_chart_markup_never_exceeds_the_cap(source, store, tmp_path):
    agent = ChartMarkupAgent(source, store, chart_dir=tmp_path, max_annotations=5)
    agent.start()
    result = agent.run_task(_task("chart.markup", "chart-markup", symbol="TEST"))
    spec = store.get(result.data["markup_spec_id"])
    assert len(spec.annotations) <= 5


def test_chart_markup_re_marking_creates_a_child(source, store, tmp_path):
    agent = ChartMarkupAgent(source, store, chart_dir=tmp_path)
    agent.start()
    first = agent.run_task(_task("chart.markup", "chart-markup", symbol="TEST"))
    second = agent.run_task(_task("chart.markup", "chart-markup", symbol="TEST"))
    child = store.get(second.data["markup_spec_id"])
    assert child.parent == first.data["markup_spec_id"]


def test_chart_markup_works_with_no_model_at_all(source, store, tmp_path):
    """A charting agent that goes silent when a provider hiccups is worse than one
    that writes its own reasons."""
    agent = ChartMarkupAgent(source, store, backend=None, chart_dir=tmp_path)
    agent.start()
    result = agent.run_task(_task("chart.markup", "chart-markup", symbol="TEST"))
    assert isinstance(result, TaskResult)
    assert not result.degraded


def test_chart_markup_falls_back_when_the_model_returns_nonsense(source, store, tmp_path):
    agent = ChartMarkupAgent(
        source, store, backend=StubBackend("not json at all"), chart_dir=tmp_path
    )
    agent.start()
    result = agent.run_task(_task("chart.markup", "chart-markup", symbol="TEST"))
    assert isinstance(result, TaskResult)
    assert result.degraded is True
    assert result.data["levels"]


def test_chart_markup_uses_the_models_selection_and_wording(source, store, tmp_path):
    from genesis.charting.compose import candidates
    from genesis.charting.levels import compute_levels

    picked = candidates(compute_levels(source.fetch("TEST", "1D")))[0].id
    reply = json.dumps(
        {
            "keep": [picked],
            "why": {picked: "the line the whole quarter has failed against"},
            "summary": "TEST is decided at the prior-day high.",
        }
    )
    agent = ChartMarkupAgent(source, store, backend=StubBackend(reply), chart_dir=tmp_path)
    agent.start()
    result = agent.run_task(_task("chart.markup", "chart-markup", symbol="TEST"))
    assert result.spoken_summary == "TEST is decided at the prior-day high."
    whys = [level["why"] for level in result.data["levels"]]
    assert any("failed against" in why for why in whys)


def test_chart_markup_records_every_level_as_a_graph_entity(source, store, tmp_path):
    agent = ChartMarkupAgent(source, store, chart_dir=tmp_path)
    agent.start()
    result = agent.run_task(_task("chart.markup", "chart-markup", symbol="TEST"))
    entities = [w for w in result.wrote if w.get("layer") == "knowledge-graph"]
    assert len(entities) == len(result.data["levels"])


def test_chart_markup_rejects_a_spec_containing_an_invented_price(
    source, store, tmp_path, monkeypatch
):
    """The boundary the prompt only asks for, checked before anything is stored."""
    from genesis.agents.charting import chart_markup as module

    monkeypatch.setattr(module, "unsourced_prices", lambda spec, sourced: [123.45])
    agent = ChartMarkupAgent(source, store, chart_dir=tmp_path)
    agent.start()
    result = agent.run_task(_task("chart.markup", "chart-markup", symbol="TEST"))
    assert isinstance(result, TaskFailure)
    assert "no tool produced" in result.reason
    assert len(store) == 0


# ----------------------------------------------------------------------
# Pattern Recognition
# ----------------------------------------------------------------------


def test_pattern_recognition_runs_rules_only_without_a_backend(source, store, tmp_path):
    markup = ChartMarkupAgent(source, store, chart_dir=tmp_path)
    markup.start()
    spec_id = markup.run_task(
        _task("chart.markup", "chart-markup", symbol="TEST")
    ).data["markup_spec_id"]

    agent = PatternRecognitionAgent(source, store)
    agent.start()
    result = agent.run_task(_task("chart.pattern", "pattern-recognition", spec_id=spec_id))
    assert isinstance(result, TaskResult)
    assert all(p["agreement"] == "rules" for p in result.data["patterns"])


def test_a_vision_only_pattern_is_capped(source, store, tmp_path):
    """A vision model will produce 0.85 for a wedge in noise. The cap is code."""
    from genesis.agents.charting.pattern_recognition import VISION_ONLY_CAP

    markup = ChartMarkupAgent(source, store, chart_dir=tmp_path)
    markup.start()
    spec_id = markup.run_task(
        _task("chart.markup", "chart-markup", symbol="TEST")
    ).data["markup_spec_id"]

    reply = json.dumps(
        {
            "patterns": [
                {"name": "cup_and_handle", "confidence": 0.95, "why": "I can see it"}
            ],
            "phase": "markup",
            "conflicts": [],
        }
    )
    agent = PatternRecognitionAgent(source, store, backend=StubBackend(reply))
    agent.start()
    result = agent.run_task(_task("chart.pattern", "pattern-recognition", spec_id=spec_id))
    seen = next(p for p in result.data["patterns"] if p["name"] == "cup_and_handle")
    assert seen["agreement"] == "vision"
    assert seen["confidence"] <= VISION_ONLY_CAP


def test_a_conflict_is_reported_not_resolved(source, store, tmp_path):
    """Rules measure a range; vision reports a flag. Neither wins silently."""
    markup = ChartMarkupAgent(source, store, chart_dir=tmp_path)
    markup.start()
    spec_id = markup.run_task(
        _task("chart.markup", "chart-markup", symbol="TEST", timeframe="1W")
    ).data["markup_spec_id"]

    reply = json.dumps(
        {"patterns": [{"name": "bull_flag", "confidence": 0.9, "why": "looks like one"}],
         "phase": "continuation", "conflicts": []}
    )
    agent = PatternRecognitionAgent(source, store, backend=StubBackend(reply))
    agent.start()
    result = agent.run_task(_task("chart.pattern", "pattern-recognition", spec_id=spec_id))
    if any(p["name"] == "range" for p in result.data["patterns"]):
        flag = next(p for p in result.data["patterns"] if p["name"] == "bull_flag")
        assert flag["agreement"] == "conflict"
        assert result.data["conflicts"]


def test_pattern_recognition_caches_against_the_spec(source, store, tmp_path):
    """Render once, ask once — the note's stated cost control."""
    markup = ChartMarkupAgent(source, store, chart_dir=tmp_path)
    markup.start()
    spec_id = markup.run_task(
        _task("chart.markup", "chart-markup", symbol="TEST")
    ).data["markup_spec_id"]

    backend = StubBackend(json.dumps({"patterns": [], "phase": "unclear"}))
    agent = PatternRecognitionAgent(source, store, backend=backend)
    agent.start()
    agent.run_task(_task("chart.pattern", "pattern-recognition", spec_id=spec_id))
    assert backend.calls == 1
    second = agent.run_task(_task("chart.pattern", "pattern-recognition", spec_id=spec_id))
    assert backend.calls == 1
    assert second.data["cached"] is True
    assert second.cost["tool_calls"] == 0


def test_a_vision_failure_degrades_to_rules_rather_than_failing(source, store, tmp_path):
    from genesis.errors import DegradedError

    markup = ChartMarkupAgent(source, store, chart_dir=tmp_path)
    markup.start()
    spec_id = markup.run_task(
        _task("chart.markup", "chart-markup", symbol="TEST")
    ).data["markup_spec_id"]

    agent = PatternRecognitionAgent(
        source, store, backend=StubBackend(raises=DegradedError("vision is down"))
    )
    agent.start()
    result = agent.run_task(_task("chart.pattern", "pattern-recognition", spec_id=spec_id))
    assert isinstance(result, TaskResult)
    assert result.degraded is True


# ----------------------------------------------------------------------
# Multi Timeframe
# ----------------------------------------------------------------------


def test_multi_timeframe_scores_and_renders(source, store, tmp_path):
    agent = MultiTimeframeAgent(
        source, store, chart_dir=tmp_path, ladder=("1M", "1W", "1D")
    )
    agent.start()
    result = agent.run_task(
        _task("chart.align", "multi-timeframe", symbol="TEST", direction="long")
    )
    assert isinstance(result, TaskResult)
    assert 0.0 <= result.data["alignment_score"] <= 1.0
    assert result.data["verdict"] in ("aligned", "mixed", "conflicted")
    assert result.data["image"]
    assert len(result.data["ladder"]) == 3


def test_a_conflicted_verdict_is_scored_below_the_threshold(source, store, tmp_path):
    """Daily up against a monthly down must score under 0.4 and warn explicitly."""
    from genesis.agents.charting.multi_timeframe import (
        CONFLICTED_BELOW,
        Rung,
        _key_conflict,
        _score,
        _verdict,
    )

    rungs = [
        Rung("1M", "down", "LH-LL", "false", 5.0),
        Rung("1W", "down", "LH-LL", "false", 4.0),
        Rung("1D", "up", "HH-HL", "true", 3.0),
    ]
    score = _score(rungs)
    assert score < CONFLICTED_BELOW
    assert _verdict(score) == "conflicted"
    assert "1M" in _key_conflict(rungs, "long")


def test_the_heaviest_disagreement_is_the_one_named(source, store, tmp_path):
    from genesis.agents.charting.multi_timeframe import Rung, _key_conflict

    rungs = [
        Rung("1W", "down", "LH-LL", "false", 4.0),
        Rung("15m", "down", "LH-LL", "false", 1.0),
    ]
    assert "1W" in _key_conflict(rungs, "long")


def test_a_ranging_timeframe_is_neutral_not_opposition(source, store, tmp_path):
    from genesis.agents.charting.multi_timeframe import Rung, _score

    all_ranging = [Rung("1D", "range", "range", "neutral", 3.0)]
    assert _score(all_ranging) == 0.5


def test_the_model_cannot_argue_the_verdict_up(source, store, tmp_path):
    """The sentence is written after the score is fixed, and cannot change it."""
    backend = StubBackend("Actually this is perfectly aligned, buy it.")
    agent = MultiTimeframeAgent(
        source, store, backend=backend, chart_dir=tmp_path, ladder=("1M", "1W", "1D")
    )
    agent.start()
    first = agent.align("TEST", direction="long", ladder=("1M", "1W", "1D"))
    plain = MultiTimeframeAgent(
        source, store, chart_dir=tmp_path, ladder=("1M", "1W", "1D")
    )
    plain.start()
    second = plain.align("TEST", direction="long", ladder=("1M", "1W", "1D"))
    assert first.verdict == second.verdict
    assert first.alignment_score == second.alignment_score


# ----------------------------------------------------------------------
# Level Watcher
# ----------------------------------------------------------------------


def test_the_level_watcher_has_no_model(source, store):
    assert LevelWatcherAgent(source, store).declaration.model_tier == "none"


def test_the_watcher_builds_its_list_from_the_store(source, store, tmp_path, trending):
    markup = ChartMarkupAgent(source, store, chart_dir=tmp_path)
    markup.start()
    markup.run_task(_task("chart.markup", "chart-markup", symbol="TEST"))

    # The clock is pinned to the fixture's own last bar. Left at wall-clock
    # time the spec is correctly *expired* — the fixtures are dated 2025 — and
    # the test would be asserting the calendar rather than the watch list.
    agent = LevelWatcherAgent(source, store, clock=lambda: trending.last_time)
    agent.start()
    assert agent.watches()


def test_the_watcher_runs_with_no_llm_backend_anywhere(source, store, tmp_path, trending):
    markup = ChartMarkupAgent(source, store, chart_dir=tmp_path)
    markup.start()
    markup.run_task(_task("chart.markup", "chart-markup", symbol="TEST"))

    agent = LevelWatcherAgent(source, store, clock=lambda: trending.last_time)
    agent.start()
    result = agent.run_task(_task("level.poll", "level-watcher"))
    assert isinstance(result, TaskResult)


def test_a_quiet_pass_says_nothing(source, store):
    """Sixty spoken summaries an hour saying nothing happened is worse than silence."""
    agent = LevelWatcherAgent(source, store)
    agent.start()
    result = agent.run_task(_task("level.poll", "level-watcher"))
    assert result.spoken_summary is None


def test_the_cooldown_suppresses_a_repeat_fire(source, store, tmp_path, trending):
    markup = ChartMarkupAgent(source, store, chart_dir=tmp_path)
    markup.start()
    markup.run_task(_task("chart.markup", "chart-markup", symbol="TEST"))

    agent = LevelWatcherAgent(source, store, clock=lambda: trending.last_time)
    agent.start()
    first = agent.poll()
    second = agent.poll()
    assert len(second) < len(first) or not second


def test_an_invalidation_is_never_rate_limited(source, store):
    agent = LevelWatcherAgent(source, store, voice_cap_per_hour=0)
    agent.start()
    from datetime import UTC, datetime

    assert agent._may_speak("invalidation", "critical", datetime.now(UTC)) is True
    assert agent._may_speak("touch", "high", datetime.now(UTC)) is False


def test_an_approach_never_speaks(source, store):
    from datetime import UTC, datetime

    agent = LevelWatcherAgent(source, store)
    agent.start()
    assert agent._may_speak("approach", "low", datetime.now(UTC)) is False


def test_a_trade_plan_contributes_its_stop_as_an_invalidation(store, trending):
    from genesis.agents.charting.level_watcher import _flatten
    from genesis.charting.spec import BarsRef, MarkupSpec, TradePlan

    spec = MarkupSpec.build(
        symbol="TEST", timeframe="1D", as_of=trending.last_time,
        bars_ref=BarsRef(source="test", **{"from": "2025-01-01", "to": "2026-01-01"}),
        annotations=[
            TradePlan(label="plan", why="reclaim", side="long", entry=150.0, stop=145.0)
        ],
    )
    watches = list(_flatten(spec))
    assert len(watches) == 1
    assert watches[0].invalidation is True
    assert watches[0].level_type == "stop_long"


# ----------------------------------------------------------------------
# Data Viz
# ----------------------------------------------------------------------


def test_data_viz_ranks_sectors(source, store, tmp_path, frames):
    agent = DataVizAgent(source, chart_dir=tmp_path)
    agent.start()
    result = agent.run_task(
        _task("viz.render", "data-viz", recipe="sector_performance", days=365)
    )
    assert isinstance(result, TaskResult)
    assert result.data["image_path"]
    assert result.data["rows"]
    assert result.data["finding"]
    # Only three sector ETFs are in the fixture, so this is the degraded path,
    # and it must say so rather than presenting a partial ranking as complete.
    assert result.degraded is True
    assert "Partial data" in result.spoken_summary


def test_an_unknown_recipe_names_the_ones_that_exist(source, tmp_path):
    agent = DataVizAgent(source, chart_dir=tmp_path)
    agent.start()
    result = agent.run_task(_task("viz.render", "data-viz", recipe="astrology"))
    assert isinstance(result, TaskFailure)
    assert "sector_performance" in result.reason


def test_compare_indexes_to_one_hundred(source, tmp_path):
    agent = DataVizAgent(source, chart_dir=tmp_path)
    agent.start()
    result = agent.run_task(
        _task("viz.render", "data-viz", recipe="compare",
              symbols=["XLU", "XLK"], days=365)
    )
    assert result.data["form"] == "line"
    assert "indexed to 100" in result.data["title"]


def test_correlation_names_the_extreme_pair(source, tmp_path):
    agent = DataVizAgent(source, chart_dir=tmp_path)
    agent.start()
    result = agent.run_task(
        _task("viz.render", "data-viz", recipe="correlation",
              symbols=["XLU", "XLK", "XLF"], days=180)
    )
    assert result.data["form"] == "heatmap"
    assert "correlated" in result.data["finding"]


def test_a_theory_is_always_labelled_as_a_hypothesis(source, tmp_path):
    """Finding is arithmetic; theory is a guess. Running them together gives
    them the same standing, and the prefix is code, not a prompt instruction."""
    agent = DataVizAgent(
        source, backend=StubBackend("Rates fell and duration re-rated."),
        chart_dir=tmp_path,
    )
    agent.start()
    result = agent.run_task(
        _task("viz.render", "data-viz", recipe="sector_performance",
              days=365, interpret=True)
    )
    assert result.data["theory_is_hypothesis"] is True
    assert "not something I verified" in result.spoken_summary


def test_no_theory_is_produced_without_a_backend(source, tmp_path):
    agent = DataVizAgent(source, chart_dir=tmp_path)
    agent.start()
    result = agent.run_task(
        _task("viz.render", "data-viz", recipe="sector_performance",
              days=365, interpret=True)
    )
    assert result.data["theory"] == ""
    assert result.data["theory_is_hypothesis"] is False


def test_an_unknown_macro_series_raises_rather_than_guessing(source, tmp_path):
    """A guessed FRED id returns a real, well-labelled chart of the wrong series."""

    class Macro:
        def series(self, series_id, *, start=None):
            raise AssertionError("should never be reached")

    agent = DataVizAgent(source, macro=Macro(), chart_dir=tmp_path)
    agent.start()
    result = agent.run_task(
        _task("viz.render", "data-viz", recipe="macro_series", series="banana harvest")
    )
    assert isinstance(result, TaskFailure)
    assert "which series" in result.reason


def test_a_macro_series_renders(source, tmp_path):
    class Macro:
        def series(self, series_id, *, start=None):
            return [(f"20{y:02d}-01-01", float(y % 6)) for y in range(6, 26)]

    agent = DataVizAgent(source, macro=Macro(), chart_dir=tmp_path)
    agent.start()
    result = agent.run_task(
        _task("viz.render", "data-viz", recipe="macro_series",
              series="fed funds", years=20)
    )
    assert result.data["form"] == "line"
    assert "federal funds" in result.data["title"]


def test_fred_missing_observations_are_dropped_not_zeroed():
    """FRED writes an unavailable print as "." — a zero would draw a rate crash."""
    from genesis.agents.charting.data_viz import _parse_observations

    payload = {
        "observations": [
            {"date": "2026-01-01", "value": "4.33"},
            {"date": "2026-01-02", "value": "."},
            {"date": "2026-01-03", "value": "4.35"},
        ]
    }
    assert _parse_observations(payload) == [("2026-01-01", 4.33), ("2026-01-03", 4.35)]


# ----------------------------------------------------------------------
# Fleet wiring
# ----------------------------------------------------------------------


def test_the_planner_catalogue_names_every_agent():
    registry = register(CapabilityRegistry())
    assert len(registry) == len(CAPABILITIES)
    assert "chart-markup" in registry
    catalogue = registry.catalogue()
    assert "chart.markup" in catalogue
    assert "viz.render" in catalogue


def test_the_catalogue_carries_no_tool_schemas():
    """Orchestrator.md: the orchestrator picks the agent, not the tool."""
    catalogue = register(CapabilityRegistry()).catalogue()
    assert "input_schema" not in catalogue
    assert "market-data" not in catalogue


def test_build_fleet_gives_each_agent_its_own_identity(source, tmp_path):
    class FakeGateway:
        def call(self, agent, capability, arguments=None, **kwargs):
            raise AssertionError("not reached")

    fleet = build_fleet(
        gateway=FakeGateway(),
        db_path=str(tmp_path / "c.db"),
        chart_dir=str(tmp_path),
    )
    identities = {a.source.agent for a in fleet.all()}
    assert identities == {
        "chart-markup", "pattern-recognition", "multi-timeframe",
        "level-watcher", "data-viz",
    }


def test_build_fleet_needs_a_source_or_a_gateway(tmp_path):
    with pytest.raises(ValueError, match="gateway or a bar source"):
        build_fleet(db_path=str(tmp_path / "c.db"))


def test_an_expired_spec_drops_off_the_watch_list(source, store, tmp_path, trending):
    """Levels from a stale spec fire alerts forever; expiry is the noise control."""
    from datetime import timedelta

    markup = ChartMarkupAgent(source, store, chart_dir=tmp_path)
    markup.start()
    markup.run_task(_task("chart.markup", "chart-markup", symbol="TEST"))

    fresh = LevelWatcherAgent(source, store, clock=lambda: trending.last_time)
    fresh.start()
    assert fresh.watches()

    stale = LevelWatcherAgent(
        source, store, clock=lambda: trending.last_time + timedelta(days=400)
    )
    stale.start()
    assert stale.watches() == []
