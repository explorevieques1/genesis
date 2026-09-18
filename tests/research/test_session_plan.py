# Spec: Genesis Markdown/20-Agents/Research/Agent — Session Plan.md
"""Your ideas in, a plan of action out. The gate is faked; the plan's rules are not."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest

from genesis.agents.research.session_plan import (
    PlanInputs,
    SessionPlanAgent,
    live_ideas,
    record_idea,
)
from genesis.errors import FatalError
from genesis.research.plan import build_plan, contract_for, ticket_for
from genesis.research.schema import Idea
from genesis.research.store import ResearchStore

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
NQ = "FUT:CME:NQ:2026-12"
ALLOW = ("ES", "NQ", "MNQ")


@pytest.fixture()
def store(tmp_path: Path) -> ResearchStore:
    return ResearchStore(path=tmp_path / "research.db", vault=tmp_path / "vault")


def idea(**kw) -> Idea:
    base = dict(symbol="NQ", direction="long", thesis="semis leading", invalidation="below 19950",
                invalidation_reason="the reclaim failed", conflicts="none found",
                entry_zone=(20000, 20050), stop_price=19950, targets=(20200,),
                confidence=0.6, author="human")
    base.update(kw)
    return Idea(**base)


def gate(approved: int = 2, *, decision: str = "approve", binding: str | None = None,
         check: str | None = None, in_session: bool = True, halted: bool = False):
    """A dry run's answer, in the order manager's own shape."""
    calls: list[dict] = []

    def size(ticket: dict) -> dict:
        calls.append(ticket)
        checks = [{"id": check or "portfolio_heat", "result": "fail",
                   "detail": "heat is 5.90% of a 6% limit"}] if decision == "reject" else []
        return {"decision": {"decision": decision, "approved_qty": approved, "binding_check": binding,
                             "worst_case_loss": "2000", "checks": checks,
                             "spoken_summary": "Rejected."},
                "now": {"in_session": in_session, "halted": halted, "mode": "confirm"},
                "mark": "20100"}

    size.calls = calls  # type: ignore[attr-defined]
    return size


def plan(ideas, **kw):
    kw.setdefault("allowlist", ALLOW)
    kw.setdefault("configured", [NQ])
    kw.setdefault("max_contracts", 2)
    kw.setdefault("now", NOW)
    return build_plan([(f"res_{n}", i) for n, i in enumerate(ideas)], **kw)


# --------------------------------------------------------------------------
# intake: no invalidation, no idea -- and the stop on the losing side
# --------------------------------------------------------------------------


def test_your_idea_is_recorded_and_read_back_with_every_number(store) -> None:
    note = record_idea(store, {"symbol": "nq", "direction": "long", "thesis": "semis leading",
                               "entry_zone": "20000-20050", "stop_price": 19950,
                               "targets": "20200"})
    assert note.created_by == "human"
    assert note.summary == "Long NQ 20000 to 20050, wrong at 19950."
    assert note.data["author"] == "human" and note.data["stop_price"] == 19950


def test_an_idea_with_no_thesis_is_a_hope_and_is_refused(store) -> None:
    with pytest.raises(FatalError, match="not an idea yet"):
        record_idea(store, {"symbol": "NQ", "direction": "long"})


def test_a_long_with_its_stop_above_the_entry_is_a_typo_caught_at_intake(store) -> None:
    with pytest.raises(FatalError, match="must be below its entry zone"):
        record_idea(store, {"symbol": "NQ", "direction": "long", "thesis": "x",
                            "entry_zone": [20000, 20050], "stop_price": 20950})


def test_your_idea_does_not_supersede_the_synthesizers(store) -> None:
    from genesis.research.schema import ResearchNote
    from genesis.research.store import new_note_id

    store.put(ResearchNote(id=new_note_id(), kind="idea", subject="nq", title="t",
                           created_by="idea-synthesizer",
                           data={**idea(author="idea-synthesizer").model_dump(mode="json"),
                                 "status": "active"}))
    record_idea(store, {"symbol": "NQ", "direction": "long", "thesis": "mine",
                        "entry_zone": [20000, 20050], "stop_price": 19950})
    authors = sorted(i.author for _, i in live_ideas(store))
    assert authors == ["human", "idea-synthesizer"]


def test_restating_your_idea_updates_it(store) -> None:
    for thesis in ("first take", "second take"):
        record_idea(store, {"symbol": "NQ", "direction": "long", "thesis": thesis,
                            "entry_zone": [20000, 20050], "stop_price": 19950})
    assert [i.thesis for _, i in live_ideas(store)] == ["second take"]


def test_an_idea_past_its_horizon_is_off_the_desk(store) -> None:
    record_idea(store, {"symbol": "NQ", "direction": "long", "thesis": "x", "horizon_days": 1,
                        "entry_zone": [20000, 20050], "stop_price": 19950})
    assert live_ideas(store, now=datetime.now(UTC) + timedelta(days=2)) == []


# --------------------------------------------------------------------------
# resolution: nobody knows the contract month
# --------------------------------------------------------------------------


def test_a_root_resolves_to_the_one_configured_contract() -> None:
    assert contract_for("NQ", allowlist=ALLOW, configured=[NQ, "EQ:XNAS:NVDA"]) == (NQ, None)


def test_two_configured_months_are_surfaced_not_picked() -> None:
    sid, why = contract_for("NQ", allowlist=ALLOW, configured=[NQ, "FUT:CME:NQ:2027-03"])
    assert sid is None and "ambiguous" in why


def test_no_configured_month_is_never_the_front_month() -> None:
    sid, why = contract_for("ES", allowlist=ALLOW, configured=[NQ])
    assert sid is None and "never guesses the front month" in why


def test_an_equity_is_not_on_a_futures_desk() -> None:
    sid, why = contract_for("NVDA", allowlist=ALLOW, configured=[])
    assert sid is None and "not on the allow-list" in why


def test_the_ticket_is_the_trade_panels_own_shape() -> None:
    """Priced at the zone's far edge: the fill furthest from the stop, so the size survives it."""
    t = ticket_for(idea(), NQ, max_contracts=2)
    assert t == {"symbol_id": NQ, "side": "buy", "qty": 2, "order_type": "limit",
                 "limit_price": "20050", "stop": {"kind": "fixed", "price": "19950"},
                 "origin": "plan", "target": {"price": "20200"}}


