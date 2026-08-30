# Spec: Genesis Markdown/10-Architecture/Daemon And Cadence.md
"""Supervision: crash -> backoff restart -> degraded.

The policy is the note's, exactly:

- crash -> restart with exponential backoff 1s, 2s, 4s... capped at 60s
- 5 crashes in 10 minutes -> mark ``degraded``, **stop restarting**, emit
  ``agent.down``, tell the user

The give-up rule is the important half. A supervisor that restarts forever turns
a reproducible bug into an infinite loop that looks like activity, and the one
thing worse than an agent being down is an agent being down silently.

The Kill Switch runs **outside** supervision -- it has to work when the
supervisor itself is broken -- so nothing here may ever be in its path.
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from genesis.agents.base import Agent, AgentState

__all__ = ["CRASH_LIMIT", "CRASH_WINDOW_SEC", "Supervisor", "SupervisionRecord"]

BACKOFF_BASE_SEC = 1.0
BACKOFF_CAP_SEC = 60.0
CRASH_LIMIT = 5
CRASH_WINDOW_SEC = 600.0  # 10 minutes


@dataclass
class SupervisionRecord:
    """Restart bookkeeping for one agent."""

    agent: Agent
    crashes: deque[dt.datetime] = field(default_factory=deque)
    consecutive: int = 0
    restart_after: dt.datetime | None = None
    given_up: bool = False
    last_reason: str | None = None

    def backoff_sec(self) -> float:
        """1, 2, 4, 8... capped at 60."""
        return min(BACKOFF_BASE_SEC * (2 ** max(0, self.consecutive - 1)), BACKOFF_CAP_SEC)


class Supervisor:
    """Restarts crashed agents, and knows when to stop trying."""

    def __init__(
        self,
        *,
        on_event: Callable[[str, dict], None] | None = None,
        crash_limit: int = CRASH_LIMIT,
        crash_window_sec: float = CRASH_WINDOW_SEC,
    ) -> None:
        self._records: dict[str, SupervisionRecord] = {}
        self._on_event = on_event or (lambda name, data: None)
        self.crash_limit = crash_limit
        self.crash_window_sec = crash_window_sec

    # -- registration ------------------------------------------------------

    def supervise(self, agent: Agent) -> None:
        self._records[agent.id] = SupervisionRecord(agent=agent)

    def record(self, agent_id: str) -> SupervisionRecord | None:
        return self._records.get(agent_id)

    @property
    def agent_ids(self) -> list[str]:
        return sorted(self._records)

    def agent(self, agent_id: str) -> Agent | None:
        rec = self._records.get(agent_id)
        return rec.agent if rec else None

    # -- lifecycle ---------------------------------------------------------

    def start_all(self) -> None:
        for rec in self._records.values():
            rec.agent.start()

    def stop_all(self, grace_sec: float = 5.0) -> None:
        for rec in self._records.values():
            rec.agent.stop(grace_sec=grace_sec)

    def note_crash(self, agent_id: str, reason: str, now: dt.datetime) -> bool:
        """Record a crash. Returns whether the agent will be restarted.

        A ``False`` return means the crash budget is spent: the agent is marked
        degraded, ``agent.down`` is emitted, and nothing will restart it until a
        human intervenes.
        """
        rec = self._records.get(agent_id)
        if rec is None:
            return False

        rec.last_reason = reason
        rec.crashes.append(now)
        cutoff = now - dt.timedelta(seconds=self.crash_window_sec)
        while rec.crashes and rec.crashes[0] < cutoff:
            rec.crashes.popleft()

        if len(rec.crashes) >= self.crash_limit:
            rec.given_up = True
            rec.restart_after = None
            rec.agent.mark_degraded(
                f"{len(rec.crashes)} crashes in "
                f"{int(self.crash_window_sec / 60)} min: {reason}"
            )
            self._on_event(
                "agent.down",
                {
                    "agent": agent_id,
                    "reason": reason,
                    "crashes": len(rec.crashes),
                    "window_sec": self.crash_window_sec,
                },
            )
            return False

        rec.consecutive += 1
        rec.restart_after = now + dt.timedelta(seconds=rec.backoff_sec())
        return True

    def due_restarts(self, now: dt.datetime) -> list[str]:
        """Agents whose backoff has elapsed and that should be restarted now."""
        return sorted(
            agent_id
            for agent_id, rec in self._records.items()
            if not rec.given_up
            and rec.restart_after is not None
            and now >= rec.restart_after
        )

    def restart(self, agent_id: str, now: dt.datetime) -> bool:
        """Bring an agent back up. Returns success."""
        rec = self._records.get(agent_id)
        if rec is None or rec.given_up:
            return False
        try:
            rec.agent.stop(grace_sec=0.0)
            rec.agent.start()
        except Exception as exc:  # noqa: BLE001 - a failed restart is itself a crash
            self.note_crash(agent_id, f"restart failed: {exc}", now)
            return False
        rec.restart_after = None
        self._on_event("agent.recovered", {"agent": agent_id})
        return True

    def note_healthy(self, agent_id: str) -> None:
        """Clear the consecutive-crash counter after a clean run.

        Consecutive count drives the backoff; the sliding window drives the
        give-up decision. Clearing one does not clear the other -- an agent that
        crashes five times in ten minutes has spent its budget even if it
        managed a good run between each.
        """
        rec = self._records.get(agent_id)
        if rec is not None:
            rec.consecutive = 0

    def health_report(self) -> dict[str, dict]:
        """What the watchdog and the dashboard agent grid render."""
        return {
            agent_id: {
                "state": rec.agent.status().state.value,
                "alive": rec.agent.health().alive,
                "crashes_in_window": len(rec.crashes),
                "given_up": rec.given_up,
                "last_reason": rec.last_reason,
            }
            for agent_id, rec in sorted(self._records.items())
        }

    def degraded_agents(self) -> list[str]:
        return sorted(
            agent_id
            for agent_id, rec in self._records.items()
            if rec.given_up or rec.agent.status().state is AgentState.DEGRADED
        )
