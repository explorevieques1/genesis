# Spec: Genesis Markdown/50-Risk/Pre-Trade Risk Engine.md §Testing — mandatory
"""Every check gets a test that tries to violate it, and one legitimate order passes."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from genesis.execution.risk import Proposal, RiskContext, evaluate, fingerprint

NOW = datetime(2026, 9, 14, 14, 0, tzinfo=UTC)


def proposal(**kw) -> Proposal:
    base = dict(
        id="ord_prop_1", created=NOW.isoformat(), trace_id="tr_1",
        symbol_id="FUT:CME:NQ:2026-12", root="NQ", local_symbol="NQZ6", con_id=1,
        multiplier=D(20), min_tick=D("0.25"), side="buy", qty=1, order_type="market",
        stop_kind="fixed", stop_offset=D(20), target_offset=D(40),
        arrival_mid=D("29365.25"), arrival_source="delayed",
    )
    base.update(kw)
    return Proposal(**base)


def ctx(**kw) -> RiskContext:
    base = dict(
        mode="confirm", halted=False, allowlist=("ES", "NQ", "MNQ"), max_contracts=2,
        max_daily_loss_usd=D(2000), max_price_deviation_pct=D(2), in_session=True,
        position_qty=0, daily_pnl=D(0), available_funds=D(100000), init_margin_change=D(30000),
        killswitch_healthy=True,
        equity=D(100000), open_risk=D(0), max_portfolio_heat_pct=D(6),
    )
    base.update(kw)
    return RiskContext(**base)


def run(p: Proposal | None = None, c: RiskContext | None = None):
    return evaluate(p or proposal(), c or ctx(), now=NOW)


def rejected_by(decision) -> str:
    assert decision.decision == "reject", decision.to_dict()
    return decision.checks[-1].id


def test_a_legitimate_order_passes_with_worst_case_in_dollars():
    d = run()
    assert d.decision == "approve" and d.approved_qty == 1
    assert d.worst_case_loss == D(400)  # 20 pts × 1 × $20
    assert d.requires_confirmation
    assert "portfolio_heat" not in {c.id for c in d.checks if c.result == "not_built"}
    assert any(c.id == "portfolio_heat" and c.result == "pass" for c in d.checks)


@pytest.mark.parametrize("mode", ["advisory", "halt", "yolo"])
def test_mode_that_forbids_opening_rejects(mode):
    assert rejected_by(run(c=ctx(mode=mode))) == "approval_mode"


def test_engaged_or_unreadable_halt_rejects():
    assert rejected_by(run(c=ctx(halted=True))) == "kill_switch"
    assert rejected_by(run(c=ctx(halted=None))) == "kill_switch"


def test_halt_still_lets_a_position_be_closed():
    p = proposal(side="sell", intent="reduce", stop_kind="none", stop_offset=None, target_offset=None)
    d = run(p, ctx(mode="halt", halted=True, position_qty=1))
    assert d.approved, d.to_dict()


def test_symbol_off_the_allowlist_rejects():
    assert rejected_by(run(proposal(root="CL"))) == "symbol_allowlist"


def test_outside_or_unknown_session_rejects():
    assert rejected_by(run(c=ctx(in_session=False))) == "session_window"
    assert rejected_by(run(c=ctx(in_session=None))) == "session_window"


@pytest.mark.parametrize("change", [
    dict(qty=0),
    dict(stop_kind="none", stop_offset=None),
    dict(stop_offset=D("20.1")),                                   # off tick
    dict(order_type="limit"),                                      # no limit price
    dict(order_type="limit", limit_price=D(25000)),                # fat finger
    dict(stop_offset=None, stop_price=D(29400)),                   # stop above a buy
    dict(target_offset=None, target_price=D(29300)),               # target below a buy
    dict(stop_kind="trail", stop_offset=None, trail_amount=None),
    dict(multiplier=None),
    dict(order_type="limit", limit_price=D(29360), arrival_mid=None),  # nothing to band against
])
def test_malformed_orders_reject(change):
    assert rejected_by(run(proposal(**change))) == "well_formed"


def test_duplicate_within_two_seconds_rejects():
    p = proposal()
    assert rejected_by(run(p, ctx(recent={fingerprint(p): 100.0}, now_mono=101.0))) == "duplicate"
    assert run(p, ctx(recent={fingerprint(p): 100.0}, now_mono=103.0)).approved


def test_contracts_cap_resizes_then_rejects():
    d = run(proposal(qty=3))
    assert d.decision == "resize" and d.approved_qty == 2 and d.binding_check == "max_contracts"
    assert d.worst_case_loss == D(800)
    assert rejected_by(run(c=ctx(position_qty=1, working_entry_qty=1))) == "max_contracts"


def test_opening_against_a_position_rejects():
    assert rejected_by(run(proposal(side="sell"), ctx(position_qty=1))) == "reduce"


def test_daily_loss_counts_the_full_stop_out():
    assert rejected_by(run(c=ctx(daily_pnl=D(-1700)))) == "daily_loss"   # 1700 + 400 > 2000
    assert run(c=ctx(daily_pnl=D(-1600))).approved                      # exactly 2000 is allowed
    assert rejected_by(run(c=ctx(daily_pnl=None))) == "daily_loss"


def test_margin_unknown_or_short_rejects():
    assert rejected_by(run(c=ctx(init_margin_change=None))) == "buying_power"
    assert rejected_by(run(c=ctx(available_funds=D(1000)))) == "buying_power"


def test_unknown_position_rejects():
    assert rejected_by(run(c=ctx(position_qty=None))) == "position"


def test_reduce_cannot_reverse():
    p = proposal(side="sell", qty=2, intent="reduce", stop_kind="none", stop_offset=None, target_offset=None)
    assert rejected_by(run(p, ctx(position_qty=1))) == "reduce"


def test_auto_mode_demotes_to_confirm_when_the_kill_switch_is_down():
    assert not run(c=ctx(mode="auto-within-limits")).requires_confirmation
    d = run(c=ctx(mode="auto-within-limits", killswitch_healthy=False))
    assert d.approved and d.requires_confirmation


def test_widening_a_stop_is_rechecked_and_tightening_is_not():
    widen = proposal(intent="modify", side="sell", modifies="gen_x_sl", stop_kind="fixed",
                     stop_offset=None, target_offset=None, stop_price=D(29000),
                     current_stop_price=D(29300))
    assert rejected_by(run(widen, ctx(position_qty=2, daily_pnl=D(-1500)))) == "daily_loss"
    tighten = replace(widen, stop_price=D(29340))
    assert run(tighten, ctx(position_qty=2, daily_pnl=D(-1999))).approved


def test_fuzz_nothing_crashes():
    import random
    rnd = random.Random(7)
    vals = [None, D(0), D(-1), D("0.1"), D(29365), D(10**9)]
    for _ in range(400):
        p = proposal(qty=rnd.choice([0, 1, 5, -1]), side=rnd.choice(["buy", "sell", "x"]),
                     order_type=rnd.choice(["market", "limit", "stop"]),
                     limit_price=rnd.choice(vals), stop_offset=rnd.choice(vals),
                     stop_price=rnd.choice(vals), target_price=rnd.choice(vals),
                     arrival_mid=rnd.choice(vals), stop_kind=rnd.choice(["fixed", "trail", "none"]),
                     trail_amount=rnd.choice(vals))
        run(p)  # must return a Decision, never raise


# --------------------------------------------------------------------------
# 8. Portfolio heat
# --------------------------------------------------------------------------
# One NQ contract with a 20-point stop is 20 x $20 = $400 of risk. On $100k
# equity at a 6% limit, the heat budget is $6,000.


def test_heat_under_the_limit_passes_and_says_where_it_lands():
    d = run(c=ctx(open_risk=D(1000)))
    heat = next(c for c in d.checks if c.id == "portfolio_heat")
    assert d.decision == "approve" and heat.result == "pass"
    assert "1.40%" in heat.detail  # (1000 + 400) / 100000


def test_heat_over_the_limit_resizes_down_to_the_headroom():
    """Soft, per the breach table: heat resizes, it does not reject outright."""
    d = run(proposal(qty=5), ctx(max_contracts=10, open_risk=D(5000)))
    assert d.decision == "resize" and d.approved_qty == 2  # $1000 headroom / $400
    assert d.binding_check == "portfolio_heat"


def test_no_headroom_at_all_rejects():
    assert rejected_by(run(c=ctx(open_risk=D(5800)))) == "portfolio_heat"


@pytest.mark.parametrize("missing", [
    {"equity": None}, {"equity": D(0)}, {"open_risk": None}, {"max_portfolio_heat_pct": None},
])
def test_every_unknown_heat_input_rejects(missing):
    """Fail closed: a heat check that assumed zero passes the order it exists to stop."""
    assert rejected_by(run(c=ctx(**missing))) == "portfolio_heat"


def test_heat_does_not_block_closing_a_position():
    p = proposal(side="sell", intent="reduce", stop_kind="none", stop_offset=None, target_offset=None)
    d = run(p, ctx(position_qty=1, open_risk=D(999999), equity=None))
    assert d.approved, d.to_dict()


def test_heat_counts_the_multiplier():
    """An MNQ is $2 a point; the same stop is a tenth of the risk and ten times the room."""
    d = run(proposal(qty=10, root="MNQ", multiplier=D(2)), ctx(max_contracts=20, open_risk=D(5800)))
    assert d.approved_qty == 5  # $200 headroom / (20 pts x $2)
