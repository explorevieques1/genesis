# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""OHLCV bars, and the one place a vendor's shape becomes ours.

Market Data Plane.md puts ``normalize.py`` between every adapter and the store
for a reason that applies with full force here even though the store does not
exist yet: **every vendor answers the same question with a different shape.**
yfinance returns a records list keyed ``Date/Open/High/Low/Close/Volume``,
maverick's batch endpoint returns columns, an MCP server returns any of those
wrapped in a JSON string inside a text block. Three shapes, one fact.

If each caller parsed for itself, the parsing would be re-derived in the level
computer, the renderer, the structure engine and every agent -- and they would
disagree at the edges, which for market data means disagreeing about a price.

Two rules this module will not bend on, both from
[[Error Handling And Degradation]]:

**Never invent a bar.** A missing field is a :class:`BarParseError`, never a
zero and never a forward-fill. A zero volume bar is a real thing; a zero volume
bar that was actually a parse failure is a level computed from nothing.

**Never reorder silently.** Bars arrive out of order often enough to matter, and
every computation downstream assumes chronological order. So this sorts, and
records that it sorted, rather than assuming the vendor was tidy.

Numpy arrays rather than a DataFrame: the whole numeric path here is
element-wise arithmetic over a few hundred floats, pandas is already a
transitive dependency but a DataFrame per timeframe per symbol per agent is
overhead nobody is buying anything with, and numpy is already core.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable, Sequence

import numpy as np

from genesis.errors import DegradedError

__all__ = ["Bars", "BarParseError", "parse_bars"]


class BarParseError(DegradedError):
    """The payload was not bars.

    ``degraded`` rather than ``fatal``: one unreadable vendor response is a
    reason to fall down the chain, not a reason to stop the task. The agent
    proceeds with less, and says so.
    """


#: Every spelling of each field seen across the wired free servers, lowercased.
#: Order matters -- the first match wins, so the unambiguous names come first.
_FIELDS: dict[str, tuple[str, ...]] = {
    "time": ("date", "datetime", "timestamp", "time", "t", "index"),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "adj close", "adjclose", "adj_close", "c"),
    "volume": ("volume", "vol", "v"),
}


@dataclass(frozen=True)
class Bars:
    """A chronological OHLCV window for one symbol and timeframe."""

    symbol: str
    timeframe: str
    times: tuple[datetime, ...]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    source: str = "unknown"
    #: Market Data Sources' trust tier, carried with the data rather than
    #: alongside it. A level computed from tier-3 bars is a tier-3 level, and
    #: whatever speaks it has to be able to say so.
    tier: int = 3
    adjusted: bool = True
    #: True when the payload arrived out of order. Not an error, but worth
    #: recording: a vendor that shuffles bars may be shuffling other things.
    resorted: bool = False

    def __post_init__(self) -> None:
        n = len(self.times)
        for name in ("open", "high", "low", "close", "volume"):
            arr = getattr(self, name)
            if len(arr) != n:
                raise BarParseError(
                    f"{self.symbol}: {name} has {len(arr)} values for {n} bars"
                )
        if n == 0:
            raise BarParseError(f"{self.symbol}: no bars")

    def __len__(self) -> int:
        return len(self.times)

    # -- windows -----------------------------------------------------------

    def tail(self, n: int) -> Bars:
        """The last ``n`` bars. ``n`` larger than the window returns all of it."""
        if n >= len(self):
            return self
        return Bars(
            symbol=self.symbol,
            timeframe=self.timeframe,
            times=self.times[-n:],
            open=self.open[-n:],
            high=self.high[-n:],
            low=self.low[-n:],
            close=self.close[-n:],
            volume=self.volume[-n:],
            source=self.source,
            tier=self.tier,
            adjusted=self.adjusted,
            resorted=self.resorted,
        )

    @property
    def last(self) -> float:
        return float(self.close[-1])

    @property
    def first_time(self) -> datetime:
        return self.times[0]

    @property
    def last_time(self) -> datetime:
        return self.times[-1]

    @property
    def typical(self) -> np.ndarray:
        """(H+L+C)/3 — the price VWAP and volume profile are computed against."""
        return (self.high + self.low + self.close) / 3.0

    @property
    def returns(self) -> np.ndarray:
        """Simple bar-over-bar returns, length n-1."""
        return np.diff(self.close) / self.close[:-1]

    def index_of(self, when: datetime) -> int:
        """Nearest bar index at or before ``when``. Clamped to the window.

        Clamping rather than raising because the caller is usually placing a
        trendline anchor or an event marker, and an anchor a day outside the
        window should pin to the edge of the chart rather than fail the render.
        """
        if when <= self.times[0]:
            return 0
        if when >= self.times[-1]:
            return len(self) - 1
        for i in range(len(self) - 1, -1, -1):
            if self.times[i] <= when:
                return i
        return 0

    def sessions(self) -> list[tuple[int, int]]:
        """``(start, end)`` index pairs, one per calendar day.

        Session VWAP, the opening range and prior-day levels all need to know
        where a day begins, and on an intraday series that is a date change in
        the timestamps -- not a fixed bar count, because half-days exist and a
        fixed count would silently anchor VWAP to the wrong bar on every one.
        """
        out: list[tuple[int, int]] = []
        start = 0
        for i in range(1, len(self)):
            if self.times[i].date() != self.times[i - 1].date():
                out.append((start, i - 1))
                start = i
        out.append((start, len(self) - 1))
        return out

    def to_records(self) -> list[dict[str, Any]]:
        return [
            {
                "time": self.times[i].isoformat(),
                "open": float(self.open[i]),
                "high": float(self.high[i]),
                "low": float(self.low[i]),
                "close": float(self.close[i]),
                "volume": float(self.volume[i]),
            }
            for i in range(len(self))
        ]


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def parse_bars(
    payload: Any,
    *,
    symbol: str,
    timeframe: str,
    source: str = "unknown",
    tier: int = 3,
    adjusted: bool = True,
) -> Bars:
    """Whatever a tool returned -> :class:`Bars`, or a typed failure.

    Accepts: a JSON string (possibly wrapped in prose or a markdown fence, which
    is what an MCP text block often is), a list of records, a dict of columns,
    or a dict with the records under some obvious key.
    """
    data = _unwrap(payload)
    records = _to_records(data)
    if not records:
        raise BarParseError(f"{symbol}: payload contained no bars")

    keys = _field_map(records[0])
    missing = [f for f in ("open", "high", "low", "close") if f not in keys]
    if missing:
        raise BarParseError(
            f"{symbol}: bars are missing {', '.join(missing)} — "
            f"got fields {sorted(records[0])}"
        )

    rows: list[tuple[datetime, float, float, float, float, float]] = []
    for raw in records:
        try:
            when = _time_of(raw, keys)
            o = _num(raw[keys["open"]])
            h = _num(raw[keys["high"]])
            lo = _num(raw[keys["low"]])
            c = _num(raw[keys["close"]])
            v = _num(raw[keys["volume"]]) if "volume" in keys else 0.0
        except (KeyError, TypeError, ValueError) as exc:
            raise BarParseError(f"{symbol}: unreadable bar {raw!r}: {exc}") from exc
        # A bar whose high is below its low is corrupt, not merely odd, and
        # every level computed from the window would inherit the corruption.
        if h < lo:
            raise BarParseError(f"{symbol}: bar at {when} has high {h} below low {lo}")
        rows.append((when, o, h, lo, c, v))

    ordered = sorted(rows, key=lambda r: r[0])
    resorted = ordered != rows

    return Bars(
        symbol=symbol.upper(),
        timeframe=timeframe,
        times=tuple(r[0] for r in ordered),
        open=np.array([r[1] for r in ordered], dtype=float),
        high=np.array([r[2] for r in ordered], dtype=float),
        low=np.array([r[3] for r in ordered], dtype=float),
        close=np.array([r[4] for r in ordered], dtype=float),
        volume=np.array([r[5] for r in ordered], dtype=float),
        source=source,
        tier=tier,
        adjusted=adjusted,
        resorted=resorted,
    )


