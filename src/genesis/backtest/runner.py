# Spec: Genesis Markdown/20-Agents/Strategy/Agent — Backtest Runner.md
"""Run a :class:`StrategySpec` through Nautilus and normalise what comes back.

The engine is `nautilus_trader` — not a hand-written simulator. That decision
buys three things a from-scratch loop does not have:

- **A venue that fills orders.** Resting stops, gaps, slippage and commission
  are handled by the same simulated matching engine the live path talks to,
  rather than by an `if bar.low <= stop` that cannot represent a gap.
- **Accounting that balances.** Positions, cash, unrealised PnL and the account
  balance history are maintained by the engine, so the equity curve is derived
  from bookkeeping rather than accumulated by the reporter.
- **One statistics implementation.** Sharpe, Sortino, profit factor and
  expectancy come from `nautilus_trader.analysis`, so a backtest and a live
  review can be compared without wondering whether the formulas differ — the
  question `Agent — Backtest Vs Live Drift` exists to answer.

What this module adds is the boundary: Genesis' own symbol ids and bar store on
the way in, and a stable JSON shape on the way out. Nautilus' reports are
pandas DataFrames with thirty-two columns; the UI needs a documented subset
that will not shift under it when the engine version moves.

**Threading.** ``BacktestEngine`` is a stateful Rust object with its own clock
and event loop. One engine is constructed, run, and disposed per request — never
shared, never reused. It is fast enough that pooling would be optimising the
wrong thing, and a shared engine across concurrent requests is a data race with
a plausible-looking equity curve as its symptom.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Sequence

from genesis.backtest.strategy import StrategySpec

log = logging.getLogger(__name__)

__all__ = ["run_spec", "BacktestRun", "BacktestUnavailable", "InsufficientData"]


class BacktestUnavailable(RuntimeError):
    """`nautilus_trader` is not installed.

    Raised rather than degraded to a stub. A "backtest" produced by a fallback
    path is the exact failure `Biological Design` §3 warns about: the surface
    would show numbers, and nobody looking at them would know which engine
    computed them.
    """


class InsufficientData(ValueError):
    """Not enough bars to warm up every series the strategy reads."""


@dataclass
class BacktestRun:
    """One finished run, normalised for the wire."""

    run_id: str
    spec: StrategySpec
    #: Nautilus' three statistic groups, kept separate because that is how the
    #: engine keeps them and flattening loses the distinction between a
    #: currency-denominated figure and a dimensionless ratio.
    stats_pnls: dict[str, dict[str, float | None]] = field(default_factory=dict)
    stats_returns: dict[str, float | None] = field(default_factory=dict)
    stats_general: dict[str, float | None] = field(default_factory=dict)
    #: Account **equity** over time: starting equity compounded by Nautilus'
    #: per-event returns. See :func:`_equity_curve` for why this is not the
    #: account balance.
    equity: list[dict[str, Any]] = field(default_factory=list)
    #: Cash balance over time, from the account report. Kept separately because
    #: for a CASH account it is genuinely different from equity.
    cash: list[dict[str, Any]] = field(default_factory=list)
    #: Per-event returns, ts → value. Nautilus' canonical series.
    returns: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    fills: list[dict[str, Any]] = field(default_factory=list)
    #: Bars the strategy saw, bars it could not decide on, exceptions it hit.
    diagnostics: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "spec": self.spec.to_dict(),
            "stats": {
                "pnls": self.stats_pnls,
                "returns": self.stats_returns,
                "general": self.stats_general,
            },
            "equity": self.equity,
            "cash": self.cash,
            "returns_series": self.returns,
            "positions": self.positions,
            "orders": self.orders,
            "fills": self.fills,
            "diagnostics": self.diagnostics,
            "meta": self.meta,
            "warnings": self.warnings,
        }


def run_spec(spec: StrategySpec, bars: Sequence[Any]) -> BacktestRun:
    """Simulate ``spec`` over ``bars`` and return a normalised run.

    ``bars`` is whatever ``BarStore.read`` returns — Genesis' own ``Bar``
    dataclass, chronological.
    """
    try:
        from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
        from nautilus_trader.model import (
            AccountType, Bar, BarType, Currency, Equity, InstrumentId, Money,
            OmsType, Price, Quantity, Symbol, TraderId, Venue,
        )
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise BacktestUnavailable(
            "nautilus_trader is not installed; run `uv pip install --prerelease=allow "
            "'nautilus_trader==2.0.0rc4'`"
        ) from exc

    if not bars:
        raise InsufficientData(f"no bars held for {spec.symbol_id} {spec.timeframe}")

    warmup = spec.required_warmup
    if len(bars) <= warmup + 2:
        # `Safety Invariants` #2's reasoning, applied to simulation: a 200-bar
        # SMA over 120 bars produces numbers, and they are meaningless numbers
        # that look exactly like a result.
        raise InsufficientData(
            f"{len(bars)} bars is not enough for a strategy needing {warmup} bars "
            "of warm-up; refusing to report numbers from a partial window"
        )

    from genesis.backtest.spec_strategy import SpecStrategy

    venue_name, raw_symbol = _split_symbol(spec.symbol_id)
    venue = Venue(venue_name)
    usd = Currency.from_str("USD")
    instrument_id = InstrumentId(Symbol(raw_symbol), venue)

    precision = _price_precision(bars)
    instrument = Equity(
        instrument_id=instrument_id,
        raw_symbol=Symbol(raw_symbol),
        currency=usd,
        price_precision=precision,
        price_increment=Price(10 ** -precision, precision),
        lot_size=Quantity.from_int(1),
        ts_event=0,
        ts_init=0,
    )

    run_id = uuid.uuid4().hex[:12]
    engine = BacktestEngine(config=BacktestEngineConfig(trader_id=TraderId("GENESIS-001")))
    started = time.monotonic()
    try:
        engine.add_venue(
            venue,
            OmsType.NETTING,
            AccountType.CASH,
            starting_balances=[Money(Decimal(str(spec.starting_equity)), usd)],
        )
        engine.add_instrument(instrument)

        bar_type = BarType.from_str(
            f"{instrument_id}-{_timeframe_spec(spec.timeframe)}-LAST-EXTERNAL"
        )
        engine.add_data([_to_nautilus_bar(Bar, Price, Quantity, bar_type, b, precision)
                         for b in bars])

        strategy = SpecStrategy.create(spec, instrument_id, bar_type)
        engine.add_strategy(strategy)
        engine.run()

        result = engine.get_result()
        run = BacktestRun(run_id=run_id, spec=spec)
        run.stats_pnls = {
            currency: {name: _finite(value) for name, value in stats.items()}
            for currency, stats in (result.stats_pnls or {}).items()
        }
        run.stats_returns = {n: _finite(v) for n, v in (result.stats_returns or {}).items()}
        run.stats_general = {n: _finite(v) for n, v in (result.stats_general or {}).items()}
        run.returns = [
            {"time": int(ts_ns // 1_000_000_000), "value": _finite(value)}
            for ts_ns, value in sorted((result.returns_series or {}).items())
        ]
        run.cash = _account_curve(engine, venue)
        run.equity = _equity_curve(run.returns, spec.starting_equity)
        run.positions = _frame(engine.generate_positions_report(), _POSITION_COLUMNS)
        run.orders = _frame(engine.generate_orders_report(), _ORDER_COLUMNS)
        run.fills = _frame(engine.generate_fills_report(), _FILL_COLUMNS)
        run.diagnostics = strategy.diagnostics

        tier = max((getattr(b, "tier", 9) for b in bars), default=9)
        run.meta = {
            "engine": "nautilus_trader",
            "engine_version": _nautilus_version(),
            "symbol_id": spec.symbol_id,
            "instrument_id": str(instrument_id),
            "timeframe": spec.timeframe,
            "bars": len(bars),
            "first_bar_at": bars[0].ts.isoformat(),
            "last_bar_at": bars[-1].ts.isoformat(),
            "source": getattr(bars[0], "source", "unknown"),
            "tier": tier,
            "total_orders": result.total_orders,
            "total_positions": result.total_positions,
            "total_events": result.total_events,
            "iterations": result.iterations,
            "wall_ms": int((time.monotonic() - started) * 1000),
        }

        run.warnings = _warnings(run, tier, spec)
        return run
    finally:
        # The engine holds a Rust runtime. Disposing is not optional garbage
        # collection -- a leaked engine per request is a leaked thread pool.
        engine.dispose()


# ---------------------------------------------------------------------------
# normalisation
# ---------------------------------------------------------------------------

#: The columns the UI actually renders, from reports that carry thirty-plus.
#: Pinning them here means a Nautilus version bump that adds or reorders
#: columns cannot silently change what the surface shows.
_POSITION_COLUMNS = (
    "instrument_id", "side", "quantity", "peak_qty", "avg_px_open", "avg_px_close",
    "realized_pnl", "realized_return", "ts_opened", "ts_closed", "duration_ns",
    "opening_order_id", "closing_order_id", "commissions",
)
_ORDER_COLUMNS = (
    "instrument_id", "side", "type", "quantity", "filled_qty", "status",
    "time_in_force", "ts_init", "ts_last", "commissions", "venue_order_id",
)
_FILL_COLUMNS = (
    "instrument_id", "order_side", "order_type", "last_qty", "last_px",
    "currency", "liquidity_side", "ts_event", "position_id", "commission",
)


def _frame(df: Any, columns: Sequence[str]) -> list[dict[str, Any]]:
    """A DataFrame to JSON rows, keeping only the pinned columns.

    Everything is stringified rather than coerced to float. These are prices,
    quantities and PnL — money — and `UI Stack §8` keeps money out of IEEE
    doubles all the way to the pixel.
    """
    if df is None or getattr(df, "empty", True):
        return []
    rows: list[dict[str, Any]] = []
    index_name = df.index.name
    for index, record in zip(df.index, df.to_dict("records")):
        row: dict[str, Any] = {}
        if index_name:
            row[index_name] = str(index)
        for column in columns:
            if column not in record:
                continue
            row[column] = _scalar(record[column])
        rows.append(row)
    return rows


def _scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, int):
        return value
    return str(value)


def _account_curve(engine: Any, venue: Any) -> list[dict[str, Any]]:
    """The **cash** balance history, from the account report.

    Named honestly. For a ``CASH`` account this is money not in shares, so it
    *drops* the moment a position opens and recovers when it closes — buying
    100k of stock reads as a 100% loss of cash. It is a real and occasionally
    useful series, and it is not an equity curve.
    """
    try:
        df = engine.generate_account_report(venue)
    except Exception as exc:  # noqa: BLE001
        log.warning("account report unavailable: %s", exc)
        return []
    if df is None or df.empty:
        return []
    out: list[dict[str, Any]] = []
    for ts, record in zip(df.index, df.to_dict("records")):
        try:
            out.append({
                "time": int(ts.timestamp()),
                "ts": ts.isoformat(),
                # Strings, deliberately. The chart parses at the axis.
                "total": str(record.get("total")),
                "free": str(record.get("free")),
                "locked": str(record.get("locked")),
                "currency": str(record.get("currency")),
            })
        except Exception:  # noqa: BLE001
            continue
    return out


def _equity_curve(
    returns: list[dict[str, Any]], starting_equity: float
) -> list[dict[str, Any]]:
    """Account equity: starting equity compounded by Nautilus' returns series.

    **This exists because the account balance is not the equity curve**, and
    plotting it as one was actively misleading. In a ``CASH`` account,
    ``AccountBalance.total`` is cash: it fell from 100,000 to 82,672 the moment
    a position opened and recovered on the close. Drawn as equity, that is a
    24% drawdown the account never experienced — it simply had money in shares.

    `nautilus_trader.analysis.tearsheet` builds its curve the same way::

        cumulative = (1 + returns).cumprod()

    so this is the engine's own definition rather than a reconstruction, and it
    samples per event rather than only on balance changes — 176 points here
    against the account report's 9, which is the difference between a curve and
    a set of line segments.
    """
    if not returns:
        return []
    out: list[dict[str, Any]] = []
    equity = float(starting_equity)
    for point in returns:
        value = point.get("value")
        if value is not None and math.isfinite(float(value)):
            equity *= 1.0 + float(value)
        out.append({
            "time": int(point["time"]),
            # A string, like every other money value on the wire.
            "total": f"{equity:.2f}",
        })
    return out


def _warnings(run: BacktestRun, tier: int, spec: StrategySpec) -> list[str]:
    """Caveats the reader must see, generated rather than remembered.

    Every one of these is a condition under which the numbers above are
    technically correct and practically misleading. They are computed from the
    run so they cannot fall out of date the way a hand-written disclaimer does.
    """
    out: list[str] = []
    errors = run.diagnostics.get("errors") or []
    if errors:
        # First, and loudest. A strategy that raised on every bar produces a
        # clean zero-trade report, and without this the reader concludes the
        # strategy found no signals.
        out.append(
            f"the strategy raised on at least one bar ({errors[0]}) — these results "
            "describe a strategy that partly failed to run"
        )
    positions = len(run.positions)
    if positions == 0:
        out.append(
            "no positions were opened; the statistics below are empty rather than zero"
        )
    elif positions < 30:
        out.append(
            f"{positions} closed positions is below the threshold at which these "
            "statistics are conclusive — treat every ratio as indicative"
        )
    if tier >= 3:
        out.append(
            f"bars are tier {tier}; Market Data Sources reserves tier 1 for venue "
            "data, so fills are indicative"
        )
    undecidable = run.diagnostics.get("undecidable_bars") or 0
    seen = run.diagnostics.get("bars_seen") or 0
    if seen and undecidable / seen > 0.5:
        out.append(
            f"{undecidable} of {seen} bars were undecidable (indicators still warming "
            "up); the strategy was only able to act on part of the window"
        )
    if spec.direction != "long":
        out.append("short side simulated without borrow cost or locate risk")
    return out


# ---------------------------------------------------------------------------
# small conversions
# ---------------------------------------------------------------------------

def _split_symbol(symbol_id: str) -> tuple[str, str]:
    """``EQ:XNAS:AAPL`` → ``("XNAS", "AAPL")``.

    Genesis' canonical ids carry the venue; Nautilus wants it as a separate
    object. A symbol without a venue gets ``SIM``, which is honest — it is a
    simulated venue and the report says so.
    """
    parts = symbol_id.split(":")
    if parts[0] == "FUT" and len(parts) >= 3:
        return parts[1], parts[2]
    if len(parts) >= 3:
        return parts[1], parts[2]
    return "SIM", parts[-1]


def _timeframe_spec(timeframe: str) -> str:
    """``1D`` → ``1-DAY``. Nautilus' bar spec grammar."""
    units = {"m": "MINUTE", "h": "HOUR", "D": "DAY", "W": "WEEK", "d": "DAY"}
    digits = "".join(c for c in timeframe if c.isdigit()) or "1"
    suffix = "".join(c for c in timeframe if not c.isdigit())
    return f"{digits}-{units.get(suffix, units.get(suffix.upper(), 'DAY'))}"