# --------------------------------------------------------------------------
# sizing is the gate's
# --------------------------------------------------------------------------


def test_the_size_is_the_gates_answer_to_the_exact_ticket() -> None:
    size = gate(approved=1, decision="resize", binding="portfolio_heat")
    p = plan([idea()], size=size)
    item = p.items[0]
    assert size.calls == [ticket_for(idea(), NQ, max_contracts=2)]
    assert item.size == 1 and item.binding == "portfolio_heat"
    assert "sized down by portfolio_heat" in item.conflicts


def test_no_order_path_means_no_sizes_and_it_says_so() -> None:
    p = plan([idea()], size=None)
    assert p.items[0].size is None
    assert any("nothing can be sized" in d for d in p.desk)


def test_no_stop_price_cannot_be_sized_and_says_why() -> None:
    size = gate()
    p = plan([idea(stop_price=None)], size=size)
    assert p.items[0].size is None and p.items[0].blocked
    assert size.calls == [], "a hope is never sent to the gate"
    assert any("cannot size a condition" in c for c in p.items[0].conflicts)


def test_no_heat_room_is_no_room_not_blocked() -> None:
    """Heat is the book's problem, not the idea's -- it becomes takeable as risk comes off."""
    p = plan([idea()], size=gate(approved=0, decision="reject", check="portfolio_heat"))
    item = p.items[0]
    assert item.size == 0 and not item.blocked
    assert any("heat is 5.90%" in c for c in item.conflicts)


def test_a_refusal_for_a_structural_reason_blocks_it() -> None:
    p = plan([idea()], size=gate(decision="reject", check="well_formed"))
    assert p.items[0].blocked


def test_a_closed_market_is_on_the_desk_not_hidden_in_the_size() -> None:
    p = plan([idea()], size=gate(in_session=False))
    assert p.items[0].size == 2
    assert any("market is closed now" in d for d in p.desk)


def test_a_halt_leads_the_desk() -> None:
    p = plan([idea()], size=gate(halted=True))
    assert p.desk[0].startswith("the kill switch is engaged")