def _unwrap(payload: Any) -> Any:
    """Get to the JSON inside a tool's text response.

    An MCP text block is a string that *usually* is JSON and sometimes is JSON
    with a sentence in front of it or a markdown fence around it. Rather than
    trust any one of those, find the outermost bracketed region and parse that.
    """
    if not isinstance(payload, (str, bytes)):
        return payload
    text = payload.decode() if isinstance(payload, bytes) else payload
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise BarParseError("tool response was not JSON and contained no JSON")


def _to_records(data: Any) -> list[dict[str, Any]]:
    """Records, columns, or a wrapper around either -> a records list."""
    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            return data
        raise BarParseError("expected a list of bar objects")
    if not isinstance(data, dict):
        raise BarParseError(f"expected bars, got {type(data).__name__}")

    # A wrapper: {"bars": [...]}, {"data": {...}}, {"history": [...]}.
    for key in ("bars", "data", "history", "prices", "candles", "results", "ohlcv"):
        if key in data:
            return _to_records(data[key])

    lowered = {str(k).lower(): k for k in data}
    if all(f in lowered for f in ("open", "high", "low", "close")):
        # Column orientation: {"Open": [...], "Close": [...]}.
        columns = {f: data[lowered[f]] for f in lowered}
        length = len(next(iter(columns.values())))
        if any(len(v) != length for v in columns.values()):
            raise BarParseError("column-oriented bars have unequal lengths")
        index = data.get(lowered.get("date") or lowered.get("index") or "", None)
        out = []
        for i in range(length):
            row = {k: v[i] for k, v in columns.items()}
            if index is not None:
                row["date"] = index[i]
            out.append(row)
        return out

    # A date-keyed mapping: {"2026-01-02": {...}}.
    if data and all(isinstance(v, dict) for v in data.values()):
        return [{"date": k, **v} for k, v in data.items()]

    raise BarParseError(f"could not find bars in payload keys {sorted(data)}")


def _field_map(row: dict[str, Any]) -> dict[str, str]:
    lowered = {str(k).strip().lower(): k for k in row}
    out: dict[str, str] = {}
    for field, spellings in _FIELDS.items():
        for spelling in spellings:
            if spelling in lowered:
                out[field] = lowered[spelling]
                break
    return out


def _time_of(row: dict[str, Any], keys: dict[str, str]) -> datetime:
    if "time" not in keys:
        raise ValueError("no timestamp field")
    return _parse_time(row[keys["time"]])


def _parse_time(value: Any) -> datetime:
    """Epoch seconds, epoch millis, or an ISO-ish string -> aware UTC datetime.

    Naive timestamps are assumed UTC rather than local. That is the honest
    default for a vendor that did not say: guessing the desk's timezone would
    shift every intraday session boundary by hours and corrupt session VWAP.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 1e11:  # milliseconds
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=UTC)
    text = str(value).strip()
    if text.isdigit():
        return _parse_time(int(text))
    cleaned = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"unparseable timestamp {value!r}") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _num(value: Any) -> float:
    """A number, or a loud failure. Never a substituted zero."""
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{value!r} is not a price")
    if isinstance(value, (int, float)):
        out = float(value)
    else:
        out = float(str(value).replace(",", "").replace("$", "").strip())
    if math.isnan(out) or math.isinf(out):
        raise ValueError(f"{value!r} is not finite")
    return out
