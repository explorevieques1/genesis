# Spec: Genesis Markdown/10-Architecture/Daemon And Cadence.md
"""Market session state.

*"The calendar must be real (market holidays, half-days, DST). Getting this
wrong means the system backtests during the open and scans on Christmas."*

So this wraps ``exchange_calendars`` rather than hand-rolling holiday rules.
Half-days fall out for free: the afterhours window is derived from the session's
*actual* close, so on the day after Thanksgiving the market closes at 13:00 ET
and Genesis knows it without a special case. DST is handled by using real
timezones throughout and never doing arithmetic on naive datetimes.

Session boundaries other than the regular open and close (premarket start,
afterhours end) are not in the exchange calendar -- they are venue conventions --
so they are constants here, expressed in market-local time.
"""

from __future__ import annotations

import datetime as dt
import functools
from enum import Enum
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

__all__ = ["MarketCalendar", "SessionState"]

PREMARKET_START = dt.time(4, 0)
AFTERHOURS_END = dt.time(20, 0)


class SessionState(str, Enum):
    """What the daemon does depends on which of these it is in."""

    PREMARKET = "premarket"
    OPEN = "open"
    AFTERHOURS = "afterhours"
    CLOSED = "closed"
    HOLIDAY = "holiday"

    @property
    def market_hours(self) -> bool:
        """Whether the ``market-open`` cadence runs.

        Premarket and afterhours count: the note's loop runs the market-open
        cadence for all three, because a gap scan at 08:00 is market work.
        """
        return self in (SessionState.PREMARKET, SessionState.OPEN, SessionState.AFTERHOURS)


class MarketCalendar:
    """Session state for one venue.

    Defaults to XNYS (US equities), matching Open Questions §1. Futures and
    crypto have different sessions; when §1 reopens, this becomes per-venue
    rather than global -- which is why the venue is a constructor argument and
    not a module constant.
    """

    def __init__(self, venue: str = "XNYS", tz: str = "America/New_York") -> None:
        self.venue = venue
        self.tz = ZoneInfo(tz)
        self._calendar = xcals.get_calendar(venue)

    # -- sessions ----------------------------------------------------------

    @functools.lru_cache(maxsize=512)  # noqa: B019 - bounded, keyed by date
    def _session_bounds(self, day: dt.date) -> tuple[dt.datetime, dt.datetime] | None:
        """Regular open and close for ``day`` in market time, or None if closed."""
        stamp = pd.Timestamp(day)
        if not self._calendar.is_session(stamp):
            return None
        return (
            self._calendar.session_open(stamp).to_pydatetime().astimezone(self.tz),
            self._calendar.session_close(stamp).to_pydatetime().astimezone(self.tz),
        )

    def is_session(self, day: dt.date) -> bool:
        return self._session_bounds(day) is not None

    def is_half_day(self, day: dt.date) -> bool:
        """A session that closes before the venue's usual time.

        Compared against the modal close of the surrounding year rather than a
        hard-coded 16:00, so this stays correct if the exchange changes hours.
        """
        bounds = self._session_bounds(day)
        if bounds is None:
            return False
        return bounds[1].timetz() < self._regular_close_time(day.year)

    @functools.lru_cache(maxsize=8)  # noqa: B019 - one entry per year
    def _regular_close_time(self, year: int) -> dt.time:
        closes = [
            self._calendar.session_close(s).to_pydatetime().astimezone(self.tz).timetz()
            for s in self._calendar.sessions_in_range(
                pd.Timestamp(f"{year}-01-01"), pd.Timestamp(f"{year}-12-31")
            )
        ]
        return max(set(closes), key=closes.count)

    def session_open(self, day: dt.date) -> dt.datetime | None:
        bounds = self._session_bounds(day)
        return bounds[0] if bounds else None

    def session_close(self, day: dt.date) -> dt.datetime | None:
        bounds = self._session_bounds(day)
        return bounds[1] if bounds else None

    # -- state -------------------------------------------------------------

    def state(self, when: dt.datetime) -> SessionState:
        """The session state at ``when``.

        ``when`` must be timezone-aware. A naive datetime is rejected rather
        than assumed to be local: guessing a timezone is how a system scans at
        the wrong hour for half the year.
        """
        if when.tzinfo is None:
            raise ValueError(
                "MarketCalendar.state requires a timezone-aware datetime; "
                "a naive one would be interpreted differently across DST"
            )
        local = when.astimezone(self.tz)
        bounds = self._session_bounds(local.date())

        if bounds is None:
            # A weekday the exchange is shut is a holiday and worth announcing
            # in the brief. A weekend is merely closed.
            return (
                SessionState.CLOSED
                if local.weekday() >= 5
                else SessionState.HOLIDAY
            )

        session_open, session_close = bounds
        if session_open <= local < session_close:
            return SessionState.OPEN

        premarket_start = local.replace(
            hour=PREMARKET_START.hour, minute=PREMARKET_START.minute,
            second=0, microsecond=0,
        )
        afterhours_end = local.replace(
            hour=AFTERHOURS_END.hour, minute=AFTERHOURS_END.minute,
            second=0, microsecond=0,
        )
        if premarket_start <= local < session_open:
            return SessionState.PREMARKET
        if session_close <= local < afterhours_end:
            return SessionState.AFTERHOURS
        return SessionState.CLOSED

    def describe(self, when: dt.datetime) -> str:
        """A line for the boot announcement and the daily brief."""
        state = self.state(when)
        local = when.astimezone(self.tz)
        if state is SessionState.HOLIDAY:
            return f"Market closed — holiday ({local:%A %d %B})"
        if self.is_half_day(local.date()):
            close = self.session_close(local.date())
            return f"Market {state.value} — half day, closes {close:%H:%M %Z}"
        return f"Market {state.value}"
