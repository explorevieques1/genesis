# Spec: Genesis Markdown/20-Agents/Charting/Agent — Pattern Recognition.md
"""The skeptic. Deterministic structure, computed so a vision model can be checked.

Agent — Pattern Recognition's design rests on one asymmetry: *"a vision model
asked 'is there a pattern here?' will always find one. The rules engine is the
skeptic."* This module is the rules engine. It measures what is measurable --
swing sequence, trend, range boundaries, volatility contraction, and a small set
of patterns with unambiguous definitions -- and refuses to guess at anything
else.

Two design choices follow from being the skeptic rather than the seer:

**It is allowed to find nothing, and usually does.** ``patterns`` comes back
empty on most charts, because most charts are not textbook patterns. An
implementation tuned to always produce something would defeat the whole
arrangement -- there would be no independent opinion left to disagree with the
vision model.

**Every pattern carries its measurement, not just its name.** A ``bull_flag``
here is *"consolidation of 0.7 ATR over 9 bars on volume 0.6x the impulse,
following a 3.2 ATR advance"*. The note's instruction to the model is the same:
*"'Bull flag' is a label; 'tight consolidation on declining volume after a 12%
impulse' is information."* The numbers are what the model is cross-checked
against, so the numbers are what get returned.

Nothing here is a probability. ``confidence`` on a rules pattern is how well the
shape fits its own definition, and the agent is responsible for not presenting
that as a forecast.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from genesis.charting import indicators as ind
from genesis.charting.bars import Bars

__all__ = ["RulesPattern", "StructureRead", "read_structure"]

#: ADX below this is not a trend, whatever the eye says. The conventional
#: threshold, and conventional is the right choice for a value whose job is to
#: be a check on somebody else's opinion.
TRENDING_ADX = 22.0


@dataclass(frozen=True)
class RulesPattern:
    """A pattern the deterministic engine will vouch for, with its measurements."""

    name: str
    confidence: float
    why: str
    from_index: int
    to_index: int
    measures: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class StructureRead:
    """Everything measurable about this chart's shape."""

    trend: str  # up | down | range
    swing: str  # HH-HL | LH-LL | mixed | range
    trend_strength: float
    adx: float
    atr: float
    range_high: float
    range_low: float
    #: Recent range as a fraction of its own prior range. Below ~0.6 is a
    #: squeeze; this is the measurement behind "volatility contraction".
    contraction: float
    volatility_pct_rank: float
    swing_points: tuple[tuple[int, float, str], ...]
    patterns: tuple[RulesPattern, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "trend": self.trend,
            "swing": self.swing,
            "trend_strength": round(self.trend_strength, 3),
            "adx": round(self.adx, 2) if np.isfinite(self.adx) else None,
            "atr14": round(self.atr, 4),
            "range_high": round(self.range_high, 4),
            "range_low": round(self.range_low, 4),
            "contraction": round(self.contraction, 3),
            "volatility_pct_rank": (
                round(self.volatility_pct_rank, 3)
                if np.isfinite(self.volatility_pct_rank)
                else None
            ),
            "patterns": [
                {
                    "name": p.name,
                    "confidence": round(p.confidence, 2),
                    "why": p.why,
                    "measures": {k: round(v, 3) for k, v in p.measures.items()},
                }
                for p in self.patterns
            ],
        }

    def summary(self) -> str:
        """One line for a prompt. What the vision model is handed alongside the image."""
        found = ", ".join(p.name for p in self.patterns) or "no rules pattern"
        return (
            f"trend={self.trend} swing={self.swing} adx={self.adx:.0f} "
            f"contraction={self.contraction:.2f} rules: {found}"
        )


