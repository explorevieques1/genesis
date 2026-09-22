# Spec: Genesis Markdown/10-Architecture/Charting Engine.md
"""The arithmetic. No model touches anything in this file.

Charting Engine.md: *"Genesis computes structure itself rather than trusting a
screenshot"*, and Safety Invariants §3: *"nothing safety-critical or arithmetic
runs on an LLM"*. This module is where the second rule is kept for the first
one -- swings, ATR, VWAP, volume profile and trend strength are all pure
functions of an OHLCV array, and a language model is never in the call chain.

Conventions borrowed rather than reinvented, per Trading Corpus Index
(``nautilus_trader/indicators/``, ``vectorbt/indicators/factory.py``):

* **ATR is Wilder's**, not a simple mean of true range. Every ATR-relative
  tolerance in this system -- confluence merging, level-watch bands,
  ``nearest_htf_level`` distance -- is calibrated against Wilder's, and mixing
  the two smoothings changes a 0.25 ATR merge threshold by enough to change
  which levels merge.
* **Swings are fractal pivots**, a high with ``k`` lower highs on each side.
  Simple, deterministic, and the same definition the eye uses.
* **Volume profile is bar-distributed**, not close-weighted: a bar's volume is
  spread across the price range it traded, because attributing a full day's
  volume to its closing price puts the POC wherever the last print happened.

Everything returns plain floats and numpy arrays. Nothing here knows what a
Markup Spec is; that composition happens one layer up in :mod:`levels`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from genesis.charting.bars import Bars
from genesis.charting.timeframes import resolve

__all__ = [
    "Swing",
    "adx",
    "anchored_vwap",
    "atr",
    "ema",
    "opening_range",
    "realized_vol",
    "session_vwap",
    "rsi",
    "sma",
    "swings",
    "trend_strength",
    "value_area",
    "volatility_percentile",
    "volume_profile",
]


# --------------------------------------------------------------------------
# Moving averages and volatility
# --------------------------------------------------------------------------


def sma(values: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average, NaN-padded to the input length.

    Padding rather than truncating so an index into the output is the same
    index into the bars. Every off-by-one bug in charting code is an alignment
    bug, and returning a shorter array is how they start.
    """
    out = np.full(len(values), np.nan)
    if period <= 0 or len(values) < period:
        return out
    cumulative = np.cumsum(np.insert(values, 0, 0.0))
    out[period - 1 :] = (cumulative[period:] - cumulative[:-period]) / period
    return out