# --------------------------------------------------------------------------
# what's in the way
# --------------------------------------------------------------------------


def test_opening_against_your_own_position_is_flagged() -> None:
    account = SimpleNamespace(positions=[SimpleNamespace(symbol=NQ, qty=-1)], problems=(),
                              degraded=False, degraded_reasons=(), portfolio_heat_pct=D("1.2"),
                              equity=D(100000))
    p = plan([idea()], size=gate(), account=account)
    assert any("trades against it" in c for c in p.items[0].conflicts)
    assert any("heat is 1.20%" in d for d in p.desk)


def test_a_print_inside_the_horizon_is_a_conflict_one_outside_is_not() -> None:
    events = [
        {"at": (NOW + timedelta(hours=3)).isoformat(), "title": "CPI m/m", "country": "USD", "all_day": False},
        {"at": (NOW + timedelta(days=20)).isoformat(), "title": "FOMC", "country": "USD", "all_day": False},
    ]
    p = plan([idea(timeframe="intraday")], size=gate(), events=events)
    conflicts = " ".join(p.items[0].conflicts)
    assert "CPI" in conflicts and "FOMC" not in conflicts


def test_a_lesson_that_names_the_setup_surfaces() -> None:
    lesson = SimpleNamespace(title="You enter ORB breakouts late", applies_when=("setup:orb_breakout",))
    other = SimpleNamespace(title="Gold on Fridays", applies_when=("symbol:GC",))
    p = plan([idea(setup="orb_breakout")], size=gate(), lessons=[lesson, other])
    assert "lesson: You enter ORB breakouts late" in p.items[0].conflicts
    assert not any("Gold" in c for c in p.items[0].conflicts)


# --------------------------------------------------------------------------
# ranking and the brief
# --------------------------------------------------------------------------


def test_actionable_ideas_rank_above_blocked_ones_then_by_score() -> None:
    weak = idea(confidence=0.3)
    strong = idea(confidence=0.9, direction="short", entry_zone=(20000, 20050), stop_price=20100,
                  targets=(19800,))
    hope = idea(stop_price=None, confidence=0.99)
    p = plan([weak, hope, strong], size=gate())
    assert [i.idea.confidence for i in p.items] == [0.9, 0.3, 0.99]
    assert [i.rank for i in p.items] == [1, 2, 3]


def test_the_brief_has_the_four_things_you_asked_for() -> None:
    p = plan([idea(setup="orb")], size=gate(approved=1, decision="resize", binding="max_contracts"))
    brief = p.brief()
    assert "## Ranked" in brief                         # ranked ideas with size
    assert "the gate would approve **1**" in brief
    assert "**Levels and triggers**" in brief           # levels
    assert "`19950` — invalidation" in brief
    assert "**In the way**" in brief                    # conflicts
    assert "> semis leading" in brief                   # your own words, quoted
    assert "nothing here is an order" in brief.lower()


def test_an_empty_desk_is_a_valid_plan() -> None:
    p = plan([], size=gate())
    assert "No live ideas" in p.spoken()
    assert "*No setup today* is a valid plan." in p.brief()


# --------------------------------------------------------------------------
# the agent: both task types, and the brief lands in the vault
# --------------------------------------------------------------------------


def _agent(store: ResearchStore, size=None) -> SessionPlanAgent:
    return SessionPlanAgent(store, inputs=PlanInputs(
        allowlist=lambda: list(ALLOW), configured=lambda: [NQ], max_contracts=lambda: 2,
        size=lambda: size,
    ))


def test_the_agent_records_then_plans_and_saves_a_brief(store, tmp_path) -> None:
    agent = _agent(store, size=gate(approved=2))
    said = agent.execute(SimpleNamespace(id="t1", type="idea.record", trace_id="tr",
                                         args={"symbol": "NQ", "direction": "long", "thesis": "semis",
                                               "entry_zone": [20000, 20050], "stop_price": 19950}))
    assert said.spoken_summary.startswith("Recorded: Long NQ 20000 to 20050, wrong at 19950")

    result = agent.execute(SimpleNamespace(id="t2", type="plan.build", trace_id="tr", args={}))
    assert result.data["actionable"] == 1
    assert result.data["vault_path"].startswith("10-Ideas/plans/")
    assert (tmp_path / "vault" / result.data["vault_path"]).exists()
    assert "brief is in your notes" in result.spoken_summary


