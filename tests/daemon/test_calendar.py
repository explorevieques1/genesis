# Spec: Genesis Markdown/10-Architecture/Daemon And Cadence.md
"""The calendar must be real: holidays, half-days, DST."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from genesis.daemon import MarketCalendar, SessionState

ET = ZoneInfo("America/New_York")


@pytest.fixture(scope="module")
def cal() -> MarketCalendar:
    return MarketCalendar()


def at(y: int, m: int, d: int, hh: int, mm: int = 0) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, tzinfo=ET)


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (at(2026, 8, 31, 3, 59), SessionState.CLOSED),
        (at(2026, 8, 31, 4, 0), SessionState.PREMARKET),
        (at(2026, 8, 31, 9, 29), SessionState.PREMARKET),
        (at(2026, 8, 31, 9, 30), SessionState.OPEN),
        (at(2026, 8, 31, 15, 59), SessionState.OPEN),
        (at(2026, 8, 31, 16, 0), SessionState.AFTERHOURS),
        (at(2026, 8, 31, 19, 59), SessionState.AFTERHOURS),
        (at(2026, 8, 31, 20, 0), SessionState.CLOSED),
    ],
)
def test_session_boundaries(cal: MarketCalendar, when, expected) -> None:
    assert cal.state(when) is expected


def test_christmas_is_a_holiday_not_merely_closed(cal: MarketCalendar) -> None:
    """'Scans on Christmas' is the failure the note names."""
    assert cal.state(at(2026, 12, 25, 10, 0)) is SessionState.HOLIDAY
    assert not cal.is_session(dt.date(2026, 12, 25))


def test_weekend_is_closed_not_holiday(cal: MarketCalendar) -> None:
    """A holiday is worth announcing in the brief; a Saturday is not."""
    assert cal.state(at(2026, 8, 29, 10, 0)) is SessionState.CLOSED


@pytest.mark.parametrize(
    "day",
    [dt.date(2026, 1, 1), dt.date(2026, 7, 3), dt.date(2026, 12, 25)],
)
def test_known_market_holidays(cal: MarketCalendar, day: dt.date) -> None:
    assert not cal.is_session(day)


def test_half_day_is_detected_and_shortens_the_session(cal: MarketCalendar) -> None:
    """Day after Thanksgiving 2026 closes at 13:00 ET, not 16:00."""
    day = dt.date(2026, 11, 27)
    assert cal.is_session(day)
    assert cal.is_half_day(day)
    assert cal.session_close(day).hour == 13


def test_half_day_afternoon_is_afterhours_not_open(cal: MarketCalendar) -> None:
    """The bug this prevents: trading logic running after the bell."""
    assert cal.state(at(2026, 11, 27, 14, 0)) is SessionState.AFTERHOURS
    assert cal.state(at(2026, 11, 27, 12, 0)) is SessionState.OPEN


def test_normal_day_is_not_a_half_day(cal: MarketCalendar) -> None:
    assert not cal.is_half_day(dt.date(2026, 11, 25))


def test_dst_transition_keeps_the_open_at_0930_local(cal: MarketCalendar) -> None:
    """US DST starts 2026-03-08. The open is 09:30 ET on both sides of it."""
    before = cal.session_open(dt.date(2026, 3, 6))
    after = cal.session_open(dt.date(2026, 3, 9))
    assert (before.hour, before.minute) == (9, 30)
    assert (after.hour, after.minute) == (9, 30)
    assert before.utcoffset() != after.utcoffset(), "the UTC offset must shift"


def test_naive_datetime_is_rejected(cal: MarketCalendar) -> None:
    """Guessing a timezone is how a system scans at the wrong hour for months."""
    with pytest.raises(ValueError, match="timezone-aware"):
        cal.state(dt.datetime(2026, 8, 31, 10, 0))


def test_utc_input_is_converted_not_misread(cal: MarketCalendar) -> None:
    assert cal.state(dt.datetime(2026, 8, 31, 14, 0, tzinfo=dt.UTC)) is SessionState.OPEN


def test_market_hours_covers_premarket_and_afterhours() -> None:
    assert SessionState.PREMARKET.market_hours
    assert SessionState.OPEN.market_hours
    assert SessionState.AFTERHOURS.market_hours
    assert not SessionState.CLOSED.market_hours
    assert not SessionState.HOLIDAY.market_hours


def test_describe_announces_the_exception(cal: MarketCalendar) -> None:
    assert "holiday" in cal.describe(at(2026, 12, 25, 10, 0))
    assert "half day" in cal.describe(at(2026, 11, 27, 12, 0))
