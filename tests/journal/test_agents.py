# Spec: Genesis Markdown/20-Agents/Journal/Journal Family.md
"""The six agents: honest when there is data, honest when there is not."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from genesis.agents.base import TaskFailure, TaskResult
from genesis.agents.journal import (
    DigestAgent,
    DriftAgent,
    InsightMinerAgent,
    PerformanceAnalystAgent,
    TradeJournalAgent,
    WatchdogAgent,
)
from genesis.agents.journal.fleet import CAPABILITIES, build_fleet, register
from genesis.agents.journal.trade_journal import build_entry
from genesis.bus.task import Lane, Task
from genesis.journal.drift import Expectation
from genesis.journal.health import Probe
from genesis.journal.schema import Evidence, Lesson, Observation
from genesis.llm.backend import Completion
from genesis.orchestrator.registry import CapabilityRegistry
from tests.journal.conftest import entry


class StubBackend:
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


def _task(task_type: str, agent: str, **args) -> Task:
    return Task(id="t1", type=task_type, lane=Lane.MAINTENANCE, agent=agent, args=args)


TRADE = {
    "symbol": "NVDA", "direction": "long",
    "entry_price": 121.06, "entry_ts": "2026-08-27T14:31:02Z",
    "exit_price": 124.20, "exit_ts": "2026-08-27T15:12:40Z",
    "qty": 120, "planned_stop": 118.40, "planned_target": 124.50,
    "exit_reason": "target", "final_stop": 118.40, "planned_qty": 192,
    "mfe_r": 1.34, "setup": "orb_breakout", "thesis": "long above the PDH reclaim",
}


# ----------------------------------------------------------------------
# Trade Journal
# ----------------------------------------------------------------------


def test_a_fill_becomes_an_entry_and_an_observation(store) -> None:
    agent = TradeJournalAgent(store)
    agent.start()
    result = agent.run_task(_task("journal.record", "trade-journal", trade=TRADE))
    assert isinstance(result, TaskResult)
    assert store.counts()["journal_entry"] == 1
    # The trade lands in the observation table too, so the miner's wide net sees
    # it without special-casing the journal.
    assert store.counts()["observation"] == 1


def test_the_r_multiple_is_computed_from_the_planned_stop() -> None:
    made = build_entry(TRADE)
    assert made.r_multiple == pytest.approx((124.20 - 121.06) / (121.06 - 118.40), abs=1e-3)


def test_no_planned_stop_means_no_r_not_zero() -> None:
    """A trade whose R cannot be computed is not a breakeven trade."""
    made = build_entry({**TRADE, "planned_stop": None})
    assert made.r_multiple is None


def test_a_short_is_scored_in_its_own_direction() -> None:
    short = build_entry(
        {**TRADE, "direction": "short", "planned_stop": 124.0, "exit_price": 118.0}
    )
    assert short.r_multiple > 0


def test_the_thesis_is_copied_verbatim() -> None:
    assert build_entry(TRADE).thesis == "long above the PDH reclaim"


def test_stop_migration_is_computed_and_directional() -> None:
    """Tightening in your favour is discipline; widening against you is the finding."""
    widened = build_entry({**TRADE, "final_stop": 117.0})
    assert widened.plan_adherence.stop_moved is True
    assert any("Stop moved" in d for d in widened.plan_adherence.deviations)

    tightened = build_entry({**TRADE, "final_stop": 119.5})
    assert tightened.plan_adherence.stop_moved is False


def test_a_deviation_is_volunteered_in_the_spoken_summary(store) -> None:
    agent = TradeJournalAgent(store)
    agent.start()
    result = agent.run_task(
        _task("journal.record", "trade-journal", trade={**TRADE, "final_stop": 117.0})
    )
    assert "Stop moved" in result.spoken_summary


def test_prompting_happens_once_and_is_skippable(store) -> None:
    agent = TradeJournalAgent(store)
    agent.start()
    agent.run_task(_task("journal.record", "trade-journal", trade=TRADE))

    first = agent.run_task(_task("journal.prompt", "trade-journal", prompt=True))
    assert first.data["count"] == 1
    second = agent.run_task(_task("journal.prompt", "trade-journal", prompt=True))
    assert second.data["count"] == 0
    assert second.spoken_summary is None


def test_journalling_without_a_trade_fails_honestly(store) -> None:
    agent = TradeJournalAgent(store)
    agent.start()
    result = agent.run_task(_task("journal.record", "trade-journal"))
    assert isinstance(result, TaskFailure)
    assert result.failure_class == "fatal"


# ----------------------------------------------------------------------
# Performance Analyst
# ----------------------------------------------------------------------


def test_an_empty_period_says_so(store) -> None:
    agent = PerformanceAnalystAgent(store)
    agent.start()
    result = agent.run_task(_task("perf.review", "performance-analyst", days=7))
    assert "No completed trades" in result.spoken_summary


def test_every_slice_carries_its_n(planted) -> None:
    agent = PerformanceAnalystAgent(planted)
    agent.start()
    result = agent.run_task(_task("perf.review", "performance-analyst", days=365))
    for found in result.data["slices"].values():
        for item in found:
            assert "n" in item and item["n"] > 0


def test_a_thin_period_refuses_to_headline_a_thin_slice(store) -> None:
    """A two-trade slice is usually both the best and the worst thing in the data."""
    for i in range(4):
        store.put_entry(entry(index=i, r=3.0 if i else -3.0, setup=f"s{i}"))
    agent = PerformanceAnalystAgent(store)
    agent.start()
    result = agent.run_task(_task("perf.review", "performance-analyst", days=365))
    assert result.data["best_slice"] is None
    assert any("not enough" in w or "indicative" in w for w in result.data["sample_warnings"])


def test_a_losing_period_leads_with_the_loss(store) -> None:
    for i in range(25):
        store.put_entry(entry(index=i, r=-0.5))
    agent = PerformanceAnalystAgent(store)
    agent.start()
    result = agent.run_task(_task("perf.review", "performance-analyst", days=365))
    assert result.spoken_summary.startswith("Down")


def test_no_recommendation_is_supported_on_a_thin_sample(store) -> None:
    for i in range(10):
        store.put_entry(entry(index=i, r=0.5))
    agent = PerformanceAnalystAgent(store)
    agent.start()
    result = agent.run_task(_task("perf.review", "performance-analyst", days=365))
    assert any("no behavioural recommendation" in w for w in result.data["sample_warnings"])


def test_the_model_is_never_given_the_trades(planted) -> None:
    """It cannot introduce a number it was not handed."""
    backend = StubBackend("A flat week.")
    agent = PerformanceAnalystAgent(planted, backend=backend)
    agent.start()
    prompt_seen: list[str] = []
    backend.complete = lambda p, **kw: (  # type: ignore[assignment]
        prompt_seen.append(p), Completion(text="A flat week.", model="stub", latency_ms=1.0)
    )[1]
    agent.run_task(_task("perf.review", "performance-analyst", days=365))
    assert prompt_seen
    assert "entry_price" not in prompt_seen[0]


# ----------------------------------------------------------------------
# Insight Miner
# ----------------------------------------------------------------------


def test_the_planted_pattern_is_found(planted) -> None:
    """The note's acceptance criterion, on a seeded dataset."""
    agent = InsightMinerAgent(planted)
    agent.start()
    result = agent.run_task(_task("insight.mine", "insight-miner", days=365))
    keys = {l["title"] for l in result.data["lessons"]}
    findings = " ".join(l["finding"] for l in result.data["lessons"])
    assert "Performance after consecutive losses" in keys
    assert "consecutive losses" in findings