def test_an_unavailable_input_is_a_stated_gap_not_a_crash(store) -> None:
    def broken() -> list:
        raise RuntimeError("calendar feed down")

    agent = SessionPlanAgent(store, inputs=PlanInputs(
        allowlist=lambda: list(ALLOW), configured=lambda: [NQ], max_contracts=lambda: 2,
        events=broken,
    ))
    plan_, _ = agent.build(save=False)
    assert any("economic calendar unavailable" in d for d in plan_.degraded)


def test_the_plan_agent_has_no_model() -> None:
    from genesis.agents.base import SPINAL_AGENTS
    from genesis.agents.research.session_plan import DECLARATION

    assert DECLARATION.model_tier == "none"
    assert "session-plan" in SPINAL_AGENTS


def test_a_short_is_priced_at_the_bottom_of_its_zone() -> None:
    t = ticket_for(idea(direction="short", stop_price=20100), NQ, max_contracts=1)
    assert t["side"] == "sell" and t["limit_price"] == "20000"


def test_a_quarter_point_price_survives_exactly() -> None:
    t = ticket_for(idea(entry_zone=(20000.25, 20050.75), stop_price=19950.5), NQ, max_contracts=1)
    assert t["limit_price"] == "20050.75" and t["stop"]["price"] == "19950.5"


def test_a_hope_gets_a_sentence_not_a_validation_error(store) -> None:
    with pytest.raises(FatalError, match="say where it's wrong") as exc:
        record_idea(store, {"symbol": "NVDA", "direction": "long", "thesis": "guided above"})
    assert "Field required" not in exc.value.reason


def test_a_condition_is_enough_to_record_but_not_to_size(store) -> None:
    note = record_idea(store, {"symbol": "NQ", "direction": "long", "thesis": "x",
                               "invalidation": "loses the 8/21 fair value gap"})
    assert note.data["stop_price"] is None
    p = plan([i for _, i in live_ideas(store)], size=gate())
    assert p.items[0].size is None and p.items[0].blocked


def test_the_reason_sizing_is_off_is_the_callers() -> None:
    p = plan([idea()], size=None, size_off="the server is not running on :8765")
    assert "the server is not running on :8765" in p.desk
    assert "| unsized |" in p.brief()


# --------------------------------------------------------------------------
# the HTTP door
# --------------------------------------------------------------------------


def test_the_routes_record_list_look_and_save(tmp_path, monkeypatch) -> None:
    """Looking writes nothing; saving writes the brief. Same functions as the agent."""
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    import genesis.config as cfg
    from genesis.server.plan_routes import plan_routes

    real = cfg.load_config
    base = real(None)
    config = base.model_copy(update={
        "memory": base.memory.model_copy(update={
            "db_path": tmp_path / "genesis.db", "vault_path": tmp_path / "vault"}),
    })
    monkeypatch.setattr(cfg, "load_config", lambda *a, **k: config)
    client = TestClient(Starlette(routes=plan_routes()))

    refused = client.post("/v1/ideas", data="{}")
    assert refused.status_code == 400 and "application/json" in refused.json()["reason"]

    hope = client.post("/v1/ideas", json={"symbol": "NQ", "direction": "long", "thesis": "x"})
    assert hope.status_code == 400 and "No invalidation, no idea" in hope.json()["reason"]

    added = client.post("/v1/ideas", json={"symbol": "NQ", "direction": "long", "thesis": "semis",
                                           "entry_zone": [20000, 20050], "stop_price": 19950})
    assert added.json()["summary"] == "Long NQ 20000 to 20050, wrong at 19950."
    assert [i["symbol"] for i in client.get("/v1/ideas").json()["ideas"]] == ["NQ"]

    looked = client.get("/v1/plan").json()
    assert looked["ok"] and "## Ranked" in looked["brief"]
    assert not (tmp_path / "vault" / "10-Ideas" / "plans").exists(), "looking is not writing"

    saved = client.post("/v1/plan", json={}).json()
    assert (tmp_path / "vault" / saved["vault_path"]).exists()
