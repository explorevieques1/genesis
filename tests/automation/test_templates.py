# Spec: Genesis Markdown/60-UI/Automation.md §Templates
"""Every template can actually run: real tools, built agents, known processes."""

from __future__ import annotations

import datetime as dt
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

from genesis.automation import actions as act
from genesis.automation.catalog import TOOL_NODES
from genesis.automation.grant import permits
from genesis.automation.runner import WorkflowAgent
from genesis.automation.store import WorkflowStore
from genesis.automation.templates import TEMPLATES, by_id
from genesis.bus import TaskBus
from genesis.daemon import MarketCalendar
from genesis.mcp.fence import wrap
from genesis.server.fleet import discover_agents

REPO = Path(__file__).resolve().parents[2]
EVENING = dt.datetime(2026, 9, 1, 22, 0, tzinfo=dt.UTC)  # Tue 18:00 ET
#: The weekend review runs Sunday 17:00 ET. Its first step is a weekday gate,
#: because `Cadence` has no weekday field and its cron therefore fires daily --
#: so a test that runs it on a Tuesday is testing the gate, not the review.
SUNDAY = dt.datetime(2026, 9, 6, 21, 0, tzinfo=dt.UTC)  # Sun 17:00 ET
AGENT_ACTIONS = {"agent.research": "topic-researcher", "agent.summarise": "topic-researcher",
                 "agent.regime": "market-analyst", "agent.ideas": "idea-synthesizer",
                 "agent.chart-markup": "chart-markup", "agent.multi-timeframe": "multi-timeframe",
                 "agent.data-viz": "data-viz", "agent.digest": "digest", "agent.performance": "performance-analyst",
                 "agent.insights": "insight-miner", "agent.drift": "drift"}


def enabled_capabilities() -> set[str]:
    servers = yaml.safe_load((REPO / "src/genesis/mcp/default_servers.yaml").read_text())
    servers = servers.get("servers", servers) if isinstance(servers, dict) else servers
    return {t["capability"] for s in servers if s.get("enabled")
            for t in (s.get("tools") or {}).values() if isinstance(t, dict) and t.get("capability")}


def test_the_templates_are_there_with_unique_ids() -> None:
    assert len(TEMPLATES) == 19
    assert len({t.id for t in TEMPLATES}) == 19
    assert sum(t.process for t in TEMPLATES) == 3


def test_every_template_tool_is_granted_curated_and_served_by_an_enabled_server() -> None:
    enabled, curated = enabled_capabilities(), {c for c, *_ in TOOL_NODES}
    for t in TEMPLATES:
        for s in t.workflow.steps:
            if s.kind == "gather":
                assert permits(s.capability), (t.id, s.capability)
                assert s.capability in enabled, f"{t.id}: no enabled server serves {s.capability}"
                assert s.capability in curated, f"{t.id}: {s.capability} is not a palette tool"


def test_every_agent_a_template_dispatches_is_built() -> None:
    built = {a["id"] for a in discover_agents() if a.get("built")}
    for t in TEMPLATES:
        for s in t.workflow.steps:
            if s.kind == "action" and s.action in AGENT_ACTIONS:
                assert AGENT_ACTIONS[s.action] in built, (t.id, s.action)


def test_processes_a_template_calls_are_templates_too() -> None:
    for t in TEMPLATES:
        for s in t.workflow.steps:
            if s.kind == "action" and s.action == "flow.process":
                assert by_id(s.params["workflow"]) is not None, (t.id, s.params)


def test_trigger_cadences_are_the_scheduler_s_own() -> None:
    kinds = {t.workflow.trigger.type for t in TEMPLATES}
    assert kinds <= {"cron", "market-open", "market-closed", "on-demand"}


# -- a few end to end, with tools faked at the gateway -----------------------


class Result:
    def __init__(self, content: Any, fence: Any = None) -> None:
        self.content, self.structured, self.fence = content, None, fence


class FakeGateway:
    def __init__(self, reply) -> None:  # noqa: ANN001
        self.reply, self.calls = reply, []

    def call(self, agent: str, capability: str, arguments: dict | None = None, **_: Any) -> Result:
        self.calls.append((capability, arguments))
        return self.reply(capability, arguments or {})


def fenced(body: str) -> Result:
    f = wrap(body, source="test")
    return Result(f.text, fence=f)


@pytest.fixture
def world(tmp_path: Path):
    bus = TaskBus(tmp_path / "genesis.db", claim_ttl_sec=5.0)
    store = WorkflowStore(tmp_path / "workflows.db")
    yield bus, store
    store.close()
    bus.close()


