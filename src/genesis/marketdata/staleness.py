# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""Every read reports its age.

Safety Invariants §10 forbids confabulation, and Market Data Sources states the
consequence in one line: *"an unlabelled stale price is a confabulation."* Not a
minor inaccuracy -- a confabulation, in the same class as an invented number,
because a listener told "ES is at 4512" has been told something false if that
price is from Friday.

So staleness is not a warning that some callers may choose to check. It is a
value that travels with every read, and the thing that speaks is required to
have it.

**The threshold is in bars, not minutes**, and that is the design decision worth
defending. A 1-minute bar four minutes old is stale; a monthly bar four minutes
old is brand new. Expressing the limit as a multiple of the bar's own period
makes one rule correct on every timeframe --
:mod:`genesis.charting.timeframes` already makes the same argument for level
relevance, and this is the same shape of problem.

**Weekends and holidays are the trap.** Daily bars on a Monday morning are two
and a half days old and perfectly fresh, because the market was shut. A naive
age check screams every weekend, everyone learns to ignore it, and then it does
not scream on the Tuesday when the feed is genuinely dead. That is a worse
outcome than no check at all, so :func:`assess` takes an optional session
calendar and measures age in *session* time when it has one.

This is a **reflex**: ``tier: none``, deterministic, no model. Whether a price
is too old to say out loud is arithmetic. A model asked the same question could
be persuaded that the number is probably still fine, and that is exactly the
failure this exists to make impossible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from genesis.charting.timeframes import resolve

__all__ = ["Freshness", "SessionClock", "assess", "STALE_AFTER_BARS", "VERY_STALE_AFTER_BARS"]

#: A bar is stale once this many of its own periods have passed since it closed.
#: Two rather than one: the current bar is always forming, so a one-period lag
#: is the normal, healthy state of any correctly-working feed. Flagging it would
#: mean flagging every read.
STALE_AFTER_BARS = 2.0

#: Past this, it is not lag -- something is broken. Different word, different
#: response: `stale` labels the answer, `very_stale` is worth an alert.
VERY_STALE_AFTER_BARS = 10.0


class SessionClock(Protocol):
    """Anything that can say how much *market time* passed between two moments.

    Deliberately narrow. ``daemon/calendar.py`` already owns the real exchange
    calendar and this module has no business duplicating it -- it only needs to
    ask one question, so it asks for one method.
    """

    def session_minutes_between(self, start: datetime, end: datetime) -> float: ...


@dataclass(frozen=True)
class Freshness:
    """How old a read is, and whether that is a problem.

    Carries the sentence a voice answer should use, because the alternative is
    every caller inventing its own phrasing and one of them eventually
    inventing a phrasing that omits the age.
    """

    as_of: datetime
    checked_at: datetime
    timeframe: str
    age: timedelta
    #: Age in bar periods -- the number the thresholds are actually compared to.
    age_bars: float
    is_stale: bool
    is_very_stale: bool
    source: str = "unknown"
    tier: int = 3
    #: True when the age was measured against a market calendar rather than the
    #: wall clock. Recorded because "3 days old" means something very different
    #: over a weekend, and a caller may need to know which kind of age this is.
    session_aware: bool = False

    @property
    def label(self) -> str:
        """One word for a UI badge or a log line."""
        if self.is_very_stale:
            return "very stale"
        return "stale" if self.is_stale else "fresh"

    def spoken(self, subject: str = "that") -> str:
        """How to say the age out loud, per Market Data Sources §Staleness.

        Fresh data still names its age when asked -- it just does so briefly.
        The stale phrasing names the *source* too, because "TradingView isn't
        updating" is actionable and "that's old" is not.
        """
        minutes = self.age.total_seconds() / 60
        if not self.is_stale:
            if minutes < 2:
                return f"{subject} is current, as of a moment ago"
            return f"{subject} is from {_human(self.age)} ago"
        return (
            f"{subject} is from {_human(self.age)} ago — "
            f"{self.source} may not be updating"
        )

    def raise_if_very_stale(self) -> None:
        """Fail closed rather than speak a number nobody should act on.

        Used by callers that size or alert. Reading is always allowed; it is
        *acting* on a very stale price that has to be impossible.
        """
        if self.is_very_stale:
            from genesis.errors import DegradedError

            raise DegradedError(
                f"{self.source} data is {_human(self.age)} old "
                f"({self.age_bars:.0f} {self.timeframe} bars); refusing to "
                f"present it as current",
                spoken_summary=f"My {self.source} data is {_human(self.age)} old.",
            )


def assess(
    as_of: datetime,
    timeframe: str,
    *,
    now: datetime | None = None,
    source: str = "unknown",
    tier: int = 3,
    clock: SessionClock | None = None,
) -> Freshness:
    """How old is this, in units that mean something for this timeframe?

    ``as_of`` is normally the last bar's timestamp. Pass a ``clock`` and the age
    is measured in session minutes, which is what stops every Monday morning
    from looking like an outage.
    """
    now = now or datetime.now(UTC)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    age = now - as_of

    tf = resolve(timeframe)
    if clock is not None:
        elapsed_minutes = clock.session_minutes_between(as_of, now)
        session_aware = True
    else:
        elapsed_minutes = age.total_seconds() / 60
        session_aware = False

    age_bars = elapsed_minutes / tf.minutes
    return Freshness(
        as_of=as_of,
        checked_at=now,
        timeframe=tf.label,
        age=age,
        age_bars=age_bars,
        is_stale=age_bars > STALE_AFTER_BARS,
        is_very_stale=age_bars > VERY_STALE_AFTER_BARS,
        source=source,
        tier=tier,
        session_aware=session_aware,
    )


def _human(delta: timedelta) -> str:
    """A duration as a person would say it. Never more precise than it is sure."""
    seconds = max(0.0, delta.total_seconds())
    if seconds < 90:
        return f"{int(seconds)} seconds"
    minutes = seconds / 60
    if minutes < 90:
        return f"{int(minutes)} minutes"
    hours = minutes / 60
    if hours < 36:
        return f"{int(hours)} hours"
    return f"{int(hours / 24)} days"
