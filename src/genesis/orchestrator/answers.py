# Spec: Genesis Markdown/10-Architecture/Orchestrator.md
"""Trivial answers -- the ones that must never touch a model.

Orchestrator.md: *"Trivial requests skip planning -- 'what time is it' needs no
task list."* LLM Model Tiers adds the general rule: **default down**, start at
the cheapest tier that can plausibly do the job.

For a class of questions the cheapest tier is *no tier*. "What time does the
market open" has an exact answer that :mod:`genesis.daemon.calendar` already
computes from a real exchange calendar including holidays and half-days. Asking
a language model instead would be slower, occasionally wrong about a holiday,
and -- since the calendar is right there -- a strictly worse answer to a
question about a fact.

This module is the orchestrator's reflex arc: pattern in, sentence out, no
network. It is also what makes the Phase 2 exit criterion demonstrable without
any of Phase 4's agents existing yet.

Everything here returns text destined for :func:`~genesis.voice.speech.speakable`,
so times and numbers are written plainly and rendered on the way to the voice.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass

from genesis.daemon.calendar import MarketCalendar, SessionState

__all__ = ["Answer", "TrivialAnswerer"]


@dataclass(frozen=True)
class Answer:
    text: str
    #: What produced it, for the trace. Never a model, in this module.
    source: str


class TrivialAnswerer:
    """Deterministic answers to questions about time and session state."""

    def __init__(self, calendar: MarketCalendar | None = None, *, now: Callable[[], dt.datetime] | None = None) -> None:
        self.calendar = calendar or MarketCalendar()
        self._now = now or (lambda: dt.datetime.now(self.calendar.tz))

    def answer(self, text: str) -> Answer | None:
        """Return an answer, or ``None`` to let the planner have it."""
        q = text.lower()
        if not q.strip():
            return None

        # Order matters. "Is the market open?" asks for state; "what time does
        # the market open?" asks for a time. Both contain "market" and "open",
        # so the more specific pattern has to be tested first or it never fires.
        if _asks(q, r"\bis the market (open|closed)\b|\bare we (open|closed)\b|\bmarket status\b"):
            return self._state_answer()
        if _asks(q, r"\bwhat time is it\b|\bwhat'?s the time\b"):
            now = self._now()
            return Answer(f"It's {now.strftime('%H:%M')} in New York.", "clock")
        if _asks(q, r"\b(market|session)\b.*\bclos|\bclos\w*\b.*\bmarket\b"):
            return self._close_answer()
        if _asks(q, r"\b(market|session)\b.*\bopen\b|\bopen\b.*\bmarket\b"):
            return self._open_answer()
        return None

    # -- the three calendar answers ---------------------------------------

    def _open_answer(self) -> Answer:
        now = self._now()
        state = self.calendar.state(now)
        today = now.date()
        open_today = self.calendar.session_open(today)

        if open_today is not None and now < open_today:
            delta = open_today - now
            return Answer(
                f"The market opens at {open_today.strftime('%H:%M')}, in {_spoken_delta(delta)}.",
                "calendar",
            )
        if state is SessionState.OPEN:
            close = self.calendar.session_close(today)
            tail = f" It closes at {close.strftime('%H:%M')}." if close else ""
            return Answer(f"The market is already open.{tail}", "calendar")

        nxt = self._next_session_open(today)
        if nxt is None:
            return Answer("I can't find the next session on the calendar.", "calendar")
        day = "tomorrow" if nxt.date() == today + dt.timedelta(days=1) else nxt.strftime("%A")
        return Answer(f"The market next opens {day} at {nxt.strftime('%H:%M')}.", "calendar")

    def _close_answer(self) -> Answer:
        now = self._now()
        close = self.calendar.session_close(now.date())
        if close is None:
            return Answer("The market is closed today.", "calendar")
        if now < close:
            return Answer(f"The close is at {close.strftime('%H:%M')}, in {_spoken_delta(close - now)}.", "calendar")
        return Answer(f"The market closed at {close.strftime('%H:%M')}.", "calendar")

    def _state_answer(self) -> Answer:
        now = self._now()
        return Answer(self.calendar.describe(now), "calendar")

    def _next_session_open(self, after: dt.date) -> dt.datetime | None:
        # Ten days covers any holiday run on any exchange calendar in use.
        for offset in range(1, 11):
            day = after + dt.timedelta(days=offset)
            if self.calendar.is_session(day):
                return self.calendar.session_open(day)
        return None


def _asks(question: str, pattern: str) -> bool:
    return re.search(pattern, question) is not None


def _spoken_delta(delta: dt.timedelta) -> str:
    """A duration as a person would say it -- never "0:47:00"."""
    minutes = max(0, int(delta.total_seconds() // 60))
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours} hour{'s' if hours != 1 else ''} and {mins} minute{'s' if mins != 1 else ''}"
    if hours:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    if mins:
        return f"{mins} minute{'s' if mins != 1 else ''}"
    return "under a minute"