def test_no_lesson_below_twenty_observations(store) -> None:
    for i in range(8):
        store.put_entry(entry(index=i, r=-1.0, stop_moved=True))
    agent = InsightMinerAgent(store)
    agent.start()
    result = agent.run_task(_task("insight.mine", "insight-miner", days=365))
    assert result.data["lessons"] == []


def test_an_under_evidenced_finding_becomes_a_hypothesis(store) -> None:
    """The compounding mechanism: recorded so it can become enough."""
    for i in range(8):
        store.put_entry(entry(index=i, r=-1.0 if i % 2 else 1.0, stop_moved=i % 2 == 0))
    agent = InsightMinerAgent(store)
    agent.start()
    result = agent.run_task(_task("insight.mine", "insight-miner", days=365))
    assert result.data["hypotheses"]
    assert store.counts()["hypothesis"] >= 1


def test_a_repeated_finding_supersedes_rather_than_accumulates(planted) -> None:
    agent = InsightMinerAgent(planted)
    agent.start()
    first = agent.run_task(_task("insight.mine", "insight-miner", days=365))
    active_after_one = len(planted.lessons())
    second = agent.run_task(_task("insight.mine", "insight-miner", days=365))
    assert second.data["superseded"]
    assert len(planted.lessons()) == active_after_one


