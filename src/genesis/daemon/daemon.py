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
        wait(TICK, or until a task is submitted)

Background lanes drain on a second thread under ``run_forever`` -- see
:meth:`Daemon._drain`.

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
#: Task Bus: "a task in execution or risk must never wait behind an LLM call in
#: research. Enforce with separate worker pools, not just ordering."
CRITICAL_LANES = (Lane.EXECUTION, Lane.RISK, Lane.USER)
BACKGROUND_LANES = (Lane.EVENT, Lane.RESEARCH, Lane.MAINTENANCE)
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
        self._shutdown = False
        #: Guards the shutdown check-and-set. The two callers below are on
        #: different threads by construction, so an unguarded flag is a real
        #: race rather than a theoretical one.
        self._shutdown_lock = threading.Lock()
        self._last_session: SessionState | None = None
        #: Roster changes from other threads (an HTTP route saving a workflow),
        #: applied at the top of the next tick so the scheduler and supervisor
        #: are only ever mutated on the loop's own thread.
        self._soon: list[Any] = []
        self._soon_lock = threading.Lock()
        #: The background pool, when ``run_forever`` has started one. ``None``
        #: means ``tick`` drains every lane itself -- the shape tests drive.
        self._background: threading.Thread | None = None
        #: One task per agent at a time, across both pools. Agents were written
        #: for a single-threaded drain; a user task for the screener waits for
        #: the screener's own scan, but never for anyone else's.
        self._agent_locks: dict[str, threading.Lock] = {}
        #: Supervisor records are mutated by both pools and by ``tick``.
        self._fleet_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, agent: Agent) -> None:
        """Add an agent to the roster: scheduled, supervised, and startable."""
        self.scheduler.register(agent.declaration)
        self.supervisor.supervise(agent)
        # Cron history is in memory; the bus is durable. Seed from it so a
        # same-day restart does not fire a cron that already ran today.
        for task in self.bus.by_idempotency_key(f"cadence:{agent.id}:cron"):
            at, fired_on = task.args.get("at"), task.args.get("fired_on")
            if at and fired_on:
                self.scheduler.seed_cron(agent.id, at, dt.date.fromisoformat(fired_on))

    def call_soon(self, fn: Any) -> None:
        """Run ``fn()`` on the loop's thread at the start of the next tick."""
        with self._soon_lock:
            self._soon.append(fn)

    def unregister(self, agent_id: str) -> None:
        """Take an agent off the roster: no longer scheduled or supervised."""
        self.scheduler.unregister(agent_id)
        self.supervisor.unsupervise(agent_id)

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
        """Stop the fleet. Idempotent.

        Two callers can legitimately want this: ``run_forever``'s own ``finally``
        and whoever owns the daemon from outside -- ``genesis voice`` hosts one
        in a thread and stops it when the loop ends. Without the guard, shutting
        down says "Genesis offline" twice, which reads like something restarted.

        Those two callers are on *different threads* by construction, so the
        flag is read and set under a lock. A bare check-then-set would let both
        through the window between them and run ``stop_all`` twice, which is
        the exact race this method exists to prevent.
        """
        with self._shutdown_lock:
            if self._shutdown:
                return
            self._shutdown = True
        self._stop.set()
        self.bus.wakeup.set()
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

        # 0. roster changes queued from other threads
        with self._soon_lock:
            soon, self._soon = self._soon, []
        for fn in soon:
            try:
                with self._fleet_lock:
                    fn()
            except Exception as exc:  # noqa: BLE001 - one bad change must not stop the loop
                self.console.warn(f"roster change failed: {exc}")

        # 1. restart anything whose backoff has elapsed
        with self._fleet_lock:
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
                args={"reason": work.reason, **self._cron_args(work, now)},
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

    def _cron_args(self, work: Any, now: dt.datetime) -> dict[str, str]:
        """What ``register`` reads back after a restart to seed cron history."""
        if work.cadence.type != "cron":
            return {}
        local = now.astimezone(self.calendar.tz).date()
        return {"at": work.cadence.at, "fired_on": local.isoformat()}

    def _drain(self, now: dt.datetime) -> list[str]:
        """Run up to ``max_tasks_per_tick`` tasks, critical lanes first.

        Under ``run_forever`` the background lanes belong to their own thread
        (:meth:`_background_loop`) and this drains only the critical ones, so
        a typed request never waits for a research pass to finish. Without that
        thread -- a bare ``tick`` -- both pools drain here, critical first.
        """
        ran = self._drain_lanes(CRITICAL_LANES, now, self.max_tasks_per_tick)
        if self._background is None:
            ran += self._drain_lanes(
                BACKGROUND_LANES, now, self.max_tasks_per_tick - len(ran)
            )
        return ran

    def _drain_lanes(self, lanes: tuple[Lane, ...], now: dt.datetime, limit: int) -> list[str]:
        ran: list[str] = []
        while len(ran) < limit:
            task = self.bus.claim(lanes=list(lanes))
            if task is None:
                break
            self._run_one(task, now)
            ran.append(task.id)
        return ran

    def _background_loop(self, tick_sec: float) -> None:
        """The background pool. Research latency is not user-facing; ticking is fine."""
        while not self._stop.is_set():
            try:
                ran = self._drain_lanes(
                    BACKGROUND_LANES, dt.datetime.now(dt.UTC), self.max_tasks_per_tick
                )
            except Exception as exc:  # noqa: BLE001 - a dead pool is silent; say so and keep going
                self.console.degraded(f"background pool fault: {exc}")
                ran = []
            if not ran:
                self._stop.wait(tick_sec)

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

        # Hold the claim for as long as the work takes, including any wait for
        # the agent's lock. With two pools, the other one calls `claim` -- which
        # expires stale claims -- while this task is still running.
        done = threading.Event()
        interval = self.bus.claim_ttl_sec / 3

        def keep_claim() -> None:
            while not done.wait(interval):
                self.bus.renew(task.id)

        heartbeat = threading.Thread(target=keep_claim, name=f"claim-{task.id}", daemon=True)
        heartbeat.start()
        try:
            with self._agent_locks.setdefault(task.agent, threading.Lock()):
                self.bus.start(task.id)
                outcome = agent.run_task(task)
        finally:
            done.set()

        if isinstance(outcome, TaskResult):
            self.bus.complete(task.id, outcome.to_dict())
            with self._fleet_lock:
                self.supervisor.note_healthy(task.agent)
            return

        assert isinstance(outcome, TaskFailure)
        self.bus.fail(task.id, outcome.to_dict())
        # A fatal failure is a crash: it is the agent, not the work, that is
        # broken. Transient and degraded failures are the task's problem and the
        # bus already handles them by retrying.
        if outcome.failure_class == "fatal":
            with self._fleet_lock:
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
            self.bus.wakeup.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handle)
            except ValueError:
                # Not on the main thread; the caller drives _stop instead.
                pass

        self.boot()
        self._background = threading.Thread(
            target=self._background_loop, args=(tick_sec,),
            name="genesis-daemon-background", daemon=True,
        )
        self._background.start()
        try:
            while not self._stop.is_set():
                # Clear before the tick, not after: a submit that lands while
                # the tick runs must cut the next wait short, not be forgotten.
                self.bus.wakeup.clear()
                self.tick()
                # A submit wakes this immediately; the tick is the fallback for
                # cadences, retries' not_before, and other processes' submits.
                self.bus.wakeup.wait(tick_sec)
        finally:
            self._stop.set()
            self._background.join(timeout=5.0)
            self.shutdown()