def run_template(world, template_id: str, gateway, now=EVENING):  # noqa: ANN001, ANN201
    bus, store = world
    wf = by_id(template_id).workflow
    store.save(wf, author="operator")
    agent = WorkflowAgent(wf, 1, store=store, bus=bus, gateway=gateway, calendar=MarketCalendar(), clock=lambda: now)
    agent.start()

    class Task:
        id, trace_id, args = "t1", "tr1", {}

    agent.run_task(Task())
    return store.runs(wf.id)[0], store


def test_headline_keyword_watch_parses_a_fenced_feed_and_alerts_on_matches(world) -> None:
    feed = '{"articles": [{"headline": "Analyst downgrade hits chipmakers"}, {"headline": "Quiet session"},' \
           ' {"headline": "SEC opens probe into lender"}]}'
    gateway = FakeGateway(lambda cap, args: fenced(feed))
    run, store = run_template(world, "headline-keyword-watch", gateway)
    assert run["status"] == "ok", run
    alert = store.alerts()[0]
    assert alert["title"] == "2 headlines to read"
    assert "downgrade" in alert["message"] and "Quiet" not in alert["message"]


def test_filing_sweep_calls_once_per_symbol_and_skips_a_symbol_that_errors(world, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(act, "_watchlist_symbols", lambda name, group="": ["NVDA", "ESZ6", "AMD"])

    def reply(cap: str, args: dict[str, Any]) -> Result:
        if args["identifier"] == "ESZ6":
            return Result('{"success": false, "error": "no CIK for ESZ6"}')
        return Result('{"success": true, "filings": [{"form_type": "8-K", "filing_date": "2026-09-01"}]}')

    gateway = FakeGateway(reply)
    run, store = run_template(world, "insider-and-filing-sweep", gateway)
    assert run["status"] == "ok", run
    assert [a["identifier"] for _, a in gateway.calls] == ["NVDA", "ESZ6", "AMD"]
    assert store.alerts()[0]["title"] == "2 new SEC filings on your watchlist"


def test_earnings_heads_up_keeps_only_the_coming_week(world, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(act, "_watchlist_symbols", lambda name, group="": ["NVDA", "AAPL"])
    calendars = {"NVDA": {"Earnings Date": [dt.date(2026, 9, 3)]}, "AAPL": {"Earnings Date": [dt.date(2026, 10, 30)]}}
    fake = types.SimpleNamespace(Ticker=lambda s: types.SimpleNamespace(calendar=calendars[s]))
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    run, store = run_template(world, "earnings-week-heads-up", FakeGateway(lambda c, a: Result("{}")))
    assert run["status"] == "ok", run
    assert store.alerts()[0]["title"] == "Earnings this week: NVDA"


def test_a_tool_error_inside_the_fence_fails_the_step_rather_than_passing(world) -> None:
    gateway = FakeGateway(lambda cap, args: fenced("Error calling tool 'x': HTTP error 422: bad provider"))
    run, _store = run_template(world, "headline-keyword-watch", gateway)
    assert run["status"] == "failed"
    assert "422" in run["steps"][0]["reason"]


def test_weekend_news_review_saves_the_brief_to_reviews_and_replaces_on_rerun(world, monkeypatch, tmp_path) -> None:  # noqa: ANN001
    import genesis.agents.research.news_catalyst as nc
    import genesis.llm.tiers as tiers
    import genesis.news as news
    import genesis.notebook.vault as vault_mod
    from genesis.automation.workflow import compile_declaration

    row = {"id": "br_1", "title": "Weekend news review — 2026-09-06", "body": {
        "overview": "Chips led; yields eased. " * 400,
        "stories": [{"headline": "NVDA guides higher", "what_happened": "Raised guidance.",
                     "why_it_matters": "Sets the tone for semis.", "symbols": ["NVDA"], "direction": "bullish"}],
        "themes": ["AI capex"], "watch": ["CPI Wednesday"],
        "trade_ideas": [{"idea": "Semis strength", "symbols": ["SMH"], "bias": "long",
                         "rationale": "Guidance reset", "invalidation": "CPI hot and yields jump"}],
        "risks": ["Hot CPI"], "confidence": 0.6, "considered": 40, "model": "fake", "flags": [],
        "articles": [{"n": 1, "title": "NVDA raises guidance", "url": "https://x.test/a", "publisher": "Wire",
                      "published": "2026-08-31T12:00", "read": True}]}}
    calls = []
    monkeypatch.setattr(nc, "write_brief", lambda *a, **k: calls.append(k) or row)
    monkeypatch.setattr(tiers, "build_tier", lambda config, tier: types.SimpleNamespace(backend=object(), note=""))
    # The store the brief is written to, and read back from by the promote
    # step: `news.ideas` fetches the brief by id rather than trusting whatever
    # text the previous step handed on.
    monkeypatch.setattr(news, "open_store", lambda: types.SimpleNamespace(
        close=lambda: None, brief=lambda _id: row if _id == row["id"] else None))
    # Ideas land in a store under tmp_path, never the real ~/.genesis one.
    import genesis.research.store as research_store

    real_store = research_store.ResearchStore
    monkeypatch.setattr(
        research_store, "ResearchStore",
        lambda **kw: real_store(path=tmp_path / "research.db", vault=None),
    )
    vault = vault_mod.Vault(tmp_path / "vault") if hasattr(vault_mod, "Vault") else None
    (tmp_path / "vault").mkdir()
    monkeypatch.setattr(vault_mod, "registry", lambda: types.SimpleNamespace(open=lambda name=None: vault))

    wf = by_id("weekend-news-review").workflow
    assert compile_declaration(wf).model_tier == "large", "a judgement node makes the workflow not a reflex"
    run, store = run_template(world, "weekend-news-review", FakeGateway(lambda c, a: Result("{}")), now=SUNDAY)
    assert run["status"] == "ok", run
    note = (tmp_path / "vault" / "Reviews" / "2026-09-06 Weekend news review.md").read_text()
    assert note.startswith("# Weekend news review — 2026-09-06")
    assert "## Trade ideas" in note and "*Invalidated if:* CPI hot" in note and "[NVDA raises guidance]" in note
    assert calls[0]["title"] == "Weekend news review — 2026-09-06" and calls[0]["hours"] == 72
    assert note.rstrip().endswith("brief br_1*"), "the whole brief is saved, not a truncated head"
    assert store.alerts()[0]["message"].startswith("1 stories, 1 trade ideas from 1 articles")

    # The brief's idea became a real idea, which is the difference between a
    # note that mentions a trade and a desk that can rank, size and measure it.
    promoted = next(s for s in run["steps"] if s["step"] == "ideas")
    assert promoted["status"] == "ok", promoted
    assert promoted["output"]["structured"]["ideas"], "the SMH long should have been stored"

    _bus, store2 = world
    agent = WorkflowAgent(wf, 1, store=store2, bus=_bus, calendar=MarketCalendar(), clock=lambda: SUNDAY)
    agent.start()

    class Again:
        id, trace_id, args = "t2", "tr2", {}

    agent.run_task(Again())
    again = (tmp_path / "vault" / "Reviews" / "2026-09-06 Weekend news review.md").read_text()
    assert again.count("# Weekend news review — 2026-09-06") == 1, "a same-day rerun replaces, not stacks"


def test_weekend_news_review_takes_the_fail_edge_when_no_model(world, monkeypatch) -> None:  # noqa: ANN001
    import genesis.llm.tiers as tiers

    monkeypatch.setattr(tiers, "build_tier", lambda c, t: types.SimpleNamespace(backend=None, note="GEMINI_API_KEY is not set"))
    run, store = run_template(world, "weekend-news-review", FakeGateway(lambda c, a: Result("{}")), now=SUNDAY)
    assert run["status"] == "ok"
    assert store.alerts()[0]["title"] == "Weekend news review could not be written"
    assert "GEMINI_API_KEY" in store.alerts()[0]["message"]


def test_the_weekend_review_does_not_run_on_a_weekday(world) -> None:  # noqa: ANN001
    """The cron is daily. Sunday is the first step, and it is load-bearing.

    Without the gate this writes a "weekend" synopsis every morning of the
    week, burns a large-tier call each time, and replaces the note it wrote the
    day before.
    """
    run, _store = run_template(world, "weekend-news-review",
                               FakeGateway(lambda c, a: Result("{}")), now=EVENING)
    assert run["status"] == "ok"
    steps = {s["step"]: s["status"] for s in run["steps"]}
    assert steps["sunday"] == "failed", steps
    assert steps["sunday-skip"] == "ok", "the gate stops the run rather than erroring it"
    assert steps.get("brief") in (None, "skipped"), "the model must not be called on a Tuesday"
