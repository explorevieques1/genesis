# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""Staleness: the reflex that stops an old price being spoken as a current one."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from genesis.errors import DegradedError
from genesis.marketdata.staleness import assess

NOW = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)


def test_the_forming_bar_is_not_stale():
    """A one-period lag is the normal, healthy state of a working feed.
    Flagging it would mean flagging every read, and a warning that always
    fires is a warning nobody reads."""
    f = assess(NOW - timedelta(minutes=1), "1m", now=NOW)
    assert not f.is_stale
    assert f.label == "fresh"


def test_the_same_age_means_different_things_on_different_timeframes():
    """Four minutes is stale on a 1m chart and brand new on a monthly one.
    This is the whole reason the threshold is in bars rather than minutes."""
    age = timedelta(minutes=4)
    assert assess(NOW - age, "1m", now=NOW).is_stale
    assert not assess(NOW - age, "1D", now=NOW).is_stale
    assert not assess(NOW - age, "1M", now=NOW).is_stale


def test_very_stale_is_a_different_response_from_stale():
    assert assess(NOW - timedelta(minutes=3), "1m", now=NOW).is_stale
    assert not assess(NOW - timedelta(minutes=3), "1m", now=NOW).is_very_stale
    assert assess(NOW - timedelta(hours=2), "1m", now=NOW).is_very_stale


def test_a_very_stale_read_refuses_to_be_presented_as_current():
    f = assess(NOW - timedelta(days=30), "1D", now=NOW, source="yfinance")
    with pytest.raises(DegradedError, match="refusing"):
        f.raise_if_very_stale()


def test_a_fresh_read_never_raises():
    assess(NOW - timedelta(hours=6), "1D", now=NOW).raise_if_very_stale()


def test_the_spoken_form_names_the_age_and_the_source():
    """Market Data Sources: "that's from four minutes ago, TradingView isn't
    updating." The source is what makes it actionable."""
    f = assess(NOW - timedelta(minutes=4), "1m", now=NOW, source="tradingview")
    spoken = f.spoken("the high of day")
    assert "4 minutes" in spoken
    assert "tradingview" in spoken


def test_fresh_data_still_reports_its_age():
    f = assess(NOW - timedelta(seconds=20), "1m", now=NOW)
    assert "moment ago" in f.spoken()


def test_a_session_clock_stops_the_weekend_looking_like_an_outage():
    """Daily bars on a Monday morning are 2.5 days old and perfectly fresh.
    A naive check screams every weekend, everyone learns to ignore it, and
    then it fails to scream on the Tuesday the feed is actually dead."""
    friday_close = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
    monday_open = datetime(2026, 9, 7, 13, 30, tzinfo=UTC)

    naive = assess(friday_close, "1H", now=monday_open)
    assert naive.is_very_stale  # wall clock: 65 hours, looks broken

    class MarketClosedAllWeekend:
        def session_minutes_between(self, start, end):
            return 30.0  # the market has been open half an hour

    aware = assess(
        friday_close, "1H", now=monday_open, clock=MarketClosedAllWeekend()
    )
    assert not aware.is_stale
    assert aware.session_aware


def test_provenance_travels_with_the_freshness():
    f = assess(NOW, "1D", now=NOW, source="databento", tier=2)
    assert (f.source, f.tier) == ("databento", 2)
