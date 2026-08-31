# Spec: Genesis Markdown/10-Architecture/Daemon And Cadence.md
"""The forever loop.

Genesis is not "on during the day" -- it has two different jobs depending on
whether the market is open, and the loop is what switches between them::

    while True:
        session = calendar.state(now)
        run_due(market-open | market-closed)
        run_due(cron)
        drain_task_bus()
        handle_events()
        watchdog.heartbeat_all()
        sleep(TICK)

:meth:`Daemon.tick` is the body of that loop, factored out and pure with respect
to time -- it takes ``now`` as an argument. Tests drive a year of market days
through it in milliseconds; ``run_forever`` is the thin wrapper that supplies a
real clock and a sleep.

Phase 1 has no intelligence in here. The loop schedules, dispatches, supervises
and logs. Nothing decides anything.
"""

from __future__ import annotations

import datetime as dt
import signal
import threading
from dataclasses import dataclass, field
from typing import Any

from genesis.agents.base import Agent, AgentState, TaskFailure, TaskResult
from genesis.bus import Lane, TaskBus, TaskState
from genesis.daemon.calendar import MarketCalendar, SessionState
from genesis.daemon.scheduler import Scheduler
from genesis.daemon.supervisor import Supervisor
from genesis.ids import new_trace_id
from genesis.observability import Console

__all__ = ["Daemon", "TickReport"]

TICK_SEC = 1.0
DEFAULT_LANE_FOR_CADENCE = {
    "market-open": Lane.RESEARCH,
    "market-closed": Lane.MAINTENANCE,
    "cron": Lane.RESEARCH,
    "event": Lane.EVENT,
    "on-demand": Lane.USER,
}


@dataclass
class TickReport:
    """What one pass of the loop did. Returned so tests can assert on it."""

    at: dt.datetime
    session: SessionState
    dispatched: list[str] = field(default_factory=list)
    ran: list[str] = field(default_factory=list)
    restarted: list[str] = field(default_factory=list)
    requeued: int = 0
    shed: int = 0