def read_structure(bars: Bars, *, swing_k: int = 3) -> StructureRead:
    pivots = ind.swings(bars, swing_k)
    adx_value = ind.adx(bars)
    strength = ind.trend_strength(bars)
    atr = ind.last_atr(bars)
    swing = _swing_sequence(pivots)
    trend = _trend(bars, adx_value, swing)
    window = bars.close[-60:] if len(bars) > 60 else bars.close
    contraction = _contraction(bars)

    return StructureRead(
        trend=trend,
        swing=swing,
        trend_strength=0.0 if np.isnan(strength) else strength,
        adx=adx_value,
        atr=atr,
        range_high=float(bars.high[-60:].max()) if len(bars) else float("nan"),
        range_low=float(bars.low[-60:].min()) if len(bars) else float("nan"),
        contraction=contraction,
        volatility_pct_rank=ind.volatility_percentile(bars),
        swing_points=tuple((p.index, p.price, p.kind) for p in pivots),
        patterns=tuple(_patterns(bars, pivots, atr, trend, contraction)),
    )


#: Pivots the swing sequence is read over. Three, not two.
#:
#: Two was the obvious choice and it is wrong in a way that only shows up on
#: real shapes: a single upward swing at the very end of a 40% decline makes the
#: last *adjacent* pair of highs ascending, and the sequence reads HH-HL on a
#: chart that has fallen all year. Three pivots compared first-to-last survives
#: one counter-swing while still describing the present rather than the window.
_SEQUENCE_PIVOTS = 3


def _swing_sequence(pivots: list[ind.Swing]) -> str:
    """HH-HL, LH-LL, mixed, or range — from the last three highs and three lows.

    Not more than three: a sequence read over ten pivots describes the whole
    window and answers the wrong question. What a trader means by "higher highs
    and higher lows" is *is it still doing that now*.
    """
    highs = [p.price for p in pivots if p.kind == "high"][-_SEQUENCE_PIVOTS:]
    lows = [p.price for p in pivots if p.kind == "low"][-_SEQUENCE_PIVOTS:]
    if len(highs) < 2 or len(lows) < 2:
        return "range"
    higher_high, higher_low = highs[-1] > highs[0], lows[-1] > lows[0]
    if higher_high and higher_low:
        return "HH-HL"
    if not higher_high and not higher_low:
        return "LH-LL"
    return "mixed"


