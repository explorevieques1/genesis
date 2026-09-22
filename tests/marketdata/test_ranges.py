# Spec: Genesis Markdown/60-UI/Candle Ranges.md
"""Candle ranges: the window arithmetic, and one round trip.

No network. ``fetch_window`` is replaced, because what this file has to prove is
that a wall-clock window becomes the right UTC instants and that the bars come
back trimmed to it -- not that Yahoo answers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from genesis.errors import DegradedError
from genesis.marketdata import ranges as mod
from genesis.marketdata.ranges import RangeStore, parse_window


def test_naive_times_are_exchange_local() -> None:
    start, end = parse_window("2026-09-08T09:30", "2026-09-08T11:05")
    # 09:30 New York in September is 13:30 UTC.
    assert (start.hour, start.minute) == (13, 30)
    assert end - start == timedelta(minutes=95)


def test_backwards_window_is_refused() -> None:
    with pytest.raises(DegradedError):
        parse_window("2026-09-08T11:05", "2026-09-08T09:30")


def test_round_trip_trims_to_the_window(tmp_path, monkeypatch) -> None:
    base = datetime(2026, 9, 8, 13, 30, tzinfo=UTC)

    def fake_fetch(ticker, timeframe, start, end):
        assert ticker == "ES=F" and timeframe == "5m"
        # One bar before the window, three inside it.
        return [
            {"ts": base + timedelta(minutes=5 * i), "open": Decimal("4512.25"),
             "high": Decimal("4513"), "low": Decimal("4511"),
             "close": Decimal("4512.75"), "volume": Decimal("100")}
            for i in range(-1, 3)
        ]

    monkeypatch.setattr(mod, "fetch_window", fake_fetch)
    store = RangeStore(tmp_path / "ranges.db")
    rid = store.create(
        name="ES gap fill", ticker="es=f", timeframe="5m",
        start="2026-09-08T09:30", end="2026-09-08T09:40",
    )

    bars = store.bars(rid)
    assert len(bars) == 3
    # Decimal survives the trip as text -- a quarter-point future is the case
    # float would break, and 4512.25 must come back exactly.
    assert bars[0]["open"] == "4512.25"
    row = store.get(rid)
    assert row["name"] == "ES gap fill" and row["ticker"] == "ES=F"
    assert row["bars"] == 3 and row["tier"] == 3

    assert store.rename(rid, "ES 8 Sep gap fill")
    assert store.list()[0]["name"] == "ES 8 Sep gap fill"
    assert store.delete(rid)
    assert store.list() == [] and store.bars(rid) == []