class Daemon:
    """Ties the calendar, scheduler, bus and supervisor into one loop."""

    def __init__(
        self,
        bus: TaskBus,
        *,
        calendar: MarketCalendar | None = None,
        scheduler: Scheduler | None = None,
        supervisor: Supervisor | None = None,
        console: Console | None = None,
        max_tasks_per_tick: int = 32,
    ) -> None:
        self.bus = bus
        self.calendar = calendar or MarketCalendar()
        self.scheduler = scheduler or Scheduler(self.calendar)
        self.supervisor = supervisor or Supervisor()
        # Wire the event sink unconditionally. Passing a supervisor in must not
        # silently disable agent.down — a fleet-health event that reaches nobody
        # is the exact failure the watchdog exists to prevent.
        self.supervisor._on_event = self._emit_event
        self.console = console or Console()
        self.max_tasks_per_tick = max_tasks_per_tick
        self._stop = threading.Event()
        self._last_session: SessionState | None = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, agent: Agent) -> None:
        """Add an agent to the roster: scheduled, supervised, and startable."""
        self.scheduler.register(agent.declaration)
        self.supervisor.supervise(agent)

    # ------------------------------------------------------------------
    # Boot
    # ------------------------------------------------------------------

    def boot(self, now: dt.datetime | None = None) -> dict[str, Any]:
        """Restore state, start agents, and announce what was found.

        Order matters and is the note's: restore the bus **before** starting
        agents, so a resumed task is not raced by a freshly scheduled one.
        """
        now = now or dt.datetime.now(dt.UTC)
        recovery = self.bus.recover()
        self.supervisor.start_all()

        session = self.calendar.state(now)
        self._last_session = session
        idle = len(self.supervisor.agent_ids)

        self.console.line("🜲", "Genesis online")
        with self.console.nest():
            self.console.line("🗓️ ", self.calendar.describe(now))
            if recovery["requeued"]:
                self.console.degraded(
                    f"{recovery['requeued']} task(s) requeued after unclean shutdown"
                )
            if recovery["expired"]:
                self.console.line("🗑️ ", f"{recovery['expired']} task(s) past deadline, dropped")
            self.console.line("🤖", f"{idle} agent(s) idle")

        return {"session": session, **recovery, "agents": idle}

    def shutdown(self, grace_sec: float = 5.0) -> None:
        self._stop.set()
        self.supervisor.stop_all(grace_sec=grace_sec)
        self.console.line("🌙", "Genesis offline")

    # ------------------------------------------------------------------
    # The loop
    # ------------------------------------------------------------------

    def tick(self, now: dt.datetime | None = None) -> TickReport:
        """One pass of the forever loop."""
        now = now or dt.datetime.now(dt.UTC)
        session = self.calendar.state(now)
        report = TickReport(at=now, session=session)

        if self._last_session is not None and session is not self._last_session:
            self._emit_event(
                "market.open" if session is SessionState.OPEN else "market.close",
                {"from": self._last_session.value, "to": session.value},
            )
            # Orchestrator Tools: a spoken cadence change is transient and
            # reverts at the next session transition unless it was written to
            # config. Reverting here rather than on a timer means "stop scanning,
            # it's noisy" lasts exactly as long as the session it was said in.
            reverted = self.scheduler.clear_cadence_overrides()
            if reverted:
                self.console.line(
                    "\u23f1\ufe0f ", f"cadence override reverted: {', '.join(reverted)}"
                )
        self._last_session = session

        # 1. restart anything whose backoff has elapsed
        for agent_id in self.supervisor.due_restarts(now):
            if self.supervisor.restart(agent_id, now):
                report.restarted.append(agent_id)

        # 2. dispatch due cadences onto the bus
        for work in self.scheduler.due(now, session=session):
            agent = self.supervisor.agent(work.agent_id)
            if agent is None or agent.status().state is AgentState.DEGRADED:
                continue
            lane = DEFAULT_LANE_FOR_CADENCE.get(work.cadence.type, Lane.RESEARCH)
            task = self.bus.submit(
                type=f"{work.agent_id}.run",
                agent=work.agent_id,
                lane=lane,
                args={"reason": work.reason},
                origin={"kind": "cadence", "ref": work.cadence.type},
                # One scheduled run per agent per cadence tick. Without this a
                # slow agent would have a second copy queued behind the first.
                idempotency_key=f"cadence:{work.agent_id}:{work.cadence.type}",
                trace_id=new_trace_id(),
            )
            self.scheduler.mark_ran(work, now)
            if task is not None:
                report.dispatched.append(task.id)

        # 3. drain the bus — critical lanes first, always
        report.ran = self._drain(now)

        # 4. backpressure, then heartbeats
        report.shed = self.bus.shed()
        for agent_id in self.supervisor.agent_ids:
            self.supervisor.agent(agent_id).set_next_run(
                self.scheduler.next_run_at(agent_id, now)
            )
        return report

    def _drain(self, now: dt.datetime) -> list[str]:
        """Run up to ``max_tasks_per_tick`` tasks, critical lanes first.

        The two claim calls are the separate worker pools in a single-threaded
        Phase 1 shape: critical lanes are fully drained before research is even
        looked at, so an order can never queue behind a scan.
        """
        ran: list[str] = []
        critical = [Lane.EXECUTION, Lane.RISK, Lane.USER]
        background = [Lane.EVENT, Lane.RESEARCH, Lane.MAINTENANCE]

        for lanes in (critical, background):
            while len(ran) < self.max_tasks_per_tick:
                task = self.bus.claim(lanes=lanes)
                if task is None:
                    break
                self._run_one(task, now)
                ran.append(task.id)
        return ran

    def _run_one(self, task: Any, now: dt.datetime) -> None:
        agent = self.supervisor.agent(task.agent)
        if agent is None:
            self.bus.fail(
                task.id,
                {
                    "class": "fatal",
                    "reason": f"no agent registered as {task.agent!r}",
                    "retryable": False,
                },
            )
            return

        self.bus.start(task.id)
        outcome = agent.run_task(task)

        if isinstance(outcome, TaskResult):
            self.bus.complete(task.id, outcome.to_dict())
            self.supervisor.note_healthy(task.agent)
            return

        assert isinstance(outcome, TaskFailure)
        self.bus.fail(task.id, outcome.to_dict())
        # A fatal failure is a crash: it is the agent, not the work, that is
        # broken. Transient and degraded failures are the task's problem and the
        # bus already handles them by retrying.
        if outcome.failure_class == "fatal":
            self.supervisor.note_crash(task.agent, outcome.reason, now)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _emit_event(self, name: str, data: dict[str, Any]) -> None:
        """Publish an event.

        Per Event Schema, events are persisted to the Episodic Log **before**
        dispatch, so nothing is lost on a crash mid-fanout.
        """
        trace_id = new_trace_id()
        self.bus.log.append(
            actor="daemon",
            kind=name,
            trace_id=trace_id,
            summary=name,
            payload=data,
            degraded=name in ("agent.down", "system.degraded"),
        )
        for work in self.scheduler.subscribers(name):
            self.bus.submit(
                type=f"{work.agent_id}.on_event",
                agent=work.agent_id,
                lane=Lane.EVENT,
                args={"event": name, "data": data},
                origin={"kind": "event", "ref": name},
                trace_id=trace_id,
            )

    def publish(self, name: str, data: dict[str, Any] | None = None) -> None:
        """Public entry point for publishing an event onto the bus."""
        self._emit_event(name, data or {})

    # ------------------------------------------------------------------
    # Forever
    # ------------------------------------------------------------------

    def run_forever(self, tick_sec: float = TICK_SEC) -> None:
        """The loop. Handles SIGINT/SIGTERM so shutdown drains rather than dies."""

        def _handle(signum: int, _frame: Any) -> None:
            self.console.line("🛑", f"signal {signum} — draining")
            self._stop.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handle)
            except ValueError:
                # Not on the main thread; the caller drives _stop instead.
                pass

        self.boot()
        try:
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(tick_sec)
        finally:
            self.shutdown()
