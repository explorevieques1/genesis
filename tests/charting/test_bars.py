# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""Parsing: three vendor shapes, one fact — and never an invented bar."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from genesis.charting.bars import BarParseError, parse_bars

RECORDS = [
    {"Date": "2026-01-05", "Open": 10, "High": 12, "Low": 9, "Close": 11, "Volume": 100},
    {"Date": "2026-01-02", "Open": 9, "High": 11, "Low": 8, "Close": 10, "Volume": 90},
]


def _parse(payload):
    return parse_bars(payload, symbol="nvda", timeframe="1D", source="test")


def test_records_list() -> None:
    bars = _parse(RECORDS)
    assert len(bars) == 2
    assert bars.symbol == "NVDA"
    assert bars.last == 11.0


def test_out_of_order_bars_are_sorted_and_the_fact_is_recorded() -> None:
    """Sorting silently would hide a vendor that shuffles other things too."""
    bars = _parse(RECORDS)
    assert bars.times[0] < bars.times[1]
    assert bars.resorted is True


def test_json_wrapped_in_prose_and_a_fence() -> None:
    payload = "Here are the bars:\n```json\n" + json.dumps(RECORDS) + "\n```"
    assert len(_parse(payload)) == 2


def test_column_orientation() -> None:
    payload = {
        "Date": ["2026-01-02", "2026-01-05"],
        "Open": [9, 10], "High": [11, 12], "Low": [8, 9],
        "Close": [10, 11], "Volume": [90, 100],
    }
    assert _parse(payload).last == 11.0


def test_date_keyed_mapping() -> None:
    payload = {
        "2026-01-02": {"open": 9, "high": 11, "low": 8, "close": 10, "volume": 90},
        "2026-01-05": {"open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
    }
    assert len(_parse(payload)) == 2


def test_a_wrapper_key_is_unwrapped() -> None:
    assert len(_parse({"bars": RECORDS})) == 2


def test_epoch_timestamps_in_seconds_and_milliseconds() -> None:
    seconds = [{**RECORDS[1], "Date": 1767312000}]
    millis = [{**RECORDS[1], "Date": 1767312000000}]
    assert _parse(seconds).times[0] == _parse(millis).times[0]


def test_a_missing_price_is_a_failure_not_a_zero() -> None:
    """Never invent a bar. A substituted zero becomes a level computed from nothing."""
    with pytest.raises(BarParseError):
        _parse([{"Date": "2026-01-02", "Open": 9, "High": 11, "Low": 8, "Volume": 90}])


def test_a_null_price_is_a_failure() -> None:
    with pytest.raises(BarParseError, match="unreadable bar"):
        _parse([{**RECORDS[0], "Close": None}])


def test_high_below_low_is_corrupt_not_odd() -> None:
    with pytest.raises(BarParseError, match="below low"):
        _parse([{**RECORDS[0], "High": 5, "Low": 9}])


def test_an_empty_payload_fails_rather_than_returning_nothing() -> None:
    with pytest.raises(BarParseError):
        _parse([])


def test_non_json_text_fails() -> None:
    with pytest.raises(BarParseError, match="not JSON"):
        _parse("the market was closed today")


def test_sessions_split_on_the_date_not_a_bar_count(intraday) -> None:
    """Half-days exist; a fixed bar count anchors VWAP to the wrong bar."""
    sessions = intraday.sessions()
    assert len(sessions) == 3
    assert all(end >= start for start, end in sessions)


def test_tail_preserves_provenance(trending) -> None:
    tail = trending.tail(30)
    assert len(tail) == 30
    assert tail.source == trending.source
    assert tail.tier == trending.tier
