# Spec: Genesis Markdown/20-Agents/Journal/Agent — Trade Journal.md
"""Agent — Trade Journal. Every fill becomes a note, with the work already done.

The note's premise is a claim about *when*, not about *what*:

> Manual journaling fails because it asks for effort at the worst moment. This
> agent removes the effort and leaves only the reflection.

So the entry is complete at the moment the trade closes. Prices, R multiple,
MAE/MFE, duration, charts, the thesis, and plan adherence are all filled in
before anyone is asked anything, and the human half is offered once, later, and
is entirely skippable. An entry with zero human input is still a good entry --
that is the design, not a fallback.

Three things this agent computes rather than asks:

**Plan adherence.** Compared from the ledger against the plan. Trade Journal
Schema is explicit that ``stop_moved`` in particular must never be
self-reported, because self-reporting on that behaviour is unreliable in a way
that is entirely human and entirely predictable.

**The R multiple.** From the planned stop, not from the dollar result. Without a
planned stop there is no risk unit and ``r_multiple`` is ``None`` -- not zero,
because a trade whose R cannot be computed is not a breakeven trade, and the
metrics layer drops ``None`` for exactly that reason.

**The entry chart, as it was.** Re-rendered from the markup spec that existed at
entry, not recomputed from today's bars. The spec is immutable, so the chart in
the note is provably the analysis the trade was taken on rather than a
reconstruction of what we would say about that date now.

The thesis is copied verbatim and never re-summarised. Six months later you need
to read what you believed at the time; memory reliably rewrites the thesis of a
losing trade into something more reasonable than it was.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Sequence

from genesis.agents.base import Agent, AgentDeclaration, TaskFailure, TaskResult
from genesis.errors import DegradedError, FatalError
from genesis.journal.schema import JournalEntry, Observation, PlanAdherence
from genesis.journal.store import JournalStore
from genesis.observability import Console

__all__ = ["DECLARATION", "TradeJournalAgent", "build_entry"]

DECLARATION = AgentDeclaration(
    id="trade-journal",
    name="Trade Journal",
    family="journal",
    cadence=[
        # On the fills themselves, so the note exists before anyone thinks about
        # writing one -- which is the entire point.
        {"type": "event", "on": ["fill.entry", "fill.partial", "fill.exit"]},
        # And once after the close, to offer the reflective half.
        {"type": "cron", "at": "16:15"},
    ],
    tools=["genesis-charting.render", "obsidian.write"],
    memory={
        "read": ["shared", "ledger", "idea-synthesizer", "chart-markup", "execution-quality"],
        "write": ["trade-journal"],
    },
    # Formatting and transcription, not reasoning.
    model_tier="small",
    vision=False,
    timeout_sec=60,
    max_concurrent=2,
)


class TradeJournalAgent(Agent):
    """Fill in, note out. Plus the once-a-day reflection prompt."""

    def __init__(
        self,
        store: JournalStore,
        *,
        ledger: Any = None,
        specs: Any = None,
        vault: Any = None,
        console: Console | None = None,
    ) -> None:
        super().__init__(DECLARATION)
        self.store = store
        self.ledger = ledger
        self.specs = specs
        self.vault = vault
        self.console = console or Console(enabled=False)

    def execute(self, task: Any) -> TaskResult | TaskFailure:
        task_type = str(getattr(task, "type", "") or "")
        args = dict(getattr(task, "args", {}) or {})
        if task_type.endswith(".prompt") or args.get("prompt"):
            return self._prompt_round(task)
        return self._record(task, args)

    # -- recording ---------------------------------------------------------

    def _record(self, task: Any, args: dict[str, Any]) -> TaskResult | TaskFailure:
        trade = args.get("trade")
        if not isinstance(trade, dict):
            raise FatalError(
                "journal.record needs a `trade` object",
                spoken_summary="I couldn't journal that — the trade record was missing.",
            )
        entry = build_entry(trade, trace_id=getattr(task, "trace_id", "") or None)
        self.store.put_entry(entry)

        # The trade is also an observation, so the Insight Miner's wide net sees
        # it alongside level outcomes and idea outcomes rather than having to
        # special-case the journal.
        self.store.record(
            Observation(
                kind="trade.closed",
                subject=f"{entry.symbol}:{entry.setup or 'unclassified'}",
                outcome="win" if entry.is_winner else "loss",
                value=entry.r_multiple,
                unit="R",
                source=entry.strategy or "manual",
                trace_id=entry.trace_id,
                detail={
                    "entry_id": entry.id,
                    "stop_moved": entry.plan_adherence.stop_moved,
                    "plan_followed": entry.plan_adherence.followed,
                    "session": entry.session_segment,
                    "regime": entry.regime,
                },
            )
        )

        path = self._write_note(entry)
        wrote: list[dict[str, Any]] = [
            {"layer": "memory", "namespace": "trade-journal", "entry": entry.id}
        ]
        if path:
            wrote.append({"layer": "vault", "path": path})

        return TaskResult(
            task_id=getattr(task, "id", "<none>"),
            agent=self.id,
            data={
                "entry_id": entry.id,
                "symbol": entry.symbol,
                "r_multiple": entry.r_multiple,
                "plan_followed": entry.plan_adherence.followed,
                "deviations": list(entry.plan_adherence.deviations),
                "note_path": path,
            },
            wrote=tuple(wrote),
            spoken_summary=_spoken(entry),
            cost={"tool_calls": 1},
        )

    # -- the once-a-day prompt --------------------------------------------

    def _prompt_round(self, task: Any) -> TaskResult:
        """Offer the reflective half for anything closed and never asked about.

        Marks every entry prompted whether or not anything is said. Trade
        Journal.md: *"Skippable — a partial journal entry is better than none,
        and nagging produces resentment, not insight."* Marking on the ask
        rather than on the answer is what makes "once" literal.
        """
        pending = self.store.unprompted(before=datetime.now(UTC))
        answers = dict(getattr(task, "args", {}).get("answers") or {})

        prompted: list[str] = []
        for entry in pending:
            fields = answers.get(entry.id) or {}
            self.store.patch_human(entry.id, **fields)
            prompted.append(entry.id)

        return TaskResult(
            task_id=getattr(task, "id", "<none>"),
            agent=self.id,
            data={"prompted": prompted, "count": len(prompted)},
            wrote=tuple(
                {"layer": "memory", "namespace": "trade-journal", "entry": entry_id}
                for entry_id in prompted
            ),
            spoken_summary=_prompt_sentence(pending),
            cost={"tool_calls": 0},
        )

    # -- the vault note ----------------------------------------------------

    def _write_note(self, entry: JournalEntry) -> str | None:
        """Best-effort. A vault that is not mounted must not lose a journal entry.

        The entry is already durable in the store by the time this runs, and the
        note is regenerable from it — so a filesystem problem costs a file, not
        a record.
        """
        if self.vault is None:
            return None
        try:
            return self.vault.write_journal(entry)
        except Exception as exc:  # noqa: BLE001 - never lose an entry over a note
            self.console.warn(f"trade-journal could not write the vault note: {exc}")
            return None


# --------------------------------------------------------------------------
# Building an entry
# --------------------------------------------------------------------------


def build_entry(trade: dict[str, Any], *, trace_id: str | None = None) -> JournalEntry:
    """A closed trade as a journal entry, with everything computable computed."""
    entry_ts = _time(trade["entry_ts"])
    exit_ts = _time(trade["exit_ts"])
    entry_price = float(trade["entry_price"])
    exit_price = float(trade["exit_price"])
    direction = str(trade.get("direction", "long")).lower()
    qty = int(trade.get("qty", 0) or 0)
    planned_stop = _optional_float(trade.get("planned_stop"))

    r_multiple = _r_multiple(entry_price, exit_price, planned_stop, direction)
    adherence = _adherence(trade, direction)

    return JournalEntry(
        trace_id=trace_id or trade.get("trace_id"),
        symbol=str(trade["symbol"]),
        direction="short" if direction == "short" else "long",
        account=str(trade.get("account", "primary")),
        strategy=trade.get("strategy"),
        setup=trade.get("setup"),
        idea=trade.get("idea"),
        entry_price=entry_price,
        entry_ts=entry_ts,
        exit_price=exit_price,
        exit_ts=exit_ts,
        qty=qty,
        exit_reason=str(trade.get("exit_reason", "manual")),
        duration_min=round((exit_ts - entry_ts).total_seconds() / 60.0, 2),
        bars_held=int(trade.get("bars_held", 0) or 0),
        planned_stop=planned_stop,
        planned_target=_optional_float(trade.get("planned_target")),
        planned_rr=_optional_float(trade.get("planned_rr")),
        risk_dollars=_optional_float(trade.get("risk_dollars")),
        pnl_gross=float(trade.get("pnl_gross", 0.0) or 0.0),
        fees=float(trade.get("fees", 0.0) or 0.0),
        pnl_net=float(trade.get("pnl_net", 0.0) or 0.0),
        r_multiple=r_multiple,
        mae_r=_optional_float(trade.get("mae_r")),
        mfe_r=_optional_float(trade.get("mfe_r")),
        portfolio_heat_at_entry=_optional_float(trade.get("portfolio_heat_at_entry")),
        regime=trade.get("regime"),
        session_segment=trade.get("session_segment") or _session_of(entry_ts),
        day_of_week=trade.get("day_of_week") or entry_ts.strftime("%A").lower(),
        markup_entry=trade.get("markup_entry"),
        markup_exit=trade.get("markup_exit"),
        chart_entry=trade.get("chart_entry"),
        chart_exit=trade.get("chart_exit"),
        slippage_bps=_optional_float(trade.get("slippage_bps")),
        fills=tuple(trade.get("fills") or ()),
        # Verbatim. Never re-summarised, never tidied.
        thesis=str(trade.get("thesis", "") or ""),
        plan_adherence=adherence,
        tags=tuple(trade.get("tags") or ()),
    )


def _r_multiple(
    entry: float, exit_price: float, stop: float | None, direction: str
) -> float | None:
    """Result in units of the risk actually taken.

    ``None`` without a planned stop, and that is load-bearing: there is no risk
    unit, so there is no R. Substituting zero would say "this trade was
    breakeven", which is a different and false claim, and it would drag every
    expectancy toward zero in proportion to how sloppy the record-keeping was.
    """
    if stop is None:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    move = (exit_price - entry) if direction != "short" else (entry - exit_price)
    return round(move / risk, 3)


def _adherence(trade: dict[str, Any], direction: str) -> PlanAdherence:
    """Plan versus execution, computed. ``stop_moved`` means moved *against*.

    Direction matters and is the whole signal: tightening a stop in your favour
    is discipline, widening it against yourself is the behaviour the Insight
    Miner is looking for. A plain "was the stop changed" boolean would score
    both identically and be worth nothing.
    """
    raw = dict(trade.get("plan_adherence") or {})
    planned_stop = _optional_float(trade.get("planned_stop"))
    final_stop = _optional_float(trade.get("final_stop"))

    moved_against = bool(raw.get("stop_moved", False))
    if planned_stop is not None and final_stop is not None:
        moved_against = (
            final_stop < planned_stop if direction != "short" else final_stop > planned_stop
        )

    deviations = list(raw.get("deviations") or ())
    if moved_against and not any("stop" in d.lower() for d in deviations):
        deviations.append(
            f"Stop moved against the position: planned {planned_stop}, final {final_stop}"
        )

    planned_size = trade.get("planned_qty")
    size_as_planned = raw.get("size_as_planned")
    if size_as_planned is None and planned_size:
        size_as_planned = int(planned_size) == int(trade.get("qty", 0) or 0)

    exit_as_planned = raw.get("exit_as_planned")
    target = _optional_float(trade.get("planned_target"))
    if exit_as_planned is None and target is not None:
        reason = str(trade.get("exit_reason", "")).lower()
        exit_as_planned = reason in ("target", "stop", "invalidation")
        if not exit_as_planned and reason == "manual":
            deviations.append(
                f"Exited manually at {trade.get('exit_price')} against a target of {target}"
            )

    return PlanAdherence(
        entry_in_zone=raw.get("entry_in_zone"),
        size_as_planned=size_as_planned,
        stop_as_planned=raw.get("stop_as_planned", not moved_against),
        stop_moved=moved_against,
        exit_as_planned=exit_as_planned,
        deviations=tuple(deviations),
    )


def _session_of(when: datetime) -> str:
    """A coarse session bucket, so time-of-day analysis has a dimension to slice.

    Deliberately coarse. Finer buckets slice a small sample into smaller ones
    until something looks significant, which is the exact failure the analyst's
    sample-size discipline exists to prevent.
    """
    minutes = when.hour * 60 + when.minute
    for start, end, label in (
        (13 * 60 + 30, 14 * 60, "open-30"),
        (14 * 60, 18 * 60, "midday"),
        (18 * 60, 19 * 60 + 30, "power-hour"),
    ):
        if start <= minutes < end:
            return label
    return "extended"


def _spoken(entry: JournalEntry) -> str:
    result = (
        f"{entry.r_multiple:+.2f}R" if entry.r_multiple is not None
        else f"{entry.pnl_net:+,.2f}"
    )
    line = f"{entry.symbol} journaled, {result}."
    if entry.plan_adherence.deviations:
        # Volunteer the uncomfortable thing. A journal that only reports the
        # number is a diary.
        line += f" {entry.plan_adherence.deviations[0]}"
    return line


def _prompt_sentence(pending: Sequence[JournalEntry]) -> str | None:
    if not pending:
        return None
    if len(pending) == 1:
        entry = pending[0]
        return (
            f"One trade to reflect on: {entry.symbol}, "
            f"{entry.r_multiple:+.2f}R." if entry.r_multiple is not None
            else f"One trade to reflect on: {entry.symbol}."
        )
    return f"{len(pending)} trades to reflect on when you have a moment."


def _time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