def _price_precision(bars: Sequence[Any]) -> int:
    """Decimal places, taken from the data rather than assumed.

    Hardcoding 2 breaks anything quoted in more — and rounding a price to fewer
    places than the venue quotes silently moves every fill.

    The ``normalize()`` matters. A price that reached the store through float
    arithmetic carries representation noise (``0.23456000000000003``), and its
    raw exponent is 17. Taking the maximum across bars would then let one noisy
    value dictate the precision of the whole instrument, so each value is
    normalised first and anything still implausible is ignored rather than
    allowed to win the max.
    """
    precision = 2
    for bar in bars[:200]:
        for value in (bar.open, bar.high, bar.low, bar.close):
            exponent = -Decimal(str(value)).normalize().as_tuple().exponent
            if not isinstance(exponent, int) or exponent > _MAX_PRICE_PRECISION:
                continue
            precision = max(precision, exponent)
    return precision


#: Beyond this, a quoted price is representation noise rather than a tick size.
#: Nine is already finer than any venue Genesis reads.
_MAX_PRICE_PRECISION = 9


def _to_nautilus_bar(Bar: Any, Price: Any, Quantity: Any, bar_type: Any, bar: Any, precision: int) -> Any:
    ts = int(bar.ts.timestamp() * 1_000_000_000)
    return Bar(
        bar_type,
        Price(float(bar.open), precision),
        Price(float(bar.high), precision),
        Price(float(bar.low), precision),
        Price(float(bar.close), precision),
        Quantity(float(bar.volume), 0),
        ts,
        ts,
    )


def _finite(value: Any) -> float | None:
    """NaN becomes ``None``.

    Nautilus returns NaN for a statistic it could not compute — a Sharpe ratio
    over zero trades, say. ``NaN`` is not valid JSON, and more importantly a UI
    that prints "NaN" in a metric tile is showing a value where there is none.
    ``None`` renders as an em dash, which is the truth.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nautilus_version() -> str:
    try:
        import nautilus_trader

        return str(nautilus_trader.__version__)
    except Exception:  # noqa: BLE001
        return "unknown"