def test_level_quality_is_found_from_observations_alone(level_outcomes) -> None:
    """The one finding available before a single trade exists."""
    agent = InsightMinerAgent(level_outcomes)
    agent.start()
    result = agent.run_task(_task("insight.mine", "insight-miner", days=365))
    findings = " ".join(l["finding"] for l in result.data["lessons"])
    assert "anchored-vwap" in findings and "trendline" in findings


def test_a_quiet_pass_reports_the_closest_hypothesis(store) -> None:
    for i in range(8):
        store.put_entry(entry(index=i, r=-1.0 if i % 2 else 1.0, stop_moved=i % 2 == 0))
    agent = InsightMinerAgent(store)
    agent.start()
    result = agent.run_task(_task("insight.mine", "insight-miner", days=365))
    assert "Nothing conclusive yet" in (result.spoken_summary or "")


def test_the_model_cannot_enlarge_a_finding(planted) -> None:
    """Wording is the model's; evidence and enforcement are not."""
    backend = StubBackend(
        json.dumps(
            {
                "title": "Enormous discovery",
                "finding": "This is certain.",
                "recommended_action": "Stop trading.",
                "enforcement": "hard_limit",
            }
        )
    )
    agent = InsightMinerAgent(planted, backend=backend)
    agent.start()
    agent.run_task(_task("insight.mine", "insight-miner", days=365))
    for lesson in planted.lessons():
        assert lesson.enforcement in ("advisory", "warn")
        assert lesson.approved_by_human is False


def test_a_hard_limit_is_proposed_never_applied(store) -> None:
    """The system proposes; you decide. Nothing here can perform the approval."""
    lesson = store.put_lesson(
        Lesson(
            key="k", title="Oversizing", finding="You oversize after two losses",
            evidence=Evidence(observations=34),
        )
    )
    agent = InsightMinerAgent(store)
    agent.start()
    proposal = agent.propose_hard_limit(lesson.id)
    assert proposal["ok"] is True
    assert proposal["requires_human_approval"] is True
    # Proposing did not change the lesson.
    assert store.lesson(lesson.id).enforcement == "advisory"
    assert store.lesson(lesson.id).approved_by_human is False


def test_a_hard_limit_needs_thirty_observations(store) -> None:
    lesson = store.put_lesson(
        Lesson(key="k", title="t", finding="f", evidence=Evidence(observations=22))
    )
    agent = InsightMinerAgent(store)
    agent.start()
    assert agent.propose_hard_limit(lesson.id)["ok"] is False


# ----------------------------------------------------------------------
# Watchdog
# ----------------------------------------------------------------------


def test_alive_but_stale_is_degraded_never_healthy(store) -> None:
    """The most dangerous failure mode there is."""
    stale = Probe(name="feed", kind="data", alive=True, data_age_sec=900, max_age_sec=60)
    assert stale.state == "degraded"


def test_an_unknown_age_is_not_a_young_age() -> None:
    assert Probe(name="feed", kind="data", alive=True, max_age_sec=60).fresh is False


def test_an_issue_is_reported_once_and_recovery_once(store) -> None:
    state = {"alive": True}
    agent = WatchdogAgent(
        store=store,
        extra_probes=[lambda: Probe(name="news", kind="mcp", alive=state["alive"])],
    )
    agent.start()
    assert agent.run_task(_task("health.check", "watchdog")).data["new_issues"] == []
    state["alive"] = False
    assert agent.run_task(_task("health.check", "watchdog")).data["new_issues"] == ["news down"]
    assert agent.run_task(_task("health.check", "watchdog")).data["new_issues"] == []
    state["alive"] = True
    assert agent.run_task(_task("health.check", "watchdog")).data["recovered"] == ["news"]


def test_a_failed_execution_component_forces_confirm(store) -> None:
    agent = WatchdogAgent(
        store=store,
        extra_probes=[
            lambda: Probe(
                name="broker", kind="broker", alive=False, restarts=9,
                execution_path=True, detail="session lost",
            )
        ],
    )
    agent.start()
    result = agent.run_task(_task("health.check", "watchdog"))
    assert result.data["approval_mode_forced"] == "confirm"
    assert "confirm" in result.spoken_summary


def test_incidents_are_recorded_for_later(store) -> None:
    agent = WatchdogAgent(
        store=store,
        extra_probes=[lambda: Probe(name="news", kind="mcp", alive=False)],
    )
    agent.start()
    agent.run_task(_task("health.check", "watchdog"))
    assert store.counts()["observation"] == 1


def test_a_healthy_cycle_says_nothing(store) -> None:
    agent = WatchdogAgent(
        store=store, extra_probes=[lambda: Probe(name="ok", kind="mcp", alive=True)]
    )
    agent.start()
    assert agent.run_task(_task("health.check", "watchdog")).spoken_summary is None


