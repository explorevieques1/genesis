# Spec: Genesis Markdown/10-Architecture/Charting Engine.md
"""Level computation — and the editorial rules that keep it from being useless.

Charting Engine.md is direct about where the difficulty actually is:
*"The hard part isn't computing levels — it's computing good ones."* Computing
a support level is twenty lines. Computing eight levels a trader would have
drawn, out of the sixty a naive pass finds, is this file.

Four rules do that work, and each one is a policy decision rather than a
formula, which is why they live here in one place instead of being scattered
through the callers:

**Strength is scored, never asserted.** ``touches x recency x reaction x
volume``. A price touched four times last month with violent rejections on
heavy volume outranks one touched once a year ago. Each factor is 0..1 and they
multiply, so a level that is weak on any single axis cannot be strong overall --
which is the intended behaviour: a "level" with one touch is not a level no
matter how much volume traded there.

**Confluence merges.** Levels within ``CONFLUENCE_ATR`` of each other become one
level naming all of them. A trader looking at the 200-day, the prior-day high
and the value-area high sitting within a third of an ATR sees *one* wall, and a
chart that draws three lines there is describing the computation rather than the
market.

**Proximity is measured in ATR.** A level 30% away is noise on a day-trade
timeframe and routine on a monthly. ATR is the only distance that transfers
between symbols and timeframes, and Agent — Chart Markup requires it explicitly.

**Some levels are always included.** Prior-period high and low, session VWAP
intraday, and the nearest untested level above and below. They are cheap, they
are always relevant, and a scoring pass will sometimes rank them below a
beautiful cluster nobody is trading. Marked ``always`` and exempt from the
strength cut, though not from confluence merging.

Nothing in this module produces prose for a human or takes an instruction from
one. It emits candidates with a machine-written ``why``; Agent — Chart Markup
selects among them and rewrites the ``why`` in its own words -- but it may not
introduce a price, and :func:`LevelComputation.prices` is what proves it did not.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Iterable, Sequence

import numpy as np

from genesis.charting import indicators as ind
from genesis.charting.bars import Bars
from genesis.charting.timeframes import resolve

__all__ = [
    "CONFLUENCE_ATR",
    "FibCandidate",
    "LevelCandidate",
    "LevelComputation",
    "LineCandidate",
    "ZoneCandidate",
    "compute_levels",
    "merge_confluence",
]

#: Two levels closer than this are one level. Markup Spec Schema fixes it at
#: 0.25 ATR, and Agent — Chart Markup's acceptance criteria test it there.
CONFLUENCE_ATR = 0.25

#: Beyond this many ATR from spot, a level is not part of this chart's story.
#: Generous on purpose -- it is a relevance filter, not an opinion. Levels
#: outside it are still computed and still returned in ``all_prices``; they
#: simply score zero on proximity and lose the cut.
RELEVANCE_ATR = 12.0

#: Moving averages drawn as levels. Three, because the fourth is clutter and
#: nobody has ever been saved by the 100-day.
MA_PERIODS = (20, 50, 200)


@dataclass(frozen=True)
class LevelCandidate:
    """One horizontal price, with everything needed to score and explain it."""

    price: float
    label: str
    type: str
    source: str
    why: str
    touches: int = 0
    strength: float = 0.0
    confluence: tuple[str, ...] = ()
    #: Exempt from the strength cut. See the module docstring.
    always: bool = False
    #: Distance from spot in ATR, signed: positive above, negative below.
    distance_atr: float = 0.0

    @property
    def side(self) -> str:
        return "above" if self.distance_atr > 0 else "below"


@dataclass(frozen=True)
class ZoneCandidate:
    low: float
    high: float
    label: str
    subtype: str
    source: str
    why: str
    strength: float = 0.0
    filled: bool = False


@dataclass(frozen=True)
class LineCandidate:
    points: tuple[tuple[datetime, float], ...]
    label: str
    why: str
    touches: int = 0
    strength: float = 0.0


@dataclass(frozen=True)
class FibCandidate:
    anchor_from: tuple[datetime, float]
    anchor_to: tuple[datetime, float]
    retracements: tuple[float, ...]
    why: str


@dataclass(frozen=True)
class LevelComputation:
    """Everything computed for one symbol and timeframe.

    The return of ``compute_levels``, and also the provenance ledger: an agent
    that writes a price not in :meth:`prices` invented it.
    """

    symbol: str
    timeframe: str
    as_of: datetime
    spot: float
    atr: float
    levels: tuple[LevelCandidate, ...] = ()
    zones: tuple[ZoneCandidate, ...] = ()
    lines: tuple[LineCandidate, ...] = ()
    fibs: tuple[FibCandidate, ...] = ()
    #: Anything the computation could not do and why, so a caller can say
    #: "no volume profile, the feed gave no volume" instead of going quiet.
    notes: tuple[str, ...] = ()
    degraded: bool = False

    def prices(self) -> list[float]:
        """Every price this computation vouches for.

        Includes fib retracement prices as well as anchors, because a spec may
        legitimately carry a retracement level that appears in no candidate.
        """
        out = [c.price for c in self.levels]
        for z in self.zones:
            out.extend((z.low, z.high))
        for line in self.lines:
            out.extend(p[1] for p in line.points)
        for fib in self.fibs:
            start, end = fib.anchor_from[1], fib.anchor_to[1]
            out.extend((start, end))
            out.extend(end - (end - start) * r for r in fib.retracements)
        out.append(self.spot)
        return out

    def strongest(self, n: int = 8) -> tuple[LevelCandidate, ...]:
        """The cut. ``always`` levels first, then by strength."""
        ranked = sorted(
            self.levels, key=lambda c: (not c.always, -c.strength, abs(c.distance_atr))
        )
        return tuple(ranked[:n])

    def nearest(self, above: bool) -> LevelCandidate | None:
        side = [c for c in self.levels if (c.distance_atr > 0) == above]
        if not side:
            return None
        return min(side, key=lambda c: abs(c.distance_atr))


# --------------------------------------------------------------------------
# The pass
# --------------------------------------------------------------------------


def compute_levels(
    bars: Bars,
    *,
    max_levels: int = 8,
    swing_k: int | None = None,
    orb_minutes: int = 30,
) -> LevelComputation:
    """Every structural level on this chart, scored and merged.

    Order is deliberate: gather everything first, score once, merge once. An
    implementation that merged as it went would produce a different chart
    depending on which level type ran first, and determinism is a stated
    acceptance criterion of the renderer that consumes this.
    """
    tf = resolve(bars.timeframe)
    atr = ind.last_atr(bars)
    spot = bars.last
    notes: list[str] = []
    if atr <= 0:
        # Every tolerance in this file is a multiple of ATR. Without one there
        # is no merging, no proximity weight and no watch band, so say so and
        # fall back to a percent of price rather than dividing by zero.
        atr = max(spot * 0.01, 1e-9)
        notes.append("ATR unavailable; distances fall back to 1% of price")

    k = swing_k if swing_k is not None else _swing_k(tf.minutes)
    pivots = ind.swings(bars, k)

    candidates: list[LevelCandidate] = []
    candidates.extend(_sr_clusters(bars, pivots, atr))
    candidates.extend(_prior_period(bars))
    candidates.extend(_moving_averages(bars))

    profile_levels, profile_zone, profile_note = _profile(bars)
    candidates.extend(profile_levels)
    if profile_note:
        notes.append(profile_note)

    vwap_levels, vwap_note = _vwaps(bars, pivots)
    candidates.extend(vwap_levels)
    if vwap_note:
        notes.append(vwap_note)

    zones: list[ZoneCandidate] = []
    if profile_zone is not None:
        zones.append(profile_zone)
    zones.extend(_fair_value_gaps(bars, atr))
    zones.extend(_order_blocks(bars, atr))

    orb = _opening_range_zone(bars, tf.minutes, orb_minutes)
    if orb is not None:
        zones.append(orb)

    scored = [_score(c, bars, atr, spot) for c in candidates]
    merged = merge_confluence(scored, atr)
    # Merging moves a level's price, so its ATR distance is now the distance to
    # a price that no longer exists. Recomputed rather than left stale: the
    # distance is what proximity weighting, the watcher's bands and
    # `nearest_htf_level` all read, and a stale one is wrong quietly.
    merged = [
        replace(c, distance_atr=round((c.price - spot) / atr, 2)) for c in merged
    ]
    marked = _mark_always(merged, bars, atr, spot)

    lines = _trendlines(bars, pivots, atr)
    fibs = _fibs(bars, pivots)

    return LevelComputation(
        symbol=bars.symbol,
        timeframe=bars.timeframe,
        as_of=bars.last_time,
        spot=spot,
        atr=atr,
        levels=tuple(sorted(marked, key=lambda c: -c.price)),
        zones=tuple(zones),
        lines=tuple(lines),
        fibs=tuple(fibs),
        notes=tuple(notes),
        degraded=bool(notes),
    )


def _swing_k(minutes: int) -> int:
    """Pivot width by timeframe.

    Wider on fast timeframes because intraday noise makes every third bar a
    fractal pivot; narrower on weekly and monthly where there are few bars and
    every real turn matters. This is the policy the indicator deliberately does
    not hold.
    """
    if minutes <= 15:
        return 5
    if minutes <= 240:
        return 4
    if minutes <= 1440:
        return 3
    return 2


# -- level sources ---------------------------------------------------------


def _sr_clusters(bars: Bars, pivots: Sequence[ind.Swing], atr: float) -> list[LevelCandidate]:
    """Swing points clustered into support and resistance.

    A cluster is a set of pivots within ``CONFLUENCE_ATR`` of each other. Its
    price is the *volume-free mean* of its members -- not the most recent touch,
    not the extreme. The mean is what a hand-drawn level actually is: the line
    through a set of turns that were never at exactly the same price.
    """
    if not pivots:
        return []
    tolerance = atr * CONFLUENCE_ATR
    out: list[LevelCandidate] = []
    for kind, wanted in (("high", "resistance"), ("low", "support")):
        prices = sorted((p for p in pivots if p.kind == kind), key=lambda p: p.price)
        cluster: list[ind.Swing] = []
        for pivot in prices:
            if cluster and pivot.price - cluster[0].price > tolerance:
                out.append(_cluster_level(cluster, wanted, bars))
                cluster = []
            cluster.append(pivot)
        if cluster:
            out.append(_cluster_level(cluster, wanted, bars))
    # A single untouched pivot is a bar's extreme, not a level. Two touches is
    # the minimum that makes the word mean anything.
    return [c for c in out if c.touches >= 2]


def _cluster_level(cluster: list[ind.Swing], kind: str, bars: Bars) -> LevelCandidate:
    price = float(np.mean([p.price for p in cluster]))
    latest = max(p.index for p in cluster)
    when = bars.times[latest].date().isoformat()
    return LevelCandidate(
        price=price,
        label=f"{'R' if kind == 'resistance' else 'S'} {price:.2f}",
        type=kind,
        source="sr-cluster",
        touches=len(cluster),
        why=(
            f"{len(cluster)} swing {'highs' if kind == 'resistance' else 'lows'} "
            f"within a quarter ATR, most recently {when}"
        ),
    )


def _prior_period(bars: Bars) -> list[LevelCandidate]:
    """Prior session high, low and close. Always drawn, trivially derived.

    On an intraday series the prior *session* is the previous calendar day's
    bars; on daily-or-slower it is simply the previous bar. Both are "the last
    completed period", and conflating them is how a 5-minute chart ends up with
    a "prior-day high" that is the high of the last five minutes.
    """
    sessions = bars.sessions()
    if len(sessions) < 2:
        return []
    start, end = sessions[-2]
    high = float(bars.high[start : end + 1].max())
    low = float(bars.low[start : end + 1].min())
    close = float(bars.close[end])
    when = bars.times[end].date().isoformat()
    return [
        LevelCandidate(
            price=high, label="PDH", type="resistance", source="prior-period",
            touches=1, always=True, why=f"prior session high ({when})",
        ),
        LevelCandidate(
            price=low, label="PDL", type="support", source="prior-period",
            touches=1, always=True, why=f"prior session low ({when})",
        ),
        LevelCandidate(
            price=close, label="PDC", type="pivot", source="prior-period",
            touches=1, why=f"prior session close ({when})",
        ),
    ]


def _moving_averages(bars: Bars) -> list[LevelCandidate]:
    out: list[LevelCandidate] = []
    for period in MA_PERIODS:
        values = ind.sma(bars.close, period)
        if len(values) == 0 or np.isnan(values[-1]):
            continue
        price = float(values[-1])
        above = bars.close[-1] > price
        out.append(
            LevelCandidate(
                price=price,
                label=f"{period}MA",
                type="ma",
                source=f"sma{period}",
                touches=_ma_touches(bars, values),
                why=(
                    f"{period}-period moving average, price {'above' if above else 'below'}"
                ),
            )
        )
    return out


def _ma_touches(bars: Bars, values: np.ndarray, window: int = 120) -> int:
    """How often price crossed this average recently.

    A moving average price has never touched is a line on a chart; one it has
    bounced off six times is a level. Counting crossings is the cheap proxy,
    and it is what stops the 200-day being drawn with authority on a name
    trading 40% above it.
    """
    lo = max(len(bars) - window, 0)
    close, ma = bars.close[lo:], values[lo:]
    valid = ~np.isnan(ma)
    if valid.sum() < 3:
        return 0
    sign = np.sign(close[valid] - ma[valid])
    return int((np.diff(sign) != 0).sum())


def _profile(bars: Bars) -> tuple[list[LevelCandidate], ZoneCandidate | None, str]:
    if float(bars.volume.sum()) <= 0:
        return [], None, "no volume in the feed; volume profile and POC skipped"
    centres, profile = ind.volume_profile(bars)
    poc, val, vah = ind.value_area(centres, profile)
    if not np.isfinite(poc):
        return [], None, "volume profile produced no point of control"
    levels = [
        LevelCandidate(
            price=poc, label="POC", type="poc", source="volume-profile", touches=1,
            why="point of control — the price with the most volume traded in the window",
        ),
        LevelCandidate(
            price=vah, label="VAH", type="value_area", source="volume-profile", touches=1,
            why="value area high — upper bound of the 70% volume band",
        ),
        LevelCandidate(
            price=val, label="VAL", type="value_area", source="volume-profile", touches=1,
            why="value area low — lower bound of the 70% volume band",
        ),
    ]
    zone = ZoneCandidate(
        low=val, high=vah, label="value area", subtype="value_area",
        source="volume-profile",
        why="70% of the window's volume traded inside this band",
        strength=0.5,
    )
    return levels, zone, ""


def _vwaps(bars: Bars, pivots: Sequence[ind.Swing]) -> tuple[list[LevelCandidate], str]:
    """Session VWAP where it means something, plus one anchored VWAP.

    The anchor is the most recent significant swing -- the low that started the
    current leg, or the high that capped it. Choosing the anchor by structure
    rather than by hand is what makes the level reproducible, which is the
    whole reason Charting Engine.md wants levels computed here instead of read
    off a screenshot.
    """
    out: list[LevelCandidate] = []
    note = ""
    if float(bars.volume.sum()) <= 0:
        return out, "no volume in the feed; VWAP skipped"

    session = ind.session_vwap(bars)
    if len(session) and not np.isnan(session[-1]):
        out.append(
            LevelCandidate(
                price=float(session[-1]), label="VWAP", type="vwap",
                source="session-vwap", touches=1, always=True,
                why="session VWAP — the intraday average everyone is trading against",
            )
        )
    elif resolve(bars.timeframe).is_intraday:
        note = "session VWAP unavailable on this window"

    anchor = _dominant_anchor(bars, pivots)
    if anchor is not None:
        values = ind.anchored_vwap(bars, anchor.index)
        if not np.isnan(values[-1]):
            when = bars.times[anchor.index].date().isoformat()
            out.append(
                LevelCandidate(
                    price=float(values[-1]), label="AVWAP", type="vwap",
                    source=f"anchored-vwap@{when}", touches=1,
                    why=(
                        f"VWAP anchored to the swing {anchor.kind} of {when} — "
                        f"the average price paid since this leg began"
                    ),
                )
            )
    return out, note


def _dominant_anchor(bars: Bars, pivots: Sequence[ind.Swing]) -> ind.Swing | None:
    """The pivot that started the current leg.

    Defined as the most recent extreme in the back half of the window: the low
    if price has risen since, the high if it has fallen. Deliberately crude,
    because a sophisticated definition would be one nobody could reproduce.
    """
    if not pivots:
        return None
    half = len(bars) // 2
    recent = [p for p in pivots if p.index >= half] or list(pivots)
    rising = bars.close[-1] >= bars.close[half]
    wanted = "low" if rising else "high"
    matching = [p for p in recent if p.kind == wanted]
    if not matching:
        return None
    return min(matching, key=lambda p: p.price) if rising else max(matching, key=lambda p: p.price)


def _fair_value_gaps(bars: Bars, atr: float, lookback: int = 60) -> list[ZoneCandidate]:
    """Three-bar imbalances that price has not yet filled.

    A bullish FVG is bar i-1's high below bar i+1's low: a range that traded
    through in one direction without two-sided auction. Filled gaps are dropped
    rather than drawn greyed-out -- a filled gap is history, and the chart is
    for deciding, not for admiring.
    """
    out: list[ZoneCandidate] = []
    start = max(len(bars) - lookback, 1)
    minimum = atr * 0.2
    for i in range(start, len(bars) - 1):
        prev_high, prev_low = float(bars.high[i - 1]), float(bars.low[i - 1])
        next_high, next_low = float(bars.high[i + 1]), float(bars.low[i + 1])
        when = bars.times[i].date().isoformat()
        if next_low > prev_high and next_low - prev_high >= minimum:
            low, high, kind = prev_high, next_low, "demand"
        elif prev_low > next_high and prev_low - next_high >= minimum:
            low, high, kind = next_high, prev_low, "supply"
        else:
            continue
        after = bars.low[i + 2 :], bars.high[i + 2 :]
        filled = bool(len(after[0]) and after[0].min() <= high and after[1].max() >= low)
        if filled:
            continue
        out.append(
            ZoneCandidate(
                low=low, high=high, label=f"FVG {kind}", subtype="fvg",
                source="fvg",
                why=f"unfilled fair value gap from the {when} impulse leg",
                strength=min((high - low) / atr, 1.0) if atr else 0.5,
            )
        )
    # Keep the two most recent: an unfilled-gap detector on a trending name
    # finds a dozen, and a chart of a dozen boxes is a chart of none.
    return out[-2:]


def _order_blocks(bars: Bars, atr: float, lookback: int = 60) -> list[ZoneCandidate]:
    """The last opposing candle before an impulsive move.

    Impulse is defined in ATR (a move of 1.5 ATR over three bars), not percent,
    for the reason every other threshold here is: percent is not comparable
    across names.
    """
    out: list[ZoneCandidate] = []
    start = max(len(bars) - lookback, 1)
    for i in range(start, len(bars) - 3):
        move = float(bars.close[i + 3] - bars.close[i])
        if abs(move) < atr * 1.5:
            continue
        bullish_candle = bars.close[i] > bars.open[i]
        if (move > 0 and bullish_candle) or (move < 0 and not bullish_candle):
            continue
        when = bars.times[i].date().isoformat()
        out.append(
            ZoneCandidate(
                low=float(bars.low[i]), high=float(bars.high[i]),
                label="order block", subtype="order_block", source="order-block",
                why=(
                    f"last {'down' if move > 0 else 'up'} candle before the {when} "
                    f"{abs(move) / atr:.1f} ATR impulse"
                ),
                strength=min(abs(move) / (atr * 3), 1.0),
            )
        )
    return out[-1:]


def _opening_range_zone(bars: Bars, tf_minutes: int, orb_minutes: int) -> ZoneCandidate | None:
    if tf_minutes >= 1440:
        return None
    rng = ind.opening_range(bars, orb_minutes, tf_minutes)
    if rng is None:
        return None
    low, high = rng
    return ZoneCandidate(
        low=low, high=high, label=f"ORB {orb_minutes}m", subtype="orb",
        source="opening-range",
        why=f"first {orb_minutes} minutes of the session",
        strength=0.6,
    )


def _trendlines(bars: Bars, pivots: Sequence[ind.Swing], atr: float) -> list[LineCandidate]:
    """Lines fitted to swing points, kept only when enough pivots sit on them.

    Two anchor pivots define a line; a third pivot within a quarter ATR of it
    is a touch. Below three touches it is a line through two points, which is
    every pair of points, and drawing those is how a chart gets forty lines.

    Charting Family flags this as the level type most likely to be *disproved*
    by Agent — Level Watcher's outcome tracking -- *"your fitted trendlines hold
    38%, stop drawing trendlines"*. Computing them anyway is the point: the
    claim is only checkable because they are structured and scored.
    """
    out: list[LineCandidate] = []
    tolerance = atr * CONFLUENCE_ATR
    for kind in ("high", "low"):
        points = [p for p in pivots if p.kind == kind]
        if len(points) < 3:
            continue
        best: tuple[int, LineCandidate] | None = None
        for a_idx in range(len(points) - 2):
            for b_idx in range(a_idx + 2, len(points)):
                a, b = points[a_idx], points[b_idx]
                if b.index == a.index:
                    continue
                slope = (b.price - a.price) / (b.index - a.index)
                touches = sum(
                    1
                    for p in points
                    if abs(p.price - (a.price + slope * (p.index - a.index))) <= tolerance
                )
                if touches < 3:
                    continue
                if best is None or touches > best[0]:
                    direction = "rising" if slope > 0 else "falling"
                    best = (
                        touches,
                        LineCandidate(
                            points=(
                                (bars.times[a.index], a.price),
                                (bars.times[b.index], b.price),
                            ),
                            label=f"{direction} {'resistance' if kind == 'high' else 'support'}",
                            why=(
                                f"{touches} swing {kind}s within a quarter ATR of this line "
                                f"since {bars.times[a.index].date().isoformat()}"
                            ),
                            touches=touches,
                            strength=min(touches / 5.0, 1.0),
                        ),
                    )
        if best is not None:
            out.append(best[1])
    return out


def _fibs(bars: Bars, pivots: Sequence[ind.Swing]) -> list[FibCandidate]:
    """Retracements from the dominant swing — chosen by structure, not by hand.

    The dominant swing is the largest price move between a pivot low and a
    later pivot high (or the reverse) in the window. One fib set or none; two
    fib sets on one chart is a screenshot from a forum.
    """
    if len(pivots) < 2:
        return []
    best: tuple[float, ind.Swing, ind.Swing] | None = None
    for i, start in enumerate(pivots):
        for end in pivots[i + 1 :]:
            if start.kind == end.kind:
                continue
            span = abs(end.price - start.price)
            if best is None or span > best[0]:
                best = (span, start, end)
    if best is None:
        return []
    _, start, end = best
    direction = "up" if end.price > start.price else "down"
    return [
        FibCandidate(
            anchor_from=(bars.times[start.index], start.price),
            anchor_to=(bars.times[end.index], end.price),
            retracements=(0.236, 0.382, 0.5, 0.618, 0.786),
            why=(
                f"retracement of the dominant {direction} swing, "
                f"{bars.times[start.index].date().isoformat()} to "
                f"{bars.times[end.index].date().isoformat()}"
            ),
        )
    ]


# -- scoring and merging ---------------------------------------------------


def _score(c: LevelCandidate, bars: Bars, atr: float, spot: float) -> LevelCandidate:
    """``touches x recency x reaction x volume x proximity``, each 0..1.

    Multiplicative rather than additive, and that is the substantive choice: a
    sum lets one strong factor carry a level that fails on every other axis,
    which is exactly how a price with enormous volume and zero touches ends up
    drawn as support.
    """
    touch_score = min(c.touches / 4.0, 1.0) if c.touches else 0.25
    recency = _recency(c, bars, atr)
    reaction = _reaction(c, bars, atr)
    volume = _volume_at(c.price, bars, atr)
    distance = (c.price - spot) / atr if atr else 0.0
    proximity = max(0.0, 1.0 - abs(distance) / RELEVANCE_ATR)

    strength = touch_score * recency * reaction * volume * max(proximity, 0.05)
    # The geometric mean of five factors collapses toward zero; rescaling keeps
    # `strength` readable as the 0..1 figure the schema documents rather than a
    # number that is 0.03 for every level on every chart.
    strength = float(min(strength ** 0.5, 1.0))
    return replace(c, strength=round(strength, 3), distance_atr=round(distance, 2))


def _recency(c: LevelCandidate, bars: Bars, atr: float) -> float:
    """How recently price was actually at this level, 0.3..1.

    Floored rather than zeroed: a level untouched for the whole window is still
    a level (the 200-day, an old high), it is simply not a fresh one. Zeroing
    would delete it entirely, and multiplicative scoring makes any zero fatal.
    """
    band = atr * 0.5
    near = np.where((bars.low <= c.price + band) & (bars.high >= c.price - band))[0]
    if len(near) == 0:
        return 0.3
    age = (len(bars) - 1 - int(near[-1])) / max(len(bars) - 1, 1)
    return float(0.3 + 0.7 * (1.0 - age))


def _reaction(c: LevelCandidate, bars: Bars, atr: float) -> float:
    """How hard price moved away after touching, in ATR, 0.2..1.

    This is what separates a level from a price that happened to be printed.
    A resistance that produced three 2-ATR rejections is information; one price
    drifted through four times is not, however many "touches" it has.
    """
    band = atr * 0.5
    touched = np.where((bars.low <= c.price + band) & (bars.high >= c.price - band))[0]
    if len(touched) == 0:
        return 0.2
    moves = []
    for i in touched:
        window = bars.close[i : i + 6]
        if len(window) < 2:
            continue
        moves.append(float(np.abs(window - c.price).max()) / atr)
    if not moves:
        return 0.2
    return float(min(0.2 + float(np.mean(moves)) / 2.0, 1.0))


def _volume_at(price: float, bars: Bars, atr: float) -> float:
    """Share of window volume that traded within half an ATR of this price.

    Normalised against the busiest band rather than the total, so the answer is
    *"how does this price compare to the busiest price"* -- which is the
    comparison that means something -- rather than a small fraction that varies
    with how many bins the window happens to have.
    """
    if float(bars.volume.sum()) <= 0:
        return 0.6  # no volume data is not evidence of no volume
    centres, profile = ind.volume_profile(bars)
    if len(centres) == 0 or profile.max() <= 0:
        return 0.6
    band = atr * 0.5
    mask = np.abs(centres - price) <= band
    if not mask.any():
        return 0.2
    return float(min(profile[mask].sum() / profile.max(), 1.0))


def merge_confluence(
    levels: Iterable[LevelCandidate], atr: float, *, tolerance_atr: float = CONFLUENCE_ATR
) -> list[LevelCandidate]:
    """Levels within ``tolerance_atr`` become one, naming all of them.

    The survivor is the strongest member, and its price is the strength-weighted
    mean of the group -- so a strong cluster is not dragged off by a weak moving
    average that happened to sit nearby, but is nudged by it, which is honest.

    Strength is boosted, not summed: three coincident levels are stronger than
    one, and no amount of coincidence makes a level certain. The boost is capped
    at 1.0 and applied as ``1 - (1 - s)^n``, which is the probability form -- it
    approaches certainty and never reaches it.

    ``always`` propagates: merging the prior-day high into a cluster must not
    quietly drop the guarantee that PDH appears on the chart.
    """
    ordered = sorted(levels, key=lambda c: c.price)
    tolerance = atr * tolerance_atr
    groups: list[list[LevelCandidate]] = []
    for level in ordered:
        if groups and level.price - groups[-1][0].price <= tolerance:
            groups[-1].append(level)
        else:
            groups.append([level])

    out: list[LevelCandidate] = []
    for group in groups:
        if len(group) == 1:
            out.append(group[0])
            continue
        lead = max(group, key=lambda c: (c.always, c.strength))
        weights = np.array([max(c.strength, 0.01) for c in group])
        price = float(np.average([c.price for c in group], weights=weights))
        boosted = 1.0 - float(np.prod([1.0 - min(c.strength, 0.99) for c in group]))
        names = tuple(dict.fromkeys(c.label for c in group))
        out.append(
            replace(
                lead,
                price=price,
                strength=round(min(boosted, 1.0), 3),
                touches=sum(c.touches for c in group),
                confluence=names,
                always=any(c.always for c in group),
                label=_merged_label(lead, price, _merged_type(group, lead)),
                type=_merged_type(group, lead),
                why=(
                    f"confluence of {', '.join(names)} within a quarter ATR — "
                    + lead.why
                ),
            )
        )
    return out


def _merged_label(lead: LevelCandidate, price: float, merged_type: str) -> str:
    """Relabel a merged cluster so the chip does not contradict the line.

    A cluster label embeds its own price (``"R 113.91"``), and merging moves the
    price. Left alone, the chart renders "R 113.91" against a line at 113.70 --
    a two-number disagreement in the one place the whole design insists on
    being unambiguous, and precisely the sort of thing a vision model reads and
    repeats. The prefix is taken from the *merged* type for the same reason: a
    flip level labelled "R" contradicts its own classification.
    """
    if lead.source == "sr-cluster":
        prefix = {"resistance": "R", "support": "S"}.get(merged_type, "P")
        return f"{prefix} {price:.2f}"
    return lead.label


def _merged_type(group: list[LevelCandidate], lead: LevelCandidate) -> str:
    """Support merged with resistance is a pivot, and saying so is the point.

    A price that has acted as both is a flip level -- the thing traders mean by
    "support becomes resistance" -- and it is more informative than whichever of
    the two happened to score higher. Any other mix keeps the lead's type.
    """
    kinds = {c.type for c in group}
    if {"support", "resistance"} <= kinds:
        return "pivot"
    return lead.type


def _mark_always(
    levels: list[LevelCandidate], bars: Bars, atr: float, spot: float
) -> list[LevelCandidate]:
    """Guarantee the nearest untested level above and below survives the cut.

    Agent — Chart Markup's *"always include ... the nearest untested level above
    and below"*. Untested means price has not traded through it since it formed,
    which here is the nearest level on each side that has not been crossed --
    those two are what price has to deal with next, whatever the scoring thinks.
    """
    if not levels:
        return levels
    out = list(levels)
    for above in (True, False):
        side = [c for c in out if (c.price > spot) == above]
        if not side:
            continue
        nearest = min(side, key=lambda c: abs(c.price - spot))
        if nearest.always:
            continue
        out[out.index(nearest)] = replace(
            nearest,
            always=True,
            why=nearest.why + f" — nearest untested level {'above' if above else 'below'}",
        )
    return out
