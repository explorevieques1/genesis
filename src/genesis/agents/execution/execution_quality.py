# Spec: Genesis Markdown/20-Agents/Execution/Agent — Execution Quality.md
"""Agent — Execution Quality. Did we get a fair fill? Measurement, no model.

Sign convention, fixed once here because a sign error in slippage is easy and
silent: **positive slippage is adverse**. A buy filled above the arrival mid,
or a sell filled below it, is positive. ``adverse_selection_30s_bps`` follows
the spec's own convention: negative means price went our way after the fill.

**A delayed arrival quote is not a benchmark.** On IBKR's free delayed feed the
"mid at proposal time" is ten to fifteen minutes old, and slippage against it
measures the delay, not the fill. Those fills are recorded with every number
the agent can honestly compute, and the verdict ``unmeasured`` -- never a
``pathological`` that is really just a stale quote.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from genesis.agents.base import AgentDeclaration

__all__ = ["DECLARATION", "FillQuality", "QualityStore", "daily_aggregate", "measure_fill", "verdict"]

DECLARATION = AgentDeclaration(
    id="execution-quality",
    name="Execution Quality",
    family="execution",
    cadence=[{"type": "event", "on": ["order.filled"]}, {"type": "cron", "at": "16:15"}],
    tools=["memory.read", "market-data.quote_history"],
    memory={"read": ["ledger", "order-manager"], "write": ["execution-quality"]},
    model_tier="none",
    timeout_sec=10,
)

BPS = Decimal(10_000)


@dataclass(frozen=True)
class FillQuality:
    fill_id: str
    order: str
    symbol: str
    side: str
    qty: int
    fill_price: str
    arrival_mid: str | None
    arrival_source: str | None
    order_type: str
    arrival_bps: str | None
    slippage_dollars: str | None
    spread_at_arrival_bps: str | None
    time_to_fill_ms: int | None
    fees: str
    adverse_selection_30s_bps: str | None
    verdict: str
    why: str
    ts: str


def _sign(side: str) -> int:
    return 1 if side == "buy" else -1


def verdict(arrival_bps: Decimal | None, spread_bps: Decimal | None, source: str | None) -> tuple[str, str]:
    """good | normal | poor | pathological | unmeasured, with the reason."""
    if arrival_bps is None:
        return "unmeasured", "no arrival quote was stamped"
    # "trigger": a stop measured against its own stop price, which is exact
    # whatever the quote feed is.
    if source not in ("realtime", "trigger"):
        return "unmeasured", f"arrival quote was {source or 'unknown'} data — slippage against it measures the delay"
    spread = spread_bps if spread_bps is not None and spread_bps > 0 else Decimal(1)
    if arrival_bps <= 0:
        return "good", f"{arrival_bps:.1f} bps — filled at or better than the arrival mid"
    if arrival_bps <= max(2 * spread, Decimal(2)):
        return "normal", f"{arrival_bps:.1f} bps on a {spread:.1f} bps spread"
    if arrival_bps <= max(6 * spread, Decimal(10)):
        return "poor", f"{arrival_bps:.1f} bps is several spreads wide ({spread:.1f} bps)"
    return "pathological", f"{arrival_bps:.1f} bps against a {spread:.1f} bps spread"


def measure_fill(*, fill_id: str, order: str, symbol: str, side: str, qty: int, fill_price: Decimal,
                 multiplier: Decimal, fees: Decimal, order_type: str, ts: str,
                 arrival_mid: Decimal | None, arrival_bid: Decimal | None, arrival_ask: Decimal | None,
                 arrival_source: str | None, time_to_fill_ms: int | None,
                 mid_30s_after: Decimal | None = None) -> FillQuality:
    s = _sign(side)
    arrival_bps = dollars = spread_bps = adverse = None
    if arrival_mid is not None and arrival_mid > 0:
        arrival_bps = (fill_price - arrival_mid) / arrival_mid * BPS * s
        dollars = (fill_price - arrival_mid) * s * qty * multiplier
        if arrival_bid is not None and arrival_ask is not None and arrival_ask >= arrival_bid:
            spread_bps = (arrival_ask - arrival_bid) / arrival_mid * BPS
    if mid_30s_after is not None and fill_price > 0:
        adverse = (fill_price - mid_30s_after) / fill_price * BPS * s
    v, why = verdict(arrival_bps, spread_bps, arrival_source)
    q = lambda d, places="0.01": None if d is None else str(d.quantize(Decimal(places)))  # noqa: E731
    return FillQuality(
        fill_id=fill_id, order=order, symbol=symbol, side=side, qty=qty, fill_price=str(fill_price),
        arrival_mid=None if arrival_mid is None else str(arrival_mid), arrival_source=arrival_source,
        order_type=order_type, arrival_bps=q(arrival_bps), slippage_dollars=q(dollars),
        spread_at_arrival_bps=q(spread_bps), time_to_fill_ms=time_to_fill_ms, fees=str(fees),
        adverse_selection_30s_bps=q(adverse), verdict=v, why=why, ts=ts,
    )


def daily_aggregate(date: str, fills: list[FillQuality], *, limit_orders_placed: int,
                    limit_orders_filled: int) -> dict[str, Any]:
    """The day, for Performance Analyst and the backtest cost model.

    Only ``realtime``-benchmarked fills feed the slippage numbers; the rest are
    counted so the gap is visible rather than averaged in.
    """
    measured = [f for f in fills if f.verdict != "unmeasured" and f.arrival_bps is not None]
    bps = [Decimal(f.arrival_bps) for f in measured]  # type: ignore[arg-type]
    worst = max(measured, key=lambda f: Decimal(f.arrival_bps), default=None)  # type: ignore[arg-type]
    total_fees = sum((Decimal(f.fees) for f in fills), Decimal(0))
    contracts = sum(f.qty for f in fills)
    return {
        "date": date,
        "fills": len(fills),
        "measured_fills": len(measured),
        "unmeasured_fills": len(fills) - len(measured),
        "avg_arrival_slippage_bps": str((sum(bps) / len(bps)).quantize(Decimal("0.01"))) if bps else None,
        "median_arrival_slippage_bps": str(Decimal(statistics.median(bps)).quantize(Decimal("0.01"))) if bps else None,
        "worst": None if worst is None else {"symbol": worst.symbol, "bps": worst.arrival_bps, "why": worst.why},
        "limit_fill_rate": (round(limit_orders_filled / limit_orders_placed, 3) if limit_orders_placed else None),
        "total_fees": str(total_fees),
        "fees_per_contract": str((total_fees / contracts).quantize(Decimal("0.01"))) if contracts else None,
        "recommended_cost_model": {
            "slippage_bps": str(Decimal(statistics.median(bps)).quantize(Decimal("0.1"))) if bps else None,
            "commission_per_contract": str((total_fees / contracts).quantize(Decimal("0.01"))) if contracts else None,
        },
        "note": None if bps else "no fill had a realtime arrival quote — slippage is unmeasured, not zero",
    }


class QualityStore:
    """``execution-quality`` namespace. One row per fill; rewritten when the
    30-second adverse-selection sample lands."""

    def __init__(self, path: Path | str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS fill_quality (fill_id TEXT PRIMARY KEY, "
                           "ts TEXT NOT NULL, doc TEXT NOT NULL)")
        self._conn.commit()

    def put(self, fq: FillQuality) -> None:
        self._conn.execute("INSERT OR REPLACE INTO fill_quality VALUES (?,?,?)",
                           (fq.fill_id, fq.ts, json.dumps(asdict(fq))))
        self._conn.commit()

    def get(self, fill_id: str) -> FillQuality | None:
        row = self._conn.execute("SELECT doc FROM fill_quality WHERE fill_id = ?", (fill_id,)).fetchone()
        return FillQuality(**json.loads(row[0])) if row else None

    def on(self, date: str) -> list[FillQuality]:
        return [FillQuality(**json.loads(r[0])) for r in self._conn.execute(
            "SELECT doc FROM fill_quality WHERE ts LIKE ? ORDER BY ts", (f"{date}%",))]

    def recent(self, limit: int = 50) -> list[FillQuality]:
        return [FillQuality(**json.loads(r[0])) for r in self._conn.execute(
            "SELECT doc FROM fill_quality ORDER BY ts DESC LIMIT ?", (limit,))]