def test_the_watchdog_probes_the_real_supervisor_and_bus(store, tmp_path) -> None:
    """Against the daemon's own types, not fakes -- fakes hid a missing method."""
    from genesis.bus.bus import TaskBus
    from genesis.daemon.supervisor import Supervisor

    supervisor = Supervisor()
    digest = DigestAgent(store)
    supervisor.supervise(digest)
    bus = TaskBus(tmp_path / "bus.db")
    agent = WatchdogAgent(store=store, supervisor=supervisor, bus=bus)
    agent.start()

    digest.start()
    data = agent.run_task(_task("health.check", "watchdog")).data
    assert data["agent"]["fleet"]["state"] == "healthy"
    assert data["bus"]["task-bus"]["state"] == "healthy"

    digest.mark_degraded("test")
    data = agent.run_task(_task("health.check", "watchdog")).data
    assert "digest" in data["agent"]["fleet"]["reason"]


def test_the_watchdog_has_no_model(store) -> None:
    assert WatchdogAgent(store=store).declaration.model_tier == "none"


# ----------------------------------------------------------------------
# Digest
# ----------------------------------------------------------------------


def test_the_brief_carries_at_most_one_warning(store) -> None:
    for i in range(3):
        store.put_lesson(
            Lesson(
                key=f"k{i}", title=f"t{i}", finding=f"finding {i}",
                evidence=Evidence(observations=34), enforcement="warn",
            )
        )
    agent = DigestAgent(store)
    agent.start()
    result = agent.run_task(_task("digest.brief", "digest", kind="morning"))
    assert result.data["text"].count("⚠️") <= 1


def test_a_quiet_morning_is_short(store) -> None:
    agent = DigestAgent(store)
    agent.start()
    result = agent.run_task(_task("digest.brief", "digest", kind="morning"))
    assert result.data["words"] < 60


def test_the_recap_reports_losses_with_the_wins(store) -> None:
    now = datetime.now(UTC)
    store.put_entry(entry(r=1.2, at=now - timedelta(hours=3)))
    store.put_entry(entry(r=-1.0, at=now - timedelta(hours=2), symbol="AMD"))
    agent = DigestAgent(store)
    agent.start()
    text = agent.run_task(_task("digest.brief", "digest", kind="evening")).data["text"]
    assert "-1.0R" in text and "+1.2R" in text


def test_a_long_narrative_is_rejected_rather_than_spoken(store) -> None:
    """The length rule is checked, not requested."""
    agent = DigestAgent(store, backend=StubBackend("word " * 400))
    agent.start()
    result = agent.run_task(_task("digest.brief", "digest", kind="morning"))
    assert result.data["words"] < 100


def test_compression_never_touches_a_referenced_id(store) -> None:
    """Compress process, preserve decisions — verified, per the note."""
    made = store.put_entry(entry(markup_entry="ms_123", trace_id="tr_9"))
    agent = DigestAgent(store)
    agent.start()
    protected = agent._protected()
    assert {made.id, "ms_123", "tr_9"} <= protected


def test_compression_reports_honestly_with_no_episodic_log(store) -> None:
    agent = DigestAgent(store)
    agent.start()
    result = agent.run_task(_task("digest.brief", "digest", kind="compress"))
    assert result.data["compressed"] == 0
    assert result.spoken_summary is None


def test_the_cron_time_picks_the_job(store) -> None:
    """The daemon's cron task carries only `at`; 16:30 must not be a morning brief."""
    agent = DigestAgent(store)
    agent.start()
    assert agent.run_task(_task("digest.run", "digest", at="16:30")).data["kind"] == "evening"
    assert agent.run_task(_task("digest.run", "digest", at="07:00")).data["kind"] == "morning"
    assert "compressed" in agent.run_task(_task("digest.run", "digest", at="21:00")).data


def test_compression_reads_a_real_episodic_log(store, tmp_path) -> None:
    from genesis.memory.episodic import EpisodicLog

    log = EpisodicLog(tmp_path / "episodic.db")
    for _ in range(3):
        log.append(actor="screener", kind="scan", trace_id="tr_1")
    log.append(actor="execution", kind="fill", trace_id="tr_2")
    agent = DigestAgent(store, episodic=log)
    agent.start()
    data = agent.run_task(_task("digest.brief", "digest", kind="compress")).data
    assert "error" not in data
    assert (data["examined"], data["preserved"], data["collapsible"]) == (4, 1, 3)