def ema(values: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if period <= 0 or len(values) < period:
        return out
    alpha = 2.0 / (period + 1.0)
    out[period - 1] = values[:period].mean()
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def rsi(values: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder's RSI, 0..100, NaN-padded. Flat series read 50, all-gains 100."""
    out = np.full(len(values), np.nan)
    if period <= 0 or len(values) <= period:
        return out
    delta = np.diff(values)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain, avg_loss = gain[:period].mean(), loss[:period].mean()

    def value(g: float, l: float) -> float:
        if l == 0:
            return 50.0 if g == 0 else 100.0
        return 100.0 - 100.0 / (1.0 + g / l)

    out[period] = value(avg_gain, avg_loss)
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
        out[i + 1] = value(avg_gain, avg_loss)
    return out


def true_range(bars: Bars) -> np.ndarray:
    high, low, close = bars.high, bars.low, bars.close
    prior = np.concatenate(([close[0]], close[:-1]))
    return np.maximum(high - low, np.maximum(np.abs(high - prior), np.abs(low - prior)))


def atr(bars: Bars, period: int = 14) -> np.ndarray:
    """Wilder's ATR, NaN-padded. The unit every distance in this system uses.

    ATR rather than percent throughout, and the reason is in
    Agent — Chart Markup: *"weight by distance in ATR units, not percent"*. A
    level 2% away is meaningless on its own -- 2% is a quiet week on one name
    and two sessions of range on another. ATR normalises by how much the thing
    actually moves, which is the only comparison that transfers across symbols.
    """
    out = np.full(len(bars), np.nan)
    if len(bars) <= period:
        return out
    tr = true_range(bars)
    out[period] = tr[1 : period + 1].mean()
    for i in range(period + 1, len(bars)):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def last_atr(bars: Bars, period: int = 14) -> float:
    """The current ATR, or a degraded fallback on a window too short for one.

    The fallback is the mean true range of whatever exists. It is worse, and
    the caller is expected to be honest about that -- but returning NaN here
    would propagate into every tolerance downstream and turn a short window
    into a chart with no merged levels and no watch bands, silently.
    """
    values = atr(bars, period)
    if len(values) and not np.isnan(values[-1]):
        return float(values[-1])
    tr = true_range(bars)
    return float(tr.mean()) if len(tr) else 0.0


def realized_vol(bars: Bars, period: int = 20, periods_per_year: int = 252) -> float:
    """Annualised close-to-close volatility over the last ``period`` bars."""
    returns = bars.returns
    if len(returns) < period:
        return float("nan")
    return float(np.std(returns[-period:], ddof=1) * np.sqrt(periods_per_year))


def volatility_percentile(bars: Bars, period: int = 20, lookback: int = 252) -> float:
    """Where current volatility sits in its own history, 0..1.

    The Markup Spec's ``volatility_pct_rank``. A percentile rather than a level
    because *"vol is 24"* means nothing without knowing that this name lives
    between 15 and 60 -- and the rank is what tells you whether a compression
    pattern is real.
    """
    returns = bars.returns
    if len(returns) < period * 2:
        return float("nan")
    window = returns[-lookback:] if len(returns) > lookback else returns
    rolling = np.array(
        [np.std(window[i - period : i], ddof=1) for i in range(period, len(window) + 1)]
    )
    if len(rolling) < 2:
        return float("nan")
    return float((rolling < rolling[-1]).sum() / (len(rolling) - 1))


# --------------------------------------------------------------------------
# Swings and trend
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Swing:
    """One pivot: an index, its price, and which way it turned."""

    index: int
    price: float
    kind: str  # "high" | "low"


def swings(bars: Bars, k: int = 3) -> list[Swing]:
    """Fractal pivots: a high with ``k`` lower highs either side, and the mirror.

    ``k`` is the whole character of the output. Small k finds every wiggle and
    produces a chart of forty trendlines; large k finds only the two obvious
    turns and misses the structure a trader is actually reading. Three is the
    common default and is scaled by timeframe at the call site in
    :mod:`levels`, not here -- this function should stay a definition, not a
    policy.
    """
    out: list[Swing] = []
    n = len(bars)
    if n < 2 * k + 1:
        return out
    for i in range(k, n - k):
        window_high = bars.high[i - k : i + k + 1]
        window_low = bars.low[i - k : i + k + 1]
        if bars.high[i] == window_high.max() and (window_high.argmax() == k):
            out.append(Swing(i, float(bars.high[i]), "high"))
        elif bars.low[i] == window_low.min() and (window_low.argmin() == k):
            out.append(Swing(i, float(bars.low[i]), "low"))
    return out


def adx(bars: Bars, period: int = 14) -> float:
    """Wilder's ADX as a single current reading, 0..100.

    The rules engine's answer to *"is this trending or ranging"*, and the
    skeptic Agent — Pattern Recognition is cross-checked against. A number the
    vision model cannot argue with.
    """
    n = len(bars)
    if n < period * 2 + 1:
        return float("nan")
    up = np.diff(bars.high)
    down = -np.diff(bars.low)
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(bars)[1:]

    def _wilder(values: np.ndarray) -> np.ndarray:
        out = np.zeros(len(values))
        out[period - 1] = values[:period].sum()
        for i in range(period, len(values)):
            out[i] = out[i - 1] - out[i - 1] / period + values[i]
        return out

    tr_s, plus_s, minus_s = _wilder(tr), _wilder(plus_dm), _wilder(minus_dm)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * plus_s / tr_s
        minus_di = 100.0 * minus_s / tr_s
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    dx = dx[period - 1 :]
    dx = dx[np.isfinite(dx)]
    if len(dx) < period:
        return float("nan")
    value = dx[:period].mean()
    for x in dx[period:]:
        value = (value * (period - 1) + x) / period
    return float(value)


def trend_strength(bars: Bars, period: int = 14) -> float:
    """ADX rescaled to 0..1, because everything else in the spec is 0..1.

    25 is the conventional trending threshold and 50 is a strong trend, so the
    scale saturates at 50 rather than 100 -- an ADX of 80 and an ADX of 55 are
    the same message.
    """
    value = adx(bars, period)
    if np.isnan(value):
        return float("nan")
    return float(min(value / 50.0, 1.0))


# --------------------------------------------------------------------------
# Volume-derived
# --------------------------------------------------------------------------


def session_vwap(bars: Bars) -> np.ndarray:
    """VWAP restarted at each session boundary. NaN on a daily-or-slower series.

    Restarting matters: a continuously accumulated VWAP over three months is a
    long-run average nobody trades against, while today's session VWAP is the
    line intraday traders are actually watching. Session boundaries come from
    the timestamps (:meth:`Bars.sessions`), not a bar count, so half-days
    anchor correctly.
    """
    out = np.full(len(bars), np.nan)
    if not resolve(bars.timeframe).is_intraday:
        # One bar per session makes session VWAP equal to that bar's typical
        # price -- an arithmetic identity dressed up as a level. Returning NaN
        # is what stops a daily chart from carrying a confident, meaningless
        # "VWAP" line, which is the failure this guard exists for.
        return out
    typical = bars.typical
    for start, end in bars.sessions():
        vol = np.cumsum(bars.volume[start : end + 1])
        pv = np.cumsum(typical[start : end + 1] * bars.volume[start : end + 1])
        with np.errstate(divide="ignore", invalid="ignore"):
            out[start : end + 1] = np.where(vol > 0, pv / vol, np.nan)
    return out


def anchored_vwap(bars: Bars, anchor: int) -> np.ndarray:
    """VWAP accumulated from one chosen bar forward.

    Anchored at an event -- an earnings gap, the swing low that started the
    move, the high everyone is trapped above. This is the level type
    Agent — Level Watcher's performance tracking is expected to vindicate, and
    the reason the anchor is a parameter rather than a constant is that *which*
    event you anchor to is the analysis.
    """
    out = np.full(len(bars), np.nan)
    if not 0 <= anchor < len(bars):
        return out
    typical = bars.typical[anchor:]
    volume = bars.volume[anchor:]
    vol = np.cumsum(volume)
    pv = np.cumsum(typical * volume)
    with np.errstate(divide="ignore", invalid="ignore"):
        out[anchor:] = np.where(vol > 0, pv / vol, np.nan)
    return out


def volume_profile(bars: Bars, bins: int = 48) -> tuple[np.ndarray, np.ndarray]:
    """``(bin_centres, volume_at_price)`` over the window.

    Each bar's volume is spread uniformly across the bins its range covers,
    rather than dumped at its close. The difference is not cosmetic: on a wide
    trend day, close-weighting puts the day's entire volume at the extreme,
    which drags the POC to wherever the session happened to stop.
    """
    low, high = float(bars.low.min()), float(bars.high.max())
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        return np.array([]), np.array([])
    edges = np.linspace(low, high, bins + 1)
    centres = (edges[:-1] + edges[1:]) / 2
    profile = np.zeros(bins)
    width = (high - low) / bins
    for i in range(len(bars)):
        lo_idx = int(np.clip((bars.low[i] - low) / width, 0, bins - 1))
        hi_idx = int(np.clip((bars.high[i] - low) / width, 0, bins - 1))
        span = hi_idx - lo_idx + 1
        profile[lo_idx : hi_idx + 1] += bars.volume[i] / span
    return centres, profile


def value_area(
    centres: np.ndarray, profile: np.ndarray, coverage: float = 0.70
) -> tuple[float, float, float]:
    """``(poc, value_area_low, value_area_high)``.

    Standard market-profile construction: start at the POC and expand to
    whichever adjacent bin holds more volume until ``coverage`` of the total is
    enclosed. Expanding by volume rather than symmetrically is what makes the
    value area lopsided in the direction price actually spent time, which is the
    information in it.
    """
    if len(profile) == 0 or profile.sum() <= 0:
        return float("nan"), float("nan"), float("nan")
    poc_index = int(profile.argmax())
    target = profile.sum() * coverage
    total = profile[poc_index]
    low_index = high_index = poc_index
    while total < target and (low_index > 0 or high_index < len(profile) - 1):
        below = profile[low_index - 1] if low_index > 0 else -1.0
        above = profile[high_index + 1] if high_index < len(profile) - 1 else -1.0
        if above >= below:
            high_index += 1
            total += profile[high_index]
        else:
            low_index -= 1
            total += profile[low_index]
    return float(centres[poc_index]), float(centres[low_index]), float(centres[high_index])


def opening_range(bars: Bars, minutes: int = 30, bar_minutes: int = 5) -> tuple[float, float] | None:
    """The first ``minutes`` of the most recent session, as (low, high).

    Returns ``None`` rather than a guess when the series is not intraday or the
    last session is too short to contain the range. An ORB computed from a
    daily bar is a day's range wearing a different name, and drawing it as an
    opening range would be a lie told in a label.
    """
    if bar_minutes <= 0 or minutes < bar_minutes:
        return None
    sessions = bars.sessions()
    if not sessions:
        return None
    start, end = sessions[-1]
    count = minutes // bar_minutes
    if end - start + 1 < count or count < 1:
        return None
    window_high = float(bars.high[start : start + count].max())
    window_low = float(bars.low[start : start + count].min())
    return window_low, window_high
