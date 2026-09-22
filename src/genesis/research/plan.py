# Spec: Genesis Markdown/20-Agents/Research/Agent — Session Plan.md
"""A plan of action from the ideas on the desk. Genesis advises; you decide.

Four things per idea, because those are what a head trader asks the desk for
before the open: **how much the gate would let me do**, **where to act and
where I'm wrong**, **what is in the way**, and **a brief I can re-read**.

**No sizing lives here.** Every size in a plan is the pre-trade risk gate's own
answer to a dry run of the exact ticket (:meth:`OrderManager.dry_run`), so the
plan and the gate cannot disagree about how much is allowed -- there is one
implementation of sizing in the system, and it is the one that guards orders.
Safety Invariants #3: a language model never sizes a position, and neither does
a second copy of the rules that drifts from the first.

**No model either.** Every line of a plan is assembled from stored records and
the gate's answers. The thesis is the trader's own words, quoted. The judgement
layer is the conversation *about* the plan -- the orchestrator can read the
saved note and argue with it -- not a paragraph generated into it, which would
put the one component that can hallucinate into a document about money.

**Nothing here is an order.** Each item carries the exact ticket the trade
panel would propose, so acting on a plan is still ``propose → approve → place``
through the same door as everything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Sequence

from genesis.research.schema import Idea

__all__ = ["PlanItem", "SessionPlan", "build_plan", "contract_for", "ticket_for"]


# --------------------------------------------------------------------------
# Resolution: nobody knows the ticker, and nobody knows the contract month
# --------------------------------------------------------------------------


def contract_for(
    symbol: str, *, allowlist: Sequence[str], configured: Iterable[str],
    futures_roots: Sequence[str] | None = None,
) -> tuple[str | None, str | None]:
    """``(symbol_id, why_not)``. Deterministic; ambiguity surfaced, never picked.

    A futures idea says "NQ". The order path needs a contract with a month, and
    Open Questions §13 forbids guessing "the front month" -- so the month comes
    from the contracts this install has configured, and "NQ" with two of them
    configured is a question for the trader, not a choice for the plan.

    An **equity or ETF** has no month and needs none: `SPY` resolves straight to
    `EQ:XNAS:SPY`. The two are told apart by ``futures_roots`` -- the risk
    envelope's own list -- rather than by guessing from the ticker's shape,
    because plenty of equity tickers look exactly like futures roots.
    """
    s = symbol.strip()
    futures = {r.upper() for r in (futures_roots if futures_roots is not None else allowlist)}
    if s.upper().startswith("FUT:"):
        root = s.split(":")[2].upper() if s.count(":") >= 3 else ""
        if root not in allowlist:
            return None, f"{root or s} is not on the allow-list ({', '.join(allowlist)})"
        return s, None
    root = s.upper()
    if root not in allowlist:
        shown = list(allowlist)
        return None, (
            f"{root} is not on the allow-list — this desk trades "
            + (", ".join(shown) if len(shown) <= 12
               else f"{len(shown)} symbols: {', '.join(shown[:8])}…")
        )
    if root not in futures:
        # An equity or ETF on the allow-list. `resolve_symbol` is the one
        # resolver in the system, and it refuses what it cannot resolve rather
        # than inventing an exchange.
        from genesis.marketdata.source import resolve_symbol

        try:
            return resolve_symbol(root), None
        except Exception as exc:  # noqa: BLE001 - an unresolvable ticker is a reason, not a crash
            return None, f"{root} could not be resolved to an instrument: {exc}"
    matches = sorted(
        {c for c in configured if c.upper().startswith("FUT:") and c.split(":")[2].upper() == root}
    )
    if len(matches) == 1:
        return matches[0], None
    if matches:
        return None, f"{root} is ambiguous — configured contracts: {', '.join(matches)}"
    return None, (
        f"no {root} contract is configured — name the month (e.g. FUT:CME:{root}:2026-12); "
        f"the plan never guesses the front month"
    )


def ticket_for(idea: Idea, symbol_id: str, *, max_contracts: int, idea_id: str = "") -> dict[str, Any] | None:
    """The trade panel's own ticket shape. ``None`` when the idea cannot be sized.

    Asks for the most the envelope could ever allow and lets the gate resize it
    down, so the answer is "how much" rather than "is 1 OK".

    **Priced at the far edge of the entry zone** -- the top for a long, the
    bottom for a short. That is the fill furthest from the stop, so the size is
    the one that survives the worst entry inside the zone ("worst case,
    always"), and it is a price the trader actually wrote down -- the midpoint
    of two prices on the tick grid need not be on it, and the gate would refuse
    it for that rather than for anything that matters.
    """
    if idea.stop_price is None or idea.entry_zone is None:
        return None
    lo, hi = idea.entry_zone
    ticket: dict[str, Any] = {
        "symbol_id": symbol_id,
        "side": "buy" if idea.direction == "long" else "sell",
        "qty": max_contracts,
        "order_type": "limit",
        "limit_price": _price(hi if idea.direction == "long" else lo),
        "stop": {"kind": "fixed", "price": _price(idea.stop_price)},
        # `{kind, ref}`, per Order And Fill Schema: the ref is what lets a fill
        # be traced back to the idea that proposed it, and therefore what lets
        # the weekly review answer "how are the news ideas doing?".
        "origin": {"kind": "idea", "ref": idea_id},
    }
    if idea.targets:
        ticket["target"] = {"price": _price(idea.targets[0])}
    return ticket


def _price(value: float) -> str:
    """A float from the idea as the exact decimal string the ticket parses.

    ``str(Decimal(str(20025.0)))`` is ``"20025.0"``; this is ``"20025"``, and
    ``20025.25`` stays ``"20025.25"`` -- never ``:g``, which rounds six figures.
    """
    d = Decimal(str(value))
    return str(d.quantize(Decimal(1)) if d == d.to_integral_value() else d)


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanItem:
    idea_id: str
    idea: Idea
    rank: int
    symbol_id: str | None
    #: Contracts the gate would approve, sized as if the market were open.
    size: int | None
    binding: str | None
    worst_case: str | None
    mark: str | None
    levels: tuple[dict[str, Any], ...]
    conflicts: tuple[str, ...]
    #: True when something stops this idea *before* sizing is the question.
    blocked: bool
    ticket: dict[str, Any] | None
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank, "idea_id": self.idea_id, "symbol": self.idea.symbol,
            "symbol_id": self.symbol_id, "direction": self.idea.direction,
            "setup": self.idea.setup, "timeframe": self.idea.timeframe,
            "author": self.idea.author, "confidence": self.idea.confidence,
            "rr": None if self.idea.rr is None else round(self.idea.rr, 2),
            "size": self.size, "binding": self.binding, "worst_case": self.worst_case,
            "mark": self.mark, "levels": list(self.levels), "conflicts": list(self.conflicts),
            "blocked": self.blocked, "ticket": self.ticket, "score": round(self.score, 4),
            "thesis": self.idea.thesis, "invalidation": self.idea.invalidation,
        }


@dataclass(frozen=True)
class SessionPlan:
    as_of: str
    items: tuple[PlanItem, ...]
    #: Desk-level: the things in the way of *everything*, not one idea.
    desk: tuple[str, ...] = ()
    degraded: tuple[str, ...] = ()
    sources: dict[str, Any] = field(default_factory=dict)

    @property
    def actionable(self) -> tuple[PlanItem, ...]:
        return tuple(i for i in self.items if not i.blocked and (i.size or 0) > 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of, "items": [i.to_dict() for i in self.items],
            "desk": list(self.desk), "degraded": list(self.degraded),
            "actionable": len(self.actionable), "sources": self.sources,
        }

    def spoken(self) -> str:
        """One or two sentences. The brief is for reading; this is for hearing."""
        if not self.items:
            return "No live ideas on the desk, so there's no plan to make."
        top = self.actionable[:1]
        head = (
            f"{len(self.actionable)} of {len(self.items)} ideas are actionable."
            if self.actionable else f"None of the {len(self.items)} ideas can be taken right now."
        )
        if top:
            i = top[0]
            head += (
                f" First is {i.idea.direction} {i.idea.symbol}, {i.size} "
                f"contract{'s' if i.size != 1 else ''}, wrong at {i.idea.stop_price:g}."
            )
        if self.desk:
            head += f" In the way: {self.desk[0]}"
        return head

    def brief(self) -> str:
        """The written brief. Markdown, because it lands in the vault."""
        lines = [
            f"# Plan of action — {self.as_of[:16].replace('T', ' ')} UTC",
            "",
            "> Genesis advises; you decide. Sizes are the risk gate's answer to a dry "
            "run of each ticket, **as if the market were open** — nothing here is an "
            "order, and each ticket still goes propose → approve → place.",
            "",
        ]
        if self.desk:
            lines += ["## In the way of everything", ""]
            lines += [f"- {d}" for d in self.desk]
            lines.append("")
        if self.degraded:
            lines += ["## Degraded", ""]
            lines += [f"- {d}" for d in self.degraded]
            lines.append("")

        lines += ["## Ranked", ""]
        if not self.items:
            lines += ["No live ideas. *No setup today* is a valid plan.", ""]
        else:
            lines += [
                "| # | Idea | Size | Bound by | R:R | Worst case | |",
                "|---|---|---|---|---|---|---|",
            ]
            for i in self.items:
                size = "—" if i.size is None else str(i.size)
                rr = "—" if i.idea.rr is None else f"{i.idea.rr:.1f}"
                state = ("blocked" if i.blocked else "unsized" if i.size is None
                         else "ready" if i.size else "no room")
                lines.append(
                    f"| {i.rank} | {i.idea.direction} {i.idea.symbol}"
                    f"{' · ' + i.idea.setup if i.idea.setup else ''} | {size} | "
                    f"{i.binding or '—'} | {rr} | {i.worst_case or '—'} | {state} |"
                )
            lines.append("")

        for i in self.items:
            lines += [
                f"## {i.rank}. {i.idea.direction.capitalize()} {i.idea.symbol}"
                f"{' — ' + i.idea.setup if i.idea.setup else ''}",
                "",
                f"*{'Your idea' if i.idea.author == 'human' else 'From ' + i.idea.author}"
                f" · {i.idea.timeframe} · confidence {i.idea.confidence:.0%}"
                f"{' · mark ' + i.mark if i.mark else ''}*",
                "",
                "**Levels and triggers**",
                "",
            ]
            lines += [f"- `{lv['price']}` — {lv['role']}: {lv['trigger']}" for lv in i.levels] or [
                "- none stated"
            ]
            lines += ["", "**Size**", ""]
            if i.size is None:
                lines.append("- cannot be sized — see below")
            else:
                lines.append(
                    f"- the gate would approve **{i.size}**"
                    f"{' (bound by ' + i.binding + ')' if i.binding else ''}"
                    f"{', worst case ' + i.worst_case if i.worst_case else ''}"
                )
            lines += ["", "**In the way**", ""]
            lines += [f"- {c}" for c in i.conflicts] or ["- nothing found"]
            lines += [
                "",
                "**Thesis**",
                "",
                f"> {i.idea.thesis}",
                "",
                f"**Wrong if** {i.idea.invalidation} — {i.idea.invalidation_reason}",
                "",
            ]

        lines += ["---", "", "*Built from:* " + ", ".join(
            f"{k} {v}" for k, v in self.sources.items()
        ), ""]
        return "\n".join(lines)


# --------------------------------------------------------------------------


def _root(symbol: str) -> str:
    """``FUT:CME:NQ:2026-12`` and ``NQ`` are the same instrument to a trader."""
    parts = symbol.upper().split(":")
    return parts[2] if len(parts) >= 3 else parts[0]


def _levels(idea: Idea, mark: Decimal | None) -> list[dict[str, Any]]:
    """Where to act and where the idea dies. Prices are the idea's own."""
    out: list[dict[str, Any]] = []

    def away(price: float) -> str:
        if mark is None or mark == 0:
            return ""
        pct = (Decimal(str(price)) - mark) / mark * 100
        return f" ({pct:+.2f}% from {mark})"

    if idea.entry_zone:
        lo, hi = idea.entry_zone
        verb = "pulls back into" if idea.direction == "long" else "rallies into"
        out.append({
            "price": f"{lo:g}–{hi:g}", "role": "entry",
            "trigger": f"act when price {verb} the zone{away((lo + hi) / 2)}",
        })
    if idea.stop_price is not None:
        side = "below" if idea.direction == "long" else "above"
        out.append({
            "price": f"{idea.stop_price:g}", "role": "invalidation",
            "trigger": f"the idea is void {side} here{away(idea.stop_price)}",
        })
    for n, target in enumerate(idea.targets, 1):
        out.append({"price": f"{target:g}", "role": f"target {n}",
                    "trigger": f"take or trail here{away(target)}"})
    return out


def _score(idea: Idea) -> float:
    """Confidence weighted by reward:risk, capped at 3R.

    Stated here so a surprising rank is inspectable. The cap stops a 10R
    lottery ticket outranking a 2R idea you believe in; an idea with no
    computable R:R ranks at half weight rather than zero, because "I haven't
    written targets yet" is not the same as "this is a bad idea".
    """
    rr = idea.rr
    return idea.confidence * (min(rr, 3.0) / 3.0 if rr else 0.5)


def build_plan(
    ideas: Sequence[tuple[str, Idea]],
    *,
    allowlist: Sequence[str],
    configured: Iterable[str],
    max_contracts: int,
    #: The futures half of the allow-list. Everything else on it is an equity
    #: or an ETF, which resolves without a contract month.
    futures_roots: Sequence[str] | None = None,
    size: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    account: Any = None,
    lessons: Sequence[Any] = (),
    events: Sequence[dict[str, Any]] = (),
    now: datetime | None = None,
    size_off: str = "nothing can be sized — the risk gate is not available",
) -> SessionPlan:
    """Assemble a plan from live ideas and whatever the desk can see.

    Every collaborator is optional and its absence is *stated*: no order path
    means no sizes and a desk line saying so, not sizes of zero.
    """
    now = now or datetime.now(UTC)
    configured = list(configured)
    desk: list[str] = []
    degraded: list[str] = []
    session_closed = halted = False

    if size is None:
        desk.append(size_off)
    if account is not None:
        if account.portfolio_heat_pct is not None and account.equity:
            desk.append(f"heat is {account.portfolio_heat_pct:.2f}% of equity before any of this")
        if account.problems:
            desk += list(account.problems)
        if account.degraded:
            degraded += list(account.degraded_reasons)

    upcoming = [e for e in events if not e.get("all_day")]

    staged: list[dict[str, Any]] = []
    for idea_id, idea in ideas:
        conflicts: list[str] = []
        blocked = False
        symbol_id, why = contract_for(idea.symbol, allowlist=allowlist, configured=configured,
                                      futures_roots=futures_roots)
        if why:
            conflicts.append(why)
            blocked = True

        ticket = None
        if idea.stop_price is None:
            conflicts.append(
                "no invalidation price — say where it's wrong as a number; "
                "the gate cannot size a condition"
            )
            blocked = True
        elif idea.entry_zone is None:
            conflicts.append("no entry zone — the gate measures risk from entry to stop")
            blocked = True
        elif symbol_id:
            ticket = ticket_for(idea, symbol_id, max_contracts=max_contracts, idea_id=idea_id)

        qty = binding = worst = mark = None
        if ticket is not None and size is not None:
            try:
                answer = size(ticket)
            except Exception as exc:  # noqa: BLE001 - one idea failing is its conflict
                conflicts.append(f"the gate could not evaluate it: {getattr(exc, 'reason', exc)}")
                blocked = True
                answer = None
            if answer:
                d = answer["decision"]
                mark = answer.get("mark")
                state = answer.get("now") or {}
                if state.get("in_session") is False:
                    session_closed = True
                if state.get("halted"):
                    halted = True
                if d["decision"] == "reject":
                    failed = d["checks"][-1] if d.get("checks") else {}
                    conflicts.append(f"the gate would refuse it — {failed.get('detail') or d.get('spoken_summary')}")
                    blocked = failed.get("id") not in ("portfolio_heat", "max_contracts", "daily_loss")
                    qty = 0
                else:
                    qty = int(d["approved_qty"])
                    binding = d.get("binding_check")
                    worst = d.get("worst_case_loss")
                    if d["decision"] == "resize":
                        conflicts.append(f"sized down by {binding}")

        # Against the book: opening against an open position is refused by the gate.
        root = _root(symbol_id or idea.symbol)
        for pos in getattr(account, "positions", ()) or ():
            if _root(str(pos.symbol)) == root:
                same = (pos.qty > 0) == (idea.direction == "long")
                conflicts.append(
                    f"you already hold {pos.qty:+d} {pos.symbol}" +
                    ("" if same else " — this trades against it; close or flatten first")
                )

        # Scheduled prints inside the idea's horizon.
        horizon = timedelta(days=1 if idea.timeframe in ("scalp", "intraday") else idea.horizon_days)
        window = [
            e for e in upcoming
            if now.isoformat() <= str(e.get("at", "")) <= (now + horizon).isoformat()
        ]
        for e in window[:3]:
            conflicts.append(f"{e.get('country', '')} {e.get('title', 'event')} at {str(e.get('at'))[:16]} UTC — high impact")
        if len(window) > 3:
            conflicts.append(f"…and {len(window) - 3} more high-impact prints inside its horizon")

        # Lessons whose conditions name this symbol or setup.
        keys = {idea.symbol.lower(), root.lower(), idea.setup.lower()} - {""}
        for lesson in lessons:
            when = " ".join(getattr(lesson, "applies_when", ()) or ()).lower()
            if any(k in when for k in keys):
                conflicts.append(f"lesson: {lesson.title}")

        try:
            mark_d = Decimal(mark) if mark is not None else None
        except InvalidOperation:
            mark_d = None
        staged.append({
            "idea_id": idea_id, "idea": idea, "symbol_id": symbol_id, "size": qty,
            "binding": binding, "worst_case": worst, "mark": mark,
            "levels": tuple(_levels(idea, mark_d)), "conflicts": tuple(conflicts),
            "blocked": blocked, "ticket": ticket, "score": _score(idea),
        })

    if halted:
        desk.insert(0, "the kill switch is engaged — nothing can open until you resume")
    if session_closed:
        desk.append("the market is closed now — sizes are what the gate allows once it opens")
    if upcoming:
        nxt = upcoming[0]
        desk.append(f"next high-impact print: {nxt.get('country', '')} {nxt.get('title')} at {str(nxt.get('at'))[:16]} UTC")

    # Actionable first, then by score. Stable, so equal scores keep store order.
    staged.sort(key=lambda s: (s["blocked"] or not s["size"], -s["score"]))
    items = tuple(PlanItem(rank=n, **s) for n, s in enumerate(staged, 1))
    return SessionPlan(
        as_of=now.isoformat(), items=items, desk=tuple(desk), degraded=tuple(degraded),
        sources={
            "ideas": len(ideas), "lessons": len(lessons), "events": len(upcoming),
            "gate": "dry run" if size is not None else "off",
            "account": "live" if account is not None else "none",
        },
    )
