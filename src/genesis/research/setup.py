# Spec: Genesis Markdown/70-Schemas/Idea Schema.md · 10-Architecture/Charting Engine.md
"""Turning a worded idea into a setup with prices on it.

A news brief says *"long energy on exhausted crude buffers"* and stops there.
That is a direction and a reason, and the risk gate cannot size either of them:
it measures risk from entry to stop, and "a lasting geopolitical resolution" is
not a distance. Idea Schema is blunt about the consequence -- an idea without a
numeric invalidation is shown with **no size**, never a guessed one.

This module computes the missing numbers from bars the system already holds,
with the engine it already has:

* :func:`genesis.charting.structure.read_structure` -- trend, swing sequence,
  ADX, ATR, the range and how contracted it is.
* :func:`genesis.charting.levels.compute_levels` -- every structural level,
  scored, with its distance from spot **in ATR units**.

**ATR is the unit, not percent.** Chart Markup's rule, and the reason is that
2% is a quiet week on one name and two sessions of range on another. A stop
placed in ATR transfers across a mega-cap, an ETF and a futures contract without
meaning something different in each.

**The stop is structural first, volatility second.** A level is where other
people's orders are; an ATR band is where noise ends. So the stop goes beyond
the nearest level *on the wrong side* of the trade, padded by a fraction of ATR
-- and when no such level exists, it falls back to a pure ATR distance and says
so. Which of the two produced it is recorded, because "the stop is below the
September swing low" and "the stop is 1.5 ATR away" are different claims and a
trader should never have to guess which one they are looking at.

**Nothing here decides to trade.** It produces prices for a ticket the gate will
size and a human will approve; it has no opinion about whether the idea is good,
and it cannot place anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["Setup", "compute_setup"]

#: Padding beyond the structural level, in ATR. Small on purpose: the level is
#: doing the work, and this only keeps the stop off the exact price everyone
#: else's stop is sitting on.
LEVEL_PAD_ATR = 0.25
#: The fallback stop distance when no level sits on the wrong side of the trade.
FALLBACK_STOP_ATR = 1.5
#: How far from spot a level may be and still be the stop. Beyond this the
#: trade is not "risking to the level", it is a different trade.
MAX_STOP_ATR = 3.0
#: And a floor, which matters more than the ceiling. The nearest level is often
#: the previous session's high or low, a few tenths of an ATR away -- a stop
#: there is inside the noise, gets hit on an ordinary morning, and (worse) makes
#: the risk distance so small that the gate sizes the maximum position against
#: it. A stop must be far enough away to mean the idea was wrong, not that
#: Tuesday was volatile.
MIN_STOP_ATR = 1.0
#: Price increments, so the numbers this produces are ones the gate will accept.
#:
#: The **broker's `min_tick` is authoritative** and is only known at proposal
#: time, after the contract is qualified. But a stop of 770.8421 is refused for
#: being off the grid rather than for anything that matters, and "the gate
#: rejected your idea" is a terrible way to learn about rounding. So prices are
#: quantised here to the published increment for the instrument class, and the
#: gate remains the thing that decides.
#:
#: US equities and ETFs quote in pennies above $1. The futures are this desk's
#: eight roots, at their CME contract specs.
EQUITY_TICK = 0.01
FUTURES_TICKS: dict[str, float] = {
    "ES": 0.25, "MES": 0.25, "NQ": 0.25, "MNQ": 0.25,
    "RTY": 0.10, "M2K": 0.10, "YM": 1.0, "MYM": 1.0,
}

#: Targets, as multiples of the risk distance. Two, because the first is where
#: a plan usually takes something off and the second is what makes the idea
#: worth taking at all.
TARGET_R = (1.5, 3.0)


@dataclass
class Setup:
    """Prices for one idea, and the evidence behind each of them."""

    symbol: str
    symbol_id: str
    direction: str
    timeframe: str
    spot: float
    atr: float
    entry_low: float
    entry_high: float
    stop: float
    targets: tuple[float, ...]
    #: ``level`` or ``atr`` -- which rule produced the stop.
    stop_basis: str = "atr"
    stop_why: str = ""
    risk_per_unit: float = 0.0
    rr: float | None = None
    trend: str = ""
    swing: str = ""
    adx: float | None = None
    contraction: float | None = None
    volatility_rank: float | None = None
    #: The levels either side of spot, nearest first, as the chart computed them.
    levels: tuple[dict[str, Any], ...] = ()
    bars: int = 0
    source: str = ""
    tier: int | None = None
    as_of: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "symbol_id": self.symbol_id,
            "direction": self.direction, "timeframe": self.timeframe,
            "spot": round(self.spot, 4), "atr": round(self.atr, 4),
            "entry_zone": [round(self.entry_low, 4), round(self.entry_high, 4)],
            "stop": round(self.stop, 4), "targets": [round(t, 4) for t in self.targets],
            "stop_basis": self.stop_basis, "stop_why": self.stop_why,
            "risk_per_unit": round(self.risk_per_unit, 4),
            "rr": None if self.rr is None else round(self.rr, 2),
            "trend": self.trend, "swing": self.swing,
            "adx": self.adx, "contraction": self.contraction,
            "volatility_rank": self.volatility_rank,
            "levels": list(self.levels), "bars": self.bars,
            "source": self.source, "tier": self.tier, "as_of": self.as_of,
            "warnings": list(self.warnings),
        }


def compute_setup(
    symbol: str,
    direction: str,
    *,
    config: Any,
    timeframe: str = "1D",
    consumer: str = "chart_markup",
) -> Setup:
    """Bars in, a priced setup out. Raises `DegradedError` when there are no bars.

    Deterministic and `tier: none` -- no model is consulted here. Two people
    running this on the same bars get the same prices, which is what makes the
    result something a backtest could later be run against.
    """
    from genesis.charting.levels import compute_levels
    from genesis.charting.structure import read_structure
    from genesis.errors import DegradedError
    from genesis.marketdata.build import build_source
    from genesis.marketdata.source import resolve_symbol

    side = "long" if str(direction).lower() != "short" else "short"
    symbol_id = resolve_symbol(symbol)

    built = build_source(config, consumer)
    try:
        bars = built.source.fetch(symbol_id, timeframe)
    finally:
        built.store.close()
        built.budget.close()

    if bars is None or len(bars) < 20:
        raise DegradedError(
            f"only {0 if bars is None else len(bars)} bars for {symbol_id} at "
            f"{timeframe} — not enough to place a stop from structure",
            spoken_summary=f"I don't have enough price history on {symbol} to set levels.",
        )

    tick = _tick_for(symbol_id)
    structure = read_structure(bars)
    computed = compute_levels(bars)
    spot = float(bars.last)
    # The chart's ATR, and **not** `compute_levels`' — that one carries a
    # non-zero floor so level merging has a tolerance to work with, which is a
    # unit for grouping prices, not a distance anyone should risk money to. A
    # borrowed placeholder used as a stop distance is an invented stop.
    atr = float(structure.atr or 0.0)
    warnings: list[str] = []
    if atr <= 0:
        raise DegradedError(
            f"ATR for {symbol_id} came out at zero — a stop cannot be placed from it",
            spoken_summary=f"I can't measure {symbol}'s range, so I won't guess a stop.",
        )

    # Levels either side, nearest first. `distance_atr` is signed: positive
    # above spot, negative below.
    ordered = sorted(computed.levels, key=lambda c: abs(c.distance_atr))
    below = [c for c in ordered if c.distance_atr < 0]
    above = [c for c in ordered if c.distance_atr > 0]

    # The stop sits beyond the nearest level on the side the trade is wrong on.
    wrong_side = below if side == "long" else above
    stop = stop_why = None
    basis = "atr"
    for candidate in wrong_side:
        distance = abs(candidate.distance_atr)
        if distance > MAX_STOP_ATR:
            break
        if distance < MIN_STOP_ATR:
            # Too close to be an invalidation. Keep looking further out rather
            # than accepting it: `wrong_side` is sorted by distance, so the
            # next one is the next real level, not a worse one.
            continue
        pad = LEVEL_PAD_ATR * atr
        stop = candidate.price - pad if side == "long" else candidate.price + pad
        basis = "level"
        stop_why = (
            f"{LEVEL_PAD_ATR:g} ATR {'below' if side == 'long' else 'above'} "
            f"{candidate.label} at {candidate.price:,.2f} ({candidate.why})"
        )
        break

    if stop is None:
        distance = FALLBACK_STOP_ATR * atr
        stop = spot - distance if side == "long" else spot + distance
        stop_why = (
            f"{FALLBACK_STOP_ATR:g} ATR from spot — no level between "
            f"{MIN_STOP_ATR:g} and {MAX_STOP_ATR:g} ATR on the "
            f"{'downside' if side == 'long' else 'upside'}"
        )
        warnings.append(
            "stop is volatility-based: no structural level sat far enough out to be "
            "an invalidation, and a stop inside the noise is not one"
        )

    # The entry zone is spot to a quarter-ATR in the trade's favour of entry:
    # the plan prices the ticket at the zone's far edge, worst case always, so
    # a zone that stretched toward the stop would flatter the size.
    edge = 0.25 * atr
    entry_low, entry_high = (spot - edge, spot) if side == "long" else (spot, spot + edge)

    entry_low, entry_high = _grid(entry_low, tick), _grid(entry_high, tick)
    stop = _grid(stop, tick)
    risk = abs((entry_high if side == "long" else entry_low) - stop)
    if risk <= 0:
        raise DegradedError(
            f"{symbol_id}: entry and stop came out at the same price",
            spoken_summary=f"I couldn't separate entry from stop on {symbol}.",
        )
    targets = tuple(
        _grid((entry_high + m * risk) if side == "long" else (entry_low - m * risk), tick)
        for m in TARGET_R
    )

    if structure.trend == "down" and side == "long":
        warnings.append("the chart's trend is down and this idea is long")
    if structure.trend == "up" and side == "short":
        warnings.append("the chart's trend is up and this idea is short")

    return Setup(
        symbol=symbol.upper(), symbol_id=symbol_id, direction=side, timeframe=timeframe,
        spot=spot, atr=atr, entry_low=entry_low, entry_high=entry_high,
        stop=float(stop), targets=targets, stop_basis=basis, stop_why=stop_why or "",
        risk_per_unit=risk, rr=TARGET_R[-1],
        trend=structure.trend, swing=structure.swing,
        adx=_round(structure.adx), contraction=_round(structure.contraction),
        volatility_rank=_round(structure.volatility_pct_rank),
        levels=tuple(
            {"price": round(c.price, 4), "label": c.label, "type": c.type,
             "why": c.why, "distance_atr": round(c.distance_atr, 2),
             "side": c.side, "strength": round(c.strength, 3)}
            for c in ordered[:8]
        ),
        bars=len(bars), source=getattr(bars, "source", ""), tier=getattr(bars, "tier", None),
        as_of=computed.as_of.isoformat() if getattr(computed, "as_of", None) else "",
        warnings=tuple(warnings),
    )


def _tick_for(symbol_id: str) -> float:
    """The price increment for this instrument, from its class."""
    if symbol_id.upper().startswith("FUT:"):
        parts = symbol_id.split(":")
        return FUTURES_TICKS.get(parts[2].upper() if len(parts) > 2 else "", 0.25)
    return EQUITY_TICK


def _grid(price: float, tick: float) -> float:
    """The nearest price on the tick grid, without float dust.

    `round(770.8421 / 0.01) * 0.01` is 770.8400000000001 in binary floating
    point, which is off the grid again — so the rounding is done in Decimal and
    handed back as a float the JSON encoder will print cleanly.
    """
    from decimal import Decimal

    step = Decimal(str(tick))
    return float((Decimal(str(price)) / step).quantize(Decimal(1)) * step)


def _round(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else round(number, 3)  # NaN check
