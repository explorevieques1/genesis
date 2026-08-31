# Spec: Genesis Markdown/10-Architecture/Daemon And Cadence.md
"""Which agents are due to run, and when.

Cadence types and their firing rules:

``market-open`` / ``market-closed``
    Every ``interval_sec`` while the session matches. ``market-open`` covers
    premarket, open and afterhours -- a gap scan at 08:00 is market work.
``cron``
    Once per day at a wall-clock time in market-local time. Tracked by date, not
    by elapsed seconds, so a daemon that was down at 07:00 does not fire the
    pre-market brief at 11:00 when it comes back.
``event``
    Fired by the bus when a subscribed event arrives, never by the clock.
``on-demand``
    Only when the orchestrator dispatches.

The scheduler is deliberately pure with respect to time: ``due()`` takes ``now``
as an argument and holds no clock of its own. That is what lets the tests drive
a year of market days through it in milliseconds.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from genesis.agents.base import AgentDeclaration, Cadence
from genesis.daemon.calendar import MarketCalendar, SessionState

__all__ = ["DueWork", "Scheduler"]


@dataclass(frozen=True)
class DueWork:
    """One agent-cadence pair that should run now."""

    agent_id: str
    cadence: Cadence
    reason: str

    @property
    def key(self) -> tuple[str, int]:
        return (self.agent_id, id(self.cadence))


@dataclass
class _Registration:
    declaration: AgentDeclaration
    last_run: dict[int, dt.datetime] = field(default_factory=dict)
    last_cron_date: dict[int, dt.date] = field(default_factory=dict)
    #: A transient interval override, from ``set_cadence``. Orchestrator Tools:
    #: *"Cadence changes are transient and revert at the next market-open
    #: transition unless written to config."* Held here rather than on the
    #: declaration because the declaration is frozen and is what the note says
    #: -- overwriting it would make the running system disagree with its spec.
    interval_override_sec: int | None = None


class Scheduler:
    """Tracks cadences and answers "what is due?"."""

    def __init__(self, calendar: MarketCalendar | None = None) -> None:
        self.calendar = calendar or MarketCalendar()
        self._registered: dict[str, _Registration] = {}

    # -- registration ------------------------------------------------------

    def register(self, declaration: AgentDeclaration) -> None:
        """Add an agent to the roster. Idempotent by agent id.

        Re-registering keeps the existing run history, so a supervised restart
        does not make an agent immediately due again and stampede the bus.
        """
        existing = self._registered.get(declaration.id)
        if existing is not None:
            existing.declaration = declaration
            return
        self._registered[declaration.id] = _Registration(declaration=declaration)

    def unregister(self, agent_id: str) -> None:
        self._registered.pop(agent_id, None)

    def set_cadence(self, agent_id: str, interval_sec: int) -> bool:
        """Transiently override an agent's interval cadences.

        Returns False for an unknown agent rather than raising: the caller is
        the orchestrator, on the voice path, and it needs to say *"I don't have
        an agent called that"* rather than take an exception mid-sentence.

        Only ``market-open`` / ``market-closed`` cadences are affected. Cron
        times and event subscriptions are not intervals and are left alone.
        """
        reg = self._registered.get(agent_id)
        if reg is None:
            return False
        if interval_sec <= 0:
            raise ValueError(f"interval_sec must be positive, got {interval_sec}")
        reg.interval_override_sec = interval_sec
        return True

    def clear_cadence_overrides(self) -> list[str]:
        """Drop every transient override. Called on a session transition."""
        cleared = []
        for agent_id, reg in sorted(self._registered.items()):
            if reg.interval_override_sec is not None:
                reg.interval_override_sec = None
                cleared.append(agent_id)
        return cleared

    @property
    def agent_ids(self) -> list[str]:
        return sorted(self._registered)

    def is_registered(self, agent_id: str) -> bool:
        return agent_id in self._registered

    def declaration(self, agent_id: str) -> AgentDeclaration | None:
        reg = self._registered.get(agent_id)
        return reg.declaration if reg else None

    # -- scheduling --------------------------------------------------------

    def due(
        self, now: dt.datetime, *, session: SessionState | None = None
    ) -> list[DueWork]:
        """Everything that should run at ``now``."""
        if now.tzinfo is None:
            raise ValueError("Scheduler.due requires a timezone-aware datetime")
        session = session if session is not None else self.calendar.state(now)
        local = now.astimezone(self.calendar.tz)

        work: list[DueWork] = []
        for agent_id, reg in sorted(self._registered.items()):
            for index, cadence in enumerate(reg.declaration.cadence):
                if self._is_due(reg, index, cadence, now, local, session):
                    work.append(
                        DueWork(
                            agent_id=agent_id,
                            cadence=cadence,
                            reason=self._reason(cadence, session),
                        )
                    )
        return work

    def _is_due(
        self,
        reg: _Registration,
        index: int,
        cadence: Cadence,
        now: dt.datetime,
        local: dt.datetime,
        session: SessionState,
    ) -> bool:
        if cadence.type == "market-open" and not session.market_hours:
            return False
        if cadence.type == "market-closed" and session.market_hours:
            return False

        if cadence.type in ("market-open", "market-closed"):
            last = reg.last_run.get(index)
            if last is None:
                return True
            assert cadence.interval_sec is not None  # validated on the model
            interval = reg.interval_override_sec or cadence.interval_sec
            return (now - last).total_seconds() >= interval

        if cadence.type == "cron":
            assert cadence.at is not None  # validated on the model
            hour, minute = (int(part) for part in cadence.at.split(":"))
            fire_at = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if local < fire_at:
                return False
            # Tracked by date: a daemon that was down at 07:00 must not fire the
            # pre-market brief at 11:00 as if nothing happened. It fires late
            # today only if it has not already fired today.
            return reg.last_cron_date.get(index) != local.date()

        # on-demand and event are never due from the clock.
        return False

    def _reason(self, cadence: Cadence, session: SessionState) -> str:
        if cadence.type == "cron":
            return f"cron {cadence.at}"
        return f"{cadence.type} every {cadence.interval_sec}s ({session.value})"

    def mark_ran(self, work: DueWork, at: dt.datetime) -> None:
        """Record that a due item was dispatched, so it is not re-dispatched."""
        reg = self._registered.get(work.agent_id)
        if reg is None:
            return
        for index, cadence in enumerate(reg.declaration.cadence):
            if cadence is work.cadence:
                reg.last_run[index] = at
                if cadence.type == "cron":
                    reg.last_cron_date[index] = at.astimezone(self.calendar.tz).date()
                return

    def next_run_at(self, agent_id: str, now: dt.datetime) -> dt.datetime | None:
        """Earliest next fire across an agent's interval cadences, for status()."""
        reg = self._registered.get(agent_id)
        if reg is None:
            return None
        candidates: list[dt.datetime] = []
        for index, cadence in enumerate(reg.declaration.cadence):
            if cadence.type not in ("market-open", "market-closed"):
                continue
            assert cadence.interval_sec is not None
            interval = reg.interval_override_sec or cadence.interval_sec
            last = reg.last_run.get(index)
            candidates.append(
                now if last is None else last + dt.timedelta(seconds=interval)
            )
        return min(candidates) if candidates else None

    def subscribers(self, event: str) -> list[DueWork]:
        """Agents whose ``event`` cadence subscribes to this event name."""
        work: list[DueWork] = []
        for agent_id, reg in sorted(self._registered.items()):
            for cadence in reg.declaration.cadence:
                if cadence.type == "event" and event in cadence.on:
                    work.append(
                        DueWork(agent_id=agent_id, cadence=cadence, reason=f"event {event}")
                    )
        return work
