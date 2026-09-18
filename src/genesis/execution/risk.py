# Spec: Genesis Markdown/50-Risk/Pre-Trade Risk Engine.md
"""The gate. A pure function: proposal + context in, decision out.

No I/O and no clock of its own. Everything it reads is gathered first and handed
over in :class:`RiskContext`, so every check can be tested by constructing the
exact situation that should trip it -- and so the engine cannot quietly go and
fetch a number that makes an order look safer.

**Fails closed.** Any input the context could not supply is ``None``, and a
check that meets ``None`` rejects with ``uncertain_input``. There is no default
that means "probably fine".

**Worst case, always.** Dollar risk is the full stop-out: stop distance in
points × contracts × the contract multiplier IBKR reported. Offsets in points
make this exact even on a delayed quote, which is why the ticket works in
points.

**The same for everyone.** Nothing here knows who proposed. A click on the
order ticket is checked exactly like an agent's proposal would be.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

__all__ = ["Check", "Decision", "Proposal", "RiskContext", "evaluate", "fingerprint"]

Side = Literal["buy", "sell"]
Intent = Literal["open", "reduce", "modify"]
ZERO = Decimal(0)

#: Checks the spec lists that do not apply to, or are not yet built for, a
#: single-account futures desk. Reported on every decision so the output never
#: implies they ran.
NOT_BUILT = (
    ("max_position_pct", "futures are capped in contracts, not % of notional"),
    ("correlated_exposure", "not built"),
    ("liquidity_adv", "not built"),
    ("event_window", "not built — the calendar feed exists (news/econ.py), the check does not"),
)


@dataclass(frozen=True)
class Proposal:
    """An order that does not exist yet. Carries no authority."""

    id: str
    created: str
    trace_id: str
    symbol_id: str
    root: str
    local_symbol: str
    con_id: int
    multiplier: Decimal
    min_tick: Decimal
    side: Side
    qty: int
    order_type: Literal["market", "limit"]
    intent: Intent = "open"
    origin: str = "human"
    limit_price: Decimal | None = None
    stop_kind: Literal["fixed", "trail", "none"] = "none"
    #: Fixed stops: exactly one of offset (points from entry) or price.
    stop_offset: Decimal | None = None
    stop_price: Decimal | None = None
    trail_amount: Decimal | None = None
    target_offset: Decimal | None = None
    target_price: Decimal | None = None
    tif: Literal["GTC", "DAY"] = "GTC"
    #: Modify only: the order being changed, and the stop it has now.
    modifies: str | None = None
    current_stop_price: Decimal | None = None
    #: Stamped at proposal time, never looked up later (Execution Quality).
    arrival_mid: Decimal | None = None
    arrival_bid: Decimal | None = None
    arrival_ask: Decimal | None = None
    arrival_ts: str | None = None
    arrival_source: str | None = None

    @property
    def signed_qty(self) -> int:
        return self.qty if self.side == "buy" else -self.qty

    @property
    def reference_price(self) -> Decimal | None:
        """What the stop and target are measured from before there is a fill."""
        return self.limit_price if self.order_type == "limit" else self.arrival_mid

    def stop_distance(self) -> Decimal | None:
        """Points from entry to stop. ``None`` when it cannot be known."""
        if self.stop_kind == "trail":
            return self.trail_amount
        if self.stop_kind != "fixed":
            return None
        if self.stop_offset is not None:
            return self.stop_offset
        ref = self.reference_price
        if self.stop_price is None or ref is None:
            return None
        return abs(ref - self.stop_price)

    def binds(self, qty: int | None = None) -> dict[str, Any]:
        """Everything an approval is bound to. Change any of it and the approval
        no longer matches."""
        s = lambda v: None if v is None else str(v)  # noqa: E731
        return {
            "proposal_id": self.id, "symbol_id": self.symbol_id, "con_id": self.con_id,
            "side": self.side, "qty": self.qty if qty is None else qty,
            "order_type": self.order_type, "intent": self.intent,
            "limit_price": s(self.limit_price), "stop_kind": self.stop_kind,
            "stop_offset": s(self.stop_offset), "stop_price": s(self.stop_price),
            "trail_amount": s(self.trail_amount), "target_offset": s(self.target_offset),
            "target_price": s(self.target_price), "tif": self.tif, "modifies": self.modifies,
        }


@dataclass(frozen=True)
class RiskContext:
    """Every input the gate reads. ``None`` means the value could not be had."""

    mode: str
    halted: bool | None
    allowlist: tuple[str, ...]
    max_contracts: int
    max_daily_loss_usd: Decimal
    max_price_deviation_pct: Decimal
    in_session: bool | None
    #: Signed contracts held in this contract.
    position_qty: int | None
    #: Signed contracts in unfilled entry orders for this contract.
    working_entry_qty: int = 0
    #: Today's P&L for the account, signed. Negative is a loss.
    daily_pnl: Decimal | None = None
    available_funds: Decimal | None = None
    init_margin_change: Decimal | None = None
    #: Fingerprints of recent placements -> monotonic seconds.
    recent: dict[str, float] = field(default_factory=dict)
    now_mono: float = field(default_factory=time.monotonic)
    #: Auto mode only.
    broker_healthy: bool = True
    killswitch_healthy: bool = False
    #: Check #8. Net liquidation, from the broker -- never the ledger's guess.
    equity: Decimal | None = None
    #: What can still be lost before this order: filled positions to their
    #: stops (or to zero where nothing covers them) plus working entries to
    #: theirs. The accountant's number; ``None`` means unknown, and unknown
    #: rejects.
    open_risk: Decimal | None = None
    max_portfolio_heat_pct: Decimal | None = None


@dataclass(frozen=True)
class Check:
    id: str
    result: Literal["pass", "fail", "resize", "not_built"]
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "result": self.result, "detail": self.detail}


@dataclass(frozen=True)
class Decision:
    proposal_id: str
    decision: Literal["approve", "resize", "reject"]
    original_qty: int
    approved_qty: int
    checks: tuple[Check, ...]
    binding_check: str | None
    worst_case_loss: Decimal | None
    #: True when a human must confirm before placement.
    requires_confirmation: bool
    evaluated_at: str
    elapsed_ms: float
    spoken_summary: str

    @property
    def approved(self) -> bool:
        return self.decision != "reject"

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id, "decision": self.decision,
            "original_qty": self.original_qty, "approved_qty": self.approved_qty,
            "binding_check": self.binding_check,
            "worst_case_loss": None if self.worst_case_loss is None else str(self.worst_case_loss),
            "requires_confirmation": self.requires_confirmation,
            "checks": [c.to_dict() for c in self.checks],
            "evaluated_at": self.evaluated_at, "elapsed_ms": round(self.elapsed_ms, 3),
            "spoken_summary": self.spoken_summary,
        }


def fingerprint(p: Proposal) -> str:
    """Near-identical orders share this. Used for the duplicate check."""
    b = p.binds()
    b.pop("proposal_id")
    return repr(sorted(b.items()))


class _Reject(Exception):
    def __init__(self, check: Check) -> None:
        self.check = check


DUPLICATE_WINDOW_SEC = 2.0


def evaluate(p: Proposal, ctx: RiskContext, *, now: datetime) -> Decision:
    """Run the checks in order. The first hard failure rejects; soft ones resize."""
    started = time.perf_counter()
    checks: list[Check] = []
    qty = p.qty
    binding: str | None = None
    worst: Decimal | None = None
    reducing = p.intent == "reduce"
    widening = p.intent == "modify" and p.stop_kind != "none" and _widens(p)

    def ok(cid: str, detail: str = "") -> None:
        checks.append(Check(cid, "pass", detail))

    def fail(cid: str, detail: str) -> None:
        raise _Reject(Check(cid, "fail", detail))

    try:
        # 1. Approval mode. In halt only risk-reducing orders pass (Approval Modes table).
        if ctx.mode == "advisory":
            fail("approval_mode", "advisory mode — orders are drafts only, nothing reaches the broker")
        if ctx.mode == "halt" and not reducing:
            fail("approval_mode", "halt mode — only closing orders are allowed")
        if ctx.mode not in ("confirm", "auto-within-limits", "halt"):
            fail("approval_mode", f"unknown approval mode {ctx.mode!r}")
        ok("approval_mode", ctx.mode)

        # 2. Kill switch. Unreadable flag is engaged.
        if ctx.halted is None:
            fail("kill_switch", "uncertain_input: the halt flag could not be read")
        if ctx.halted and not reducing:
            fail("kill_switch", "kill switch engaged — resume from the dashboard first")
        ok("kill_switch", "engaged, closing order allowed" if ctx.halted else "not engaged")

        # 3. Allow-list, by contract root.
        if p.root not in ctx.allowlist:
            fail("symbol_allowlist", f"{p.root} is not on the allow-list ({', '.join(ctx.allowlist)})")
        ok("symbol_allowlist", p.root)

        # 4. Session, from the contract's own trading hours.
        if ctx.in_session is None:
            fail("session_window", "uncertain_input: the contract's trading hours are unknown")
        if not ctx.in_session:
            fail("session_window", f"{p.local_symbol} is not trading now")
        ok("session_window", "inside trading hours")

        # 5. Well-formed.
        _well_formed(p, ctx, fail)
        ok("well_formed", "")

        # 6. Duplicate.
        seen = ctx.recent.get(fingerprint(p))
        if seen is not None and ctx.now_mono - seen < DUPLICATE_WINDOW_SEC:
            fail("duplicate", f"an identical order was placed {ctx.now_mono - seen:.1f}s ago")
        ok("duplicate", "")

        if ctx.position_qty is None:
            fail("position", "uncertain_input: the broker position for this contract is unknown")

        if reducing:
            if ctx.position_qty == 0 or (ctx.position_qty > 0) == (p.side == "buy"):
                fail("reduce", "nothing to close in that direction")
            if qty > abs(ctx.position_qty):
                fail("reduce", f"closing {qty} would reverse a position of {ctx.position_qty}")
            ok("reduce", f"closes {qty} of {ctx.position_qty}")
        elif p.intent == "open":
            if ctx.position_qty != 0 and (ctx.position_qty > 0) != (p.side == "buy"):
                fail("reduce", "this would trade against an open position — close or flatten it first")

            # 7'. Contracts cap: resize to headroom.
            held = abs(ctx.position_qty + ctx.working_entry_qty)
            headroom = ctx.max_contracts - held
            if headroom <= 0:
                fail("max_contracts", f"{held} held or working, limit {ctx.max_contracts}")
            if qty > headroom:
                checks.append(Check("max_contracts", "resize",
                                    f"{qty} → {headroom}: {held} held or working, limit {ctx.max_contracts}"))
                qty, binding = headroom, "max_contracts"
            else:
                ok("max_contracts", f"{held + qty} of {ctx.max_contracts}")

        # 8. Portfolio heat after this order, against the full stop-out.
        # Soft: resized down to the headroom, the way the spec's breach table
        # says heat is handled. Only an opening order adds heat; a widened stop
        # on an existing position is bound by the daily-loss check below.
        if p.intent == "open":
            qty, binding = _heat(p, ctx, qty, binding, checks, fail)

        # 10. Daily loss against the full stop-out.
        if p.intent == "open" or widening:
            distance = p.stop_distance() if p.intent == "open" else _modify_distance(p)
            if distance is None:
                fail("daily_loss", "uncertain_input: the stop distance cannot be computed")
            size = qty if p.intent == "open" else abs(ctx.position_qty)
            worst = distance * size * p.multiplier
            if ctx.daily_pnl is None:
                fail("daily_loss", "uncertain_input: today's P&L is unknown")
            used = max(ZERO, -ctx.daily_pnl)
            if used + worst > ctx.max_daily_loss_usd:
                fail("daily_loss", f"lost {used:.2f} today + worst case {worst:.2f} "
                                   f"exceeds {ctx.max_daily_loss_usd:.2f}")
            ok("daily_loss", f"used {used:.2f} + worst {worst:.2f} of {ctx.max_daily_loss_usd:.2f}")

        # 11. Prop firm: none configured (Open Questions §2).
        ok("prop_firm", "none configured")

        # 13. Buying power, from the broker's own what-if.
        if p.intent == "open":
            if ctx.available_funds is None or ctx.init_margin_change is None:
                fail("buying_power", "uncertain_input: margin could not be checked with the broker")
            per = ctx.init_margin_change / p.qty if p.qty else ZERO
            need = per * qty
            if need > ctx.available_funds:
                fail("buying_power", f"needs {need:.2f} initial margin, {ctx.available_funds:.2f} available")
            ok("buying_power", f"margin {need:.2f} of {ctx.available_funds:.2f} available")

    except _Reject as r:
        checks.append(r.check)
        return _decide(p, "reject", qty, checks, r.check.id, worst, False, started, now)

    for cid, why in NOT_BUILT:
        checks.append(Check(cid, "not_built", why))

    # 15. Auto mode needs a healthy path; otherwise demote to confirm, never drop.
    confirm = ctx.mode == "confirm" and p.intent == "open"
    if ctx.mode == "auto-within-limits" and p.intent == "open":
        if not (ctx.broker_healthy and ctx.killswitch_healthy):
            checks.append(Check("execution_path_healthy", "fail",
                                "kill switch process unreachable — demoted to confirm"
                                if ctx.broker_healthy else "broker unhealthy — demoted to confirm"))
            confirm = True
        else:
            checks.append(Check("execution_path_healthy", "pass", "broker and kill switch up"))

    return _decide(p, "resize" if qty != p.qty else "approve", qty, checks, binding, worst,
                   confirm, started, now)


def _heat(p: Proposal, ctx: RiskContext, qty: int, binding: str | None,
          checks: list[Check], fail: Any) -> tuple[int, str | None]:
    """Check #8: Σ open risk + this order's worst case ≤ max heat × equity.

    **Every input missing is a rejection.** Heat is the aggregate the envelope
    calls "the one that matters most" -- five 1% risks is a 5% day -- and a heat
    check that assumed zero for an input it could not read would pass exactly
    the order it exists to stop.
    """
    if ctx.max_portfolio_heat_pct is None:
        fail("portfolio_heat", "uncertain_input: no max_portfolio_heat_pct in the envelope")
    if ctx.equity is None or ctx.equity <= ZERO:
        fail("portfolio_heat", "uncertain_input: equity is unknown — heat has no denominator")
    if ctx.open_risk is None:
        fail("portfolio_heat", "uncertain_input: open risk is unknown — a working order "
                               "has no measurable stop, or the order book could not be read")
    distance = p.stop_distance()
    if distance is None or distance <= ZERO:
        fail("portfolio_heat", "uncertain_input: the stop distance cannot be computed")

    limit = ctx.equity * ctx.max_portfolio_heat_pct / Decimal(100)
    per = distance * p.multiplier
    headroom = limit - ctx.open_risk
    fits = int(headroom // per) if headroom > ZERO else 0

    def pct(money: Decimal) -> str:
        return f"{(money / ctx.equity * 100):.2f}%"

    if fits <= 0:
        fail("portfolio_heat", f"heat is {pct(ctx.open_risk)} of a {ctx.max_portfolio_heat_pct}% "
                               f"limit — one more contract adds {pct(per)}")
    if qty > fits:
        checks.append(Check("portfolio_heat", "resize",
                            f"{qty} → {fits}: heat would be {pct(ctx.open_risk + per * qty)}, "
                            f"limit {ctx.max_portfolio_heat_pct}%"))
        return fits, "portfolio_heat"
    checks.append(Check("portfolio_heat", "pass",
                        f"after {pct(ctx.open_risk + per * qty)} of {ctx.max_portfolio_heat_pct}%"))
    return qty, binding


def _decide(p: Proposal, decision: Any, qty: int, checks: list[Check], binding: str | None,
            worst: Decimal | None, confirm: bool, started: float, now: datetime) -> Decision:
    if decision == "reject":
        failed = checks[-1]
        summary = f"Rejected: {failed.detail}."
    else:
        verb = {"open": "Approved", "reduce": "Close approved", "modify": "Change approved"}[p.intent]
        summary = f"{verb}: {p.side} {qty} {p.local_symbol}"
        if worst is not None:
            summary += f", risk {worst:.2f}"
        if decision == "resize":
            summary += f" (resized from {p.qty} by {binding})"
        summary += "."
    return Decision(
        proposal_id=p.id, decision=decision, original_qty=p.qty, approved_qty=qty,
        checks=tuple(checks), binding_check=binding, worst_case_loss=worst,
        requires_confirmation=confirm, evaluated_at=now.isoformat(),
        elapsed_ms=(time.perf_counter() - started) * 1000, spoken_summary=summary,
    )


def _on_tick(price: Decimal, tick: Decimal) -> bool:
    return tick > 0 and price % tick == 0


def _well_formed(p: Proposal, ctx: RiskContext, fail: Any) -> None:
    if not isinstance(p.qty, int) or isinstance(p.qty, bool) or p.qty < 1:
        fail("well_formed", f"quantity must be a whole number of contracts, got {p.qty!r}")
    if p.side not in ("buy", "sell"):
        fail("well_formed", f"unknown side {p.side!r}")
    if p.multiplier is None or p.multiplier <= 0 or p.min_tick is None or p.min_tick <= 0:
        fail("well_formed", "uncertain_input: contract multiplier or tick size unknown")

    for name in ("limit_price", "stop_price", "target_price"):
        value = getattr(p, name)
        if value is not None and (value <= 0 or not _on_tick(value, p.min_tick)):
            fail("well_formed", f"{name.replace('_', ' ')} {value} is not a positive multiple of the "
                                f"{p.min_tick} tick")
    for name in ("stop_offset", "trail_amount", "target_offset"):
        value = getattr(p, name)
        if value is not None and (value <= 0 or not _on_tick(value, p.min_tick)):
            fail("well_formed", f"{name.replace('_', ' ')} {value} must be a positive multiple of "
                                f"{p.min_tick} points")

    if p.order_type == "limit":
        if p.limit_price is None:
            fail("well_formed", "a limit order needs a limit price")
        _band(p, p.limit_price, "limit", ctx, fail)
    elif p.order_type != "market":
        fail("well_formed", f"unknown order type {p.order_type!r}")

    if p.intent == "modify":
        if p.modifies is None:
            fail("well_formed", "a change must name the order it changes")
        return
    if p.intent == "reduce":
        return

    # Opening risk: a stop is mandatory. A position without one is an unbounded loss.
    if p.stop_kind == "none":
        fail("well_formed", "no stop — the worst case is unbounded. Set a stop or a trailing stop")
    if p.stop_kind == "trail" and p.trail_amount is None:
        fail("well_formed", "a trailing stop needs a trail amount in points")
    if p.stop_kind == "fixed" and (p.stop_offset is None) == (p.stop_price is None):
        fail("well_formed", "a fixed stop takes an offset in points or a price, exactly one")
    if p.target_offset is not None and p.target_price is not None:
        fail("well_formed", "a target takes an offset in points or a price, not both")

    ref = p.reference_price
    long = p.side == "buy"
    if p.stop_price is not None:
        if ref is None:
            fail("well_formed", "uncertain_input: no quote to check the stop's side against")
        if (p.stop_price >= ref) if long else (p.stop_price <= ref):
            fail("well_formed", f"stop {p.stop_price} is on the wrong side of entry {ref}")
        _band(p, p.stop_price, "stop", ctx, fail)
    if p.target_price is not None:
        if ref is None:
            fail("well_formed", "uncertain_input: no quote to check the target's side against")
        if (p.target_price <= ref) if long else (p.target_price >= ref):
            fail("well_formed", f"target {p.target_price} is on the wrong side of entry {ref}")


def _band(p: Proposal, price: Decimal, what: str, ctx: RiskContext, fail: Any) -> None:
    if p.arrival_mid is None or p.arrival_mid <= 0:
        fail("well_formed", f"uncertain_input: no arrival quote to check the {what} price against")
    deviation = abs(price - p.arrival_mid) / p.arrival_mid * 100
    if deviation > ctx.max_price_deviation_pct:
        fail("well_formed", f"{what} {price} is {deviation:.2f}% from the quote {p.arrival_mid} "
                            f"(limit {ctx.max_price_deviation_pct}%) — fat-finger guard")


def _widens(p: Proposal) -> bool:
    """A stop change that moves it away from the market enlarges risk (Order Manager)."""
    if p.current_stop_price is None:
        return True  # unknown current stop: treat as widening, so it is checked
    if p.stop_price is None:
        return p.trail_amount is not None  # converting to a trail: check its distance
    return p.stop_price < p.current_stop_price if p.side == "sell" else p.stop_price > p.current_stop_price


def _modify_distance(p: Proposal) -> Decimal | None:
    """Points of loss from the reference to the new stop, for a widening change.

    ``side`` on a modify is the *stop order's* side: a sell stop protects a long.
    """
    if p.trail_amount is not None and p.stop_price is None:
        return p.trail_amount
    if p.stop_price is None or p.arrival_mid is None:
        return None
    return max(ZERO, (p.arrival_mid - p.stop_price) if p.side == "sell" else (p.stop_price - p.arrival_mid))