def test_the_morning_brief_quotes_overnight_research(store, tmp_path) -> None:
    from genesis.news.store import NewsStore
    from genesis.research.schema import ResearchNote
    from genesis.research.store import ResearchStore

    research = ResearchStore(path=tmp_path / "research.db", vault=None)
    research.put(ResearchNote(id="rn_1", kind="regime", title="Market regime", subject="2026-09-13",
                              created_by="market-analyst", data={"regime": "risk-on"}), mirror=False)
    research.put(ResearchNote(id="rn_2", kind="idea", title="NVDA long", subject="nvda",
                              created_by="idea-synthesizer", summary="NVDA long from 121"), mirror=False)
    news = NewsStore(tmp_path / "news.db")
    news.add_brief(title="b", hours=24, requested_by="test",
                   body={"stories": [{"headline": "CPI at 8:30"}]})

    agent = DigestAgent(store, research=research, news=news)
    agent.start()
    text = agent.run_task(_task("digest.brief", "digest", kind="morning")).data["text"]
    assert "risk-on" in text and "CPI at 8:30" in text and "NVDA long from 121" in text


# ----------------------------------------------------------------------
# Drift
# ----------------------------------------------------------------------


def _live(store, n: int, r: float, strategy: str = "nq_orb_v3") -> None:
    for i in range(n):
        store.put_entry(entry(index=i, r=r, strategy=strategy, slippage_bps=6.1))


def test_no_divergence_claim_below_thirty_trades(store) -> None:
    _live(store, 12, -1.0)
    agent = DriftAgent(
        store, expectations={"nq_orb_v3": Expectation(expectancy_r=0.31, sigma_r=1.0, trades=400)}
    )
    agent.start()
    report = agent.run_task(_task("drift.check", "drift", days=365)).data["reports"][0]
    assert report["divergence"]["significant"] is False
    assert "below the 30-trade minimum" in report["diagnosis"]["reasoning"]


def test_a_real_divergence_is_diagnosed_and_escalated(store) -> None:
    _live(store, 40, -0.8)
    agent = DriftAgent(
        store,
        expectations={
            "nq_orb_v3": Expectation(
                expectancy_r=0.31, sigma_r=1.0, trades=400, avg_win_r=1.79,
                avg_loss_r=-0.98, trades_per_week=4.1, assumed_slippage_bps=2.0,
                regime="trending",
            )
        },
    )
    agent.start()
    result = agent.run_task(_task("drift.check", "drift", days=365))
    report = result.data["reports"][0]
    assert report["divergence"]["significant"] is True
    assert report["diagnosis"]["likely_cause"] != "variance"


def test_a_suspected_bug_proposes_demotion_but_does_not_apply_it(store) -> None:
    """If the code might be wrong, autonomy goes — but the risk engine decides."""
    _live(store, 40, -0.8)
    agent = DriftAgent(
        store,
        expectations={
            "nq_orb_v3": Expectation(
                expectancy_r=0.31, sigma_r=1.0, trades=400, optimizer_trials=500
            )
        },
    )
    agent.start()
    result = agent.run_task(_task("drift.check", "drift", days=365))
    assert result.data["demotion_proposed"]
    assert result.data["demotion_proposed"][0]["to"] == "confirm"


def test_a_strategy_with_no_backtest_is_reported_not_invented(store) -> None:
    _live(store, 40, 0.2)
    agent = DriftAgent(store)
    agent.start()
    result = agent.run_task(_task("drift.check", "drift", days=365))
    assert result.data["reports"] == []
    assert result.data["unmeasurable"] == ["nq_orb_v3"]
    assert result.degraded is True


# ----------------------------------------------------------------------
# Fleet
# ----------------------------------------------------------------------


def test_the_catalogue_omits_the_agents_nobody_asks_for() -> None:
    """A catalogue is a menu; everything on it should be orderable."""
    registry = register(CapabilityRegistry())
    assert "trade-journal" not in registry
    assert "drift" not in registry
    assert "performance-analyst" in registry


def test_build_fleet_uses_the_store_it_was_given(tmp_path) -> None:
    from genesis.journal.store import JournalStore

    given = JournalStore(tmp_path / "given.db")
    fleet = build_fleet(store=given)
    assert fleet.store is given
    assert all(getattr(a, "store", given) is given for a in fleet.all() if hasattr(a, "store"))
    given.close()


def test_the_fleet_builds_with_nothing_wired(tmp_path) -> None:
    """No backend, no ledger, no gateway. Every agent still constructs."""
    fleet = build_fleet(db_path=str(tmp_path / "j.db"))
    assert len(fleet.all()) == 6
    fleet.store.close()