def _trend(bars: Bars, adx_value: float, swing: str) -> str:
    """Trend needs three independent measures to agree: ADX, swings, and location.

    Requiring agreement is the same discipline the agent applies to
    vision-versus-rules, one level down. Each measure alone is wrong in its own
    characteristic way -- ADX calls a violent range a trend, the swing sequence
    calls a counter-swing a reversal, and price-versus-average calls a stalled
    drift a trend -- so a claim needs all three, and when they disagree the
    honest answer is ``range``.

    The third check is the one that stops the specific failure of the other two:
    price above its own 50-period average is not an opinion, and no arrangement
    of recent pivots makes a chart trading 40% below it an uptrend.
    """
    if not np.isfinite(adx_value) or adx_value < TRENDING_ADX:
        return "range"
    if swing not in ("HH-HL", "LH-LL"):
        return "range"

    wanted = "up" if swing == "HH-HL" else "down"
    average = ind.sma(bars.close, min(50, max(len(bars) // 4, 5)))
    if len(average) and np.isfinite(average[-1]):
        located = "up" if bars.close[-1] >= average[-1] else "down"
        if located != wanted:
            return "range"
    return wanted


def _contraction(bars: Bars, recent: int = 10, prior: int = 30) -> float:
    """Recent true range against its prior baseline.

    Below 0.6 is a real squeeze and is the precondition for every consolidation
    pattern below. Above 1.4 is expansion. Returns 1.0 (i.e. "no information")
    rather than NaN on a short window, so callers do not each need a NaN branch.
    """
    if len(bars) < recent + prior:
        return 1.0
    tr = ind.true_range(bars)
    baseline = float(tr[-(recent + prior) : -recent].mean())
    if baseline <= 0:
        return 1.0
    return float(tr[-recent:].mean() / baseline)


# --------------------------------------------------------------------------
# Patterns the engine will actually vouch for
# --------------------------------------------------------------------------


def _patterns(
    bars: Bars, pivots: list[ind.Swing], atr: float, trend: str, contraction: float
) -> list[RulesPattern]:
    """The short list. Each has a definition a second implementation would match.

    Deliberately short. Every pattern added here is one the vision model can be
    contradicted about; a pattern with a fuzzy definition contradicts nothing
    and only adds a name that sounds authoritative.
    """
    found: list[RulesPattern] = []
    for detect in (_flag, _double, _sweep, _squeeze, _inside_range):
        pattern = detect(bars, pivots, atr, trend, contraction)
        if pattern is not None:
            found.append(pattern)
    return found


def _flag(bars, pivots, atr, trend, contraction) -> RulesPattern | None:
    """Impulse, then tight consolidation on lighter volume, in the trend's direction."""
    if len(bars) < 30 or atr <= 0 or trend == "range":
        return None
    consolidation, impulse = bars.close[-10:], bars.close[-25:-10]
    if len(impulse) < 5:
        return None
    impulse_move = (impulse[-1] - impulse[0]) / atr
    if trend == "up" and impulse_move < 2.0:
        return None
    if trend == "down" and impulse_move > -2.0:
        return None
    span = (consolidation.max() - consolidation.min()) / atr
    if span > 1.5 or contraction > 0.9:
        return None
    volume_ratio = (
        float(bars.volume[-10:].mean() / bars.volume[-25:-10].mean())
        if float(bars.volume[-25:-10].mean()) > 0
        else 1.0
    )
    name = "bull_flag" if trend == "up" else "bear_flag"
    confidence = min(0.4 + (1.5 - span) * 0.3 + max(0.0, 1.0 - volume_ratio) * 0.3, 0.9)
    return RulesPattern(
        name=name,
        confidence=round(confidence, 2),
        why=(
            f"{abs(impulse_move):.1f} ATR impulse then {span:.1f} ATR consolidation "
            f"over 10 bars on {volume_ratio:.1f}x the impulse's volume"
        ),
        from_index=len(bars) - 25,
        to_index=len(bars) - 1,
        measures={
            "impulse_atr": abs(impulse_move),
            "consolidation_atr": span,
            "volume_ratio": volume_ratio,
        },
    )


def _double(bars, pivots, atr, trend, contraction) -> RulesPattern | None:
    """Two swings at the same price with a meaningful reaction between them."""
    if atr <= 0:
        return None
    for kind, name in (("high", "double_top"), ("low", "double_bottom")):
        points = [p for p in pivots if p.kind == kind][-2:]
        if len(points) < 2:
            continue
        gap = abs(points[1].price - points[0].price) / atr
        separation = points[1].index - points[0].index
        if gap > 0.25 or separation < 8:
            continue
        # A "double top" halfway up a range is two swings that happened to
        # match. The pattern means something only at the window's extreme —
        # that is what makes it a level the whole chart is failing against.
        extreme = float(bars.high.max() if kind == "high" else bars.low.min())
        if abs(max(p.price for p in points) - extreme) / atr > 0.5 and kind == "high":
            continue
        if abs(min(p.price for p in points) - extreme) / atr > 0.5 and kind == "low":
            continue
        between = bars.close[points[0].index : points[1].index]
        if len(between) == 0:
            continue
        retrace = abs(float(between.min() if kind == "high" else between.max()) - points[0].price) / atr
        if retrace < 2.0:
            continue
        return RulesPattern(
            name=name,
            confidence=round(min(0.45 + (0.25 - gap) + retrace * 0.05, 0.85), 2),
            why=(
                f"two swing {kind}s {gap:.2f} ATR apart, {separation} bars apart, "
                f"with a {retrace:.1f} ATR reaction between them"
            ),
            from_index=points[0].index,
            to_index=points[1].index,
            measures={"gap_atr": gap, "retrace_atr": retrace, "bars_apart": float(separation)},
        )
    return None


def _sweep(bars, pivots, atr, trend, contraction) -> RulesPattern | None:
    """A wick through a prior swing that closed back inside within two bars.

    The distinction Agent — Level Watcher is built around, applied to structure:
    a wick through is not a break, a close beyond is. A sweep is specifically
    the first without the second.
    """
    if len(bars) < 10 or atr <= 0:
        return None
    for kind in ("high", "low"):
        points = [p for p in pivots if p.kind == kind and p.index < len(bars) - 3]
        if not points:
            continue
        prior = points[-1]
        # Sweeping *a* swing is unremarkable — a random walk does it constantly.
        # Sweeping the highest high of the preceding stretch is the event the
        # name describes: stops sat there, they were taken, price came back.
        window = bars.high[max(prior.index - 20, 0) : prior.index + 1] if kind == "high" \
            else bars.low[max(prior.index - 20, 0) : prior.index + 1]
        prominent = (
            prior.price >= float(window.max()) if kind == "high"
            else prior.price <= float(window.min())
        )
        if not prominent:
            continue
        recent = range(max(prior.index + 1, len(bars) - 5), len(bars))
        for i in recent:
            if kind == "high" and bars.high[i] > prior.price and bars.close[i] < prior.price:
                depth = float(bars.high[i] - prior.price) / atr
            elif kind == "low" and bars.low[i] < prior.price and bars.close[i] > prior.price:
                depth = float(prior.price - bars.low[i]) / atr
            else:
                continue
            if depth < 0.35:
                continue
            when = bars.times[prior.index].date().isoformat()
            return RulesPattern(
                name="liquidity_sweep",
                confidence=round(min(0.4 + depth * 0.4, 0.8), 2),
                why=(
                    f"wick {depth:.2f} ATR through the {when} swing {kind} "
                    f"with an immediate reclaim on the close"
                ),
                from_index=prior.index,
                to_index=i,
                measures={"depth_atr": depth},
            )
    return None


def _squeeze(bars, pivots, atr, trend, contraction) -> RulesPattern | None:
    if contraction >= 0.6 or len(bars) < 40:
        return None
    return RulesPattern(
        name="volatility_contraction",
        confidence=round(min(0.5 + (0.6 - contraction), 0.85), 2),
        why=(
            f"last 10 bars' true range is {contraction:.2f}x the prior 30 — "
            f"a squeeze, direction unspecified"
        ),
        from_index=max(len(bars) - 10, 0),
        to_index=len(bars) - 1,
        measures={"contraction": contraction},
    )


def _inside_range(bars, pivots, atr, trend, contraction) -> RulesPattern | None:
    """Price genuinely oscillating between two edges. The honest 'nothing'.

    Worth naming rather than leaving as an absence: *"it is ranging between 118
    and 124"* is a real answer to "what is this chart doing", and it is the
    answer that most often contradicts a vision model's flag or wedge.

    The definition has to be earned, and the obvious one is not: *"every close
    sits inside the window's own high and low"* is true of every window by
    construction, and would stamp ``range`` on every chart that failed the trend
    test. So the test is oscillation -- price must have visited **both** edges
    more than once -- plus a width narrow enough to trade. A slow one-way drift
    with a weak ADX fails it, correctly, because it is a drift and not a range.
    """
    if trend != "range" or len(bars) < 40 or atr <= 0:
        return None
    window_high = float(bars.high[-40:].max())
    window_low = float(bars.low[-40:].min())
    width = window_high - window_low
    # Width is only a sanity bound. It is tempting to require a *narrow* range
    # in ATR terms, but that gets it backwards: a clean, smooth oscillation has
    # a small per-bar true range and therefore a large width-in-ATR, and would
    # be the first thing rejected. Edge visits are the real discriminator.
    if width <= 0 or width / atr > 12:
        return None

    edge = width * 0.08
    upper = int((bars.high[-40:] >= window_high - edge).sum())
    lower = int((bars.low[-40:] <= window_low + edge).sum())
    if upper < 3 or lower < 3:
        return None

    return RulesPattern(
        name="range",
        confidence=round(min(0.4 + min(upper, lower) * 0.04, 0.8), 2),
        why=(
            f"40 bars oscillating between {window_low:.2f} and {window_high:.2f} "
            f"({width / atr:.1f} ATR wide), {upper} visits to the top and {lower} to the bottom"
        ),
        from_index=len(bars) - 40,
        to_index=len(bars) - 1,
        measures={
            "width_atr": width / atr,
            "high": window_high,
            "low": window_low,
            "upper_touches": float(upper),
            "lower_touches": float(lower),
        },
    )
