# Spec: Genesis Markdown/10-Architecture/Markup Spec.md
"""Timeframes, as a closed set with arithmetic attached.

Every charting component needs the same three facts about a timeframe -- how
many minutes a bar covers, how far back it is worth looking, and how long a
level drawn on it stays relevant -- and each one was about to grow its own
table. One table, because three tables is three tables that disagree.

The relevance window is the one that is not obvious. Agent — Level Watcher
retires levels *"from a spec older than its timeframe's relevance window"*, and
that window is not a constant: a 5-minute level marked yesterday is archaeology,
a monthly level marked last quarter is current. Expressed in bars rather than
days so the rule reads the same on every timeframe -- a level is stale after
roughly the number of bars it took to form the swing that made it.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["TIMEFRAMES", "Timeframe", "normalise", "resolve"]


@dataclass(frozen=True)
class Timeframe:
    """One bar size, with the windows that depend on it."""

    label: str
    minutes: int
    #: Default bars to fetch when nobody says. Enough to see structure, few
    #: enough that the chart is legible at 1600x900 -- past ~400 candles the
    #: bodies are thinner than the level lines drawn over them.
    default_lookback_bars: int
    #: After this many bars, a level from this timeframe is retired.
    relevance_bars: int
    #: True where a session VWAP means anything. A daily VWAP is a number you
    #: can compute and nobody should draw.
    intraday: bool

    @property
    def is_intraday(self) -> bool:
        return self.intraday


TIMEFRAMES: dict[str, Timeframe] = {
    tf.label: tf
    for tf in (
        Timeframe("1m", 1, 390, 390, True),
        Timeframe("5m", 5, 390, 390, True),
        Timeframe("15m", 15, 260, 260, True),
        Timeframe("30m", 30, 260, 260, True),
        Timeframe("1H", 60, 300, 260, True),
        Timeframe("4H", 240, 300, 180, True),
        Timeframe("1D", 1440, 252, 120, False),
        Timeframe("1W", 10080, 260, 104, False),
        Timeframe("1M", 43200, 180, 60, False),
    )
}

#: What people and other systems actually write. TradingView says ``60``,
#: yfinance says ``1d``, a person says ``daily``. All three mean 1D, and the
#: place to resolve that is here rather than in five call sites.
_ALIASES = {
    "1": "1m", "1min": "1m", "minute": "1m",
    "5": "5m", "5min": "5m",
    "15": "15m", "15min": "15m",
    "30": "30m", "30min": "30m",
    "60": "1H", "1h": "1H", "hour": "1H", "hourly": "1H", "60m": "1H",
    "240": "4H", "4h": "4H",
    "d": "1D", "1d": "1D", "day": "1D", "daily": "1D",
    "w": "1W", "1w": "1W", "week": "1W", "weekly": "1W",
    "m": "1M", "1mo": "1M", "month": "1M", "monthly": "1M",
}


def normalise(value: str) -> str:
    """``"daily"`` -> ``"1D"``. Raises :class:`KeyError` on nonsense.

    Deliberately raises rather than defaulting to 1D. A silently coerced
    timeframe produces a chart of the wrong thing, correctly labelled, which is
    the hardest kind of wrong to notice.
    """
    raw = value.strip()
    if raw in TIMEFRAMES:
        return raw
    lowered = raw.lower()
    if lowered in _ALIASES:
        return _ALIASES[lowered]
    # "1D" written "1d" is the overwhelmingly common case and not worth an error.
    for label in TIMEFRAMES:
        if label.lower() == lowered:
            return label
    raise KeyError(f"unknown timeframe {value!r}; known: {', '.join(TIMEFRAMES)}")


def resolve(value: str) -> Timeframe:
    return TIMEFRAMES[normalise(value)]
