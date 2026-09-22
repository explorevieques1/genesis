# Spec: Genesis Markdown/60-UI/Candle Ranges.md
"""Candle ranges: a named snippet of price, kept for study.

A range is one window of bars — *"ES, 5-minute, 8 Sep 2026 09:30 to 11:05"* —
downloaded once, named, and thereafter frozen. It exists because reviewing a
setup you took is a different job from holding market history: you want the
forty bars around the trade, under a name you chose, and you want them to look
the same next month.

**Deliberately not the bar store.** :mod:`genesis.marketdata.store` is the
record of what the world did: canonical symbol ids, immutable closed bars,
restatement tracking, coverage. Ranges are none of that — they are the trader's
own scrapbook, keyed by whatever ticker the vendor answers to, and losing this
database costs some snippets and no history. Same lifecycle as the watchlist
store, and built the same way.

That separation is what lets ``ES=F`` in. Yahoo's ``ES=F`` is a **continuous
front-month series with an undocumented roll** — see the refusal in
:mod:`genesis.marketdata.adapters.yfinance` and Open Questions §13 — so it must
never be written into the bar store beside a dated contract. As a named
scrapbook page labelled with the vendor ticker it came from, it is exactly what
it says it is and corrupts nothing.

Bars are read back through ``CR:<range_id>`` on the ordinary market routes, so
the chart draws a range with no idea it is doing anything unusual.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from genesis.errors import DegradedError
from genesis.ids import new_id
from genesis.marketdata.adapters.yfinance import INTERVALS
from genesis.marketdata.normalize import to_decimal
from genesis.memory.db import connect, transaction

__all__ = ["RangeStore", "SCHEMA", "DEFAULT_TZ", "parse_window"]

#: Where a trader means when they say "9:30". Overridable per range, because
#: the point of a range is a window a person picked off a chart, and the chart
#: was in exchange time.
DEFAULT_TZ = "America/New_York"

SCHEMA = """
CREATE TABLE IF NOT EXISTS candle_ranges (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    ticker    TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    start     TEXT NOT NULL,
    "end"     TEXT NOT NULL,
    tz        TEXT NOT NULL,
    source    TEXT NOT NULL,
    tier      INTEGER NOT NULL,
    bars      INTEGER NOT NULL DEFAULT 0,
    created   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candle_range_bars (
    range_id TEXT NOT NULL REFERENCES candle_ranges(id) ON DELETE CASCADE,
    ts       TEXT NOT NULL,
    open     TEXT NOT NULL,
    high     TEXT NOT NULL,
    low      TEXT NOT NULL,
    close    TEXT NOT NULL,
    volume   TEXT NOT NULL,
    PRIMARY KEY (range_id, ts)
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_window(start: str, end: str, tz: str = DEFAULT_TZ) -> tuple[datetime, datetime]:
    """Two local wall-clock stamps -> UTC. Naive input means *that* zone.

    A window typed as "09:30" is 09:30 where the trader was looking, and the
    zone is carried on the range rather than assumed later — the same DST-
    shifted hour is two different clock times in June and December.
    """
    try:
        zone = ZoneInfo(tz)
    except Exception as exc:  # ZoneInfoNotFoundError and friends
        raise DegradedError(f"unknown timezone {tz!r}") from exc
    out = []
    for label, raw in (("start", start), ("end", end)):
        try:
            stamp = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise DegradedError(
                f"{label} {raw!r} is not a date-time — use 2026-09-08T09:30"
            ) from exc
        out.append(stamp.astimezone(UTC) if stamp.tzinfo else stamp.replace(tzinfo=zone).astimezone(UTC))
    if out[1] <= out[0]:
        raise DegradedError("the range ends before it starts")
    return out[0], out[1]


def fetch_window(
    ticker: str, timeframe: str, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    """Bars for one window from Yahoo. Tier 3, and labelled as such.

    Straight to yfinance rather than through the adapter chain: the chain is
    keyed by canonical symbol id and correctly refuses ``ES=F``, which is the
    single thing this module exists to allow. What comes back is stamped with
    the vendor ticker it was asked for and nothing more is claimed about it.
    """
    interval = INTERVALS.get(timeframe)
    if interval is None:
        raise DegradedError(
            f"{timeframe} is not a timeframe yfinance serves "
            f"({', '.join(INTERVALS)})"
        )
    try:
        import yfinance
    except ImportError as exc:
        raise DegradedError(
            "the `yfinance` package is not installed; `uv pip install yfinance`"
        ) from exc

    try:
        frame = yfinance.Ticker(ticker).history(
            start=start, end=end, interval=interval, auto_adjust=True, raise_errors=True,
        )
    except Exception as exc:
        raise DegradedError(f"yfinance failed for {ticker}: {exc}") from exc

    if frame.empty:
        raise DegradedError(
            f"no {timeframe} bars for {ticker} in that window. Yahoo keeps "
            f"intraday history briefly — 30 days for 1m, 60 for 5m and 15m — "
            f"so an older window is gone rather than empty."
        )

    rows = []
    for index, row in frame.iterrows():
        stamp = index.to_pydatetime()
        stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)
        rows.append({
            "ts": stamp,
            "open": to_decimal(row["Open"]),
            "high": to_decimal(row["High"]),
            "low": to_decimal(row["Low"]),
            "close": to_decimal(row["Close"]),
            "volume": to_decimal(row.get("Volume", 0), field="volume"),
        })
    return rows


class RangeStore:
    """Opened per request, like every other surface store."""

    def __init__(self, path: Path | str, *, conn: sqlite3.Connection | None = None) -> None:
        self.path = path
        self._conn = conn if conn is not None else connect(path)
        self._conn.executescript(SCHEMA)

    # -- writes ------------------------------------------------------------

    def create(
        self,
        *,
        name: str,
        ticker: str,
        timeframe: str,
        start: str,
        end: str,
        tz: str = DEFAULT_TZ,
    ) -> str:
        """Download a window and save it under a name. Fetches, so it is slow."""
        ticker = (ticker or "").strip().upper()
        if not ticker:
            raise DegradedError("a range needs a ticker")
        begin, finish = parse_window(start, end, tz)
        bars = fetch_window(ticker, timeframe, begin, finish)
        # Yahoo's window is half-open and coarse; trim to what was asked for so
        # the saved range is the range on screen, not the bars around it.
        bars = [b for b in bars if begin <= b["ts"] <= finish]
        if not bars:
            raise DegradedError(
                f"{ticker}: bars came back, but none inside "
                f"{begin:%Y-%m-%d %H:%M}–{finish:%H:%M} UTC"
            )

        rid = new_id("cr")
        with transaction(self._conn) as tx:
            tx.execute(
                'INSERT INTO candle_ranges (id, name, ticker, timeframe, start, "end",'
                " tz, source, tier, bars, created) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (rid, (name or "").strip() or f"{ticker} {timeframe}", ticker, timeframe,
                 begin.isoformat(), finish.isoformat(), tz, "yfinance", 3, len(bars), _now()),
            )
            tx.executemany(
                "INSERT INTO candle_range_bars (range_id, ts, open, high, low, close,"
                " volume) VALUES (?,?,?,?,?,?,?)",
                [(rid, b["ts"].isoformat(), str(b["open"]), str(b["high"]),
                  str(b["low"]), str(b["close"]), str(b["volume"])) for b in bars],
            )
        return rid

    def rename(self, range_id: str, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        with transaction(self._conn) as tx:
            return tx.execute(
                "UPDATE candle_ranges SET name = ? WHERE id = ?", (name, range_id)
            ).rowcount > 0

    def delete(self, range_id: str) -> bool:
        with transaction(self._conn) as tx:
            return tx.execute(
                "DELETE FROM candle_ranges WHERE id = ?", (range_id,)
            ).rowcount > 0

    # -- reads -------------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM candle_ranges ORDER BY created DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, range_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM candle_ranges WHERE id = ?", (range_id,)
        ).fetchone()
        return dict(row) if row else None

    def bars(self, range_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM candle_range_bars WHERE range_id = ? ORDER BY ts",
            (range_id,),
        ).fetchall()
        return [dict(r) for r in rows]
