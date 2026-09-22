# Spec: Genesis Markdown/10-Architecture/Task Bus.md
"""The single path all work travels.

Agents never call each other. They put work here and read results from the
memory fabric, which is what keeps the agent graph legible instead of a tangle
of direct calls nobody can reason about.

Four properties are load-bearing, and each is enforced by structure rather than
by discipline:

**Every state transition is in the Episodic Log.** The state change and its log
entry are written in *one* transaction (:meth:`EpisodicLog.append_in`). A crash
between them is therefore impossible, which is what makes the note's "every
transition reconstructible from the Episodic Log alone" true rather than hoped.

**Claims expire.** A worker killed mid-task cannot release its claim, so the
claim carries a TTL. On expiry the task returns to ``pending`` and is retried --
this is how work survives ``kill -9`` without being lost.

**Idempotency keys are unique among live tasks.** Enforced by a partial UNIQUE
index, so a re-enqueue while the original is in flight is a no-op at the
database level, not a check-then-insert race. This is what makes recovery
exactly-once instead of at-least-once.

**Shedding cannot reach a protected lane.** :attr:`Lane.sheddable` is false for
execution, risk and user, and the shed query filters on it, so no threshold
change can start dropping orders.
"""

from __future__ import annotations

import json
import random
import sqlite3
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genesis.bus.task import TERMINAL_STATES, Lane, Task, TaskState
from genesis.ids import new_id, new_trace_id
from genesis.memory.db import connect, transaction
from genesis.memory.episodic import EpisodicLog

__all__ = ["TaskBus", "SCHEMA"]

DEFAULT_CLAIM_TTL_SEC = 30.0
DEFAULT_RESEARCH_DEPTH_LIMIT = 500

# Error Handling And Degradation: 1s, 2s, 4s, 8s... capped at 60s, with jitter.
# Without this a failed task is re-claimed on the next line of the same tick and
# burns every attempt in microseconds, which is not a retry policy -- it is a
# fast way to exhaust one.
RETRY_BACKOFF_BASE_SEC = 1.0
RETRY_BACKOFF_CAP_SEC = 60.0
RETRY_JITTER = 0.25


def retry_delay(attempts: int, base_sec: float = RETRY_BACKOFF_BASE_SEC) -> float:
    """Backoff for the next attempt, with jitter to avoid a thundering herd."""
    base = min(base_sec * (2 ** max(0, attempts - 1)), RETRY_BACKOFF_CAP_SEC)
    return base * (1.0 + random.uniform(0.0, RETRY_JITTER))

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    lane            INTEGER NOT NULL,
    agent           TEXT NOT NULL,
    args            TEXT,
    depends_on      TEXT,
    origin          TEXT,
    deadline        TEXT,
    idempotency_key TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    state           TEXT NOT NULL,
    trace_id        TEXT NOT NULL,
    claim_id        TEXT,
    claimed_until   REAL,
    not_before      REAL,          -- retry backoff: not claimable until this time
    result          TEXT,
    failure         TEXT,
    created_at      TEXT NOT NULL
);

-- Claiming scans for the highest-priority runnable task; this is the index that
-- keeps an execution task starting fast behind a deep research backlog.
CREATE INDEX IF NOT EXISTS tasks_ready ON tasks(state, lane, not_before, created_at);
CREATE INDEX IF NOT EXISTS tasks_trace ON tasks(trace_id);
CREATE INDEX IF NOT EXISTS tasks_agent ON tasks(agent, state);

-- Idempotency, enforced by the database. The index covers only live states, so
-- a key may be reused once its previous task has reached a terminal state, but
-- never while one is in flight.
CREATE UNIQUE INDEX IF NOT EXISTS tasks_idempotency_live
    ON tasks(idempotency_key)
    WHERE idempotency_key IS NOT NULL
      AND state IN ('pending', 'claimed', 'running');
"""


class TaskBus:
    """Durable, lane-prioritised task queue.

    The queue lives in SQLite so a restart resumes rather than forgets.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        log: EpisodicLog | None = None,
        claim_ttl_sec: float = DEFAULT_CLAIM_TTL_SEC,
        research_depth_limit: int = DEFAULT_RESEARCH_DEPTH_LIMIT,
        retry_backoff_base_sec: float = RETRY_BACKOFF_BASE_SEC,
    ) -> None:
        self.path = path
        self._conn = connect(path)
        self._conn.executescript(SCHEMA)
        # The log shares the connection so a transition and its log entry commit
        # together. Two connections could not give that guarantee.
        self._log = log if log is not None else EpisodicLog(path, conn=self._conn)
        self.claim_ttl_sec = claim_ttl_sec
        self.research_depth_limit = research_depth_limit
        self.retry_backoff_base_sec = retry_backoff_base_sec
        self._lock = threading.RLock()
        #: Set on every successful submit. An in-process daemon waits on this
        #: instead of sleeping out its tick, so a typed request starts in
        #: microseconds rather than up to a second later. Another process
        #: submitting to the same file cannot set it; that daemon still ticks.
        self.wakeup = threading.Event()

    @property
    def log(self) -> EpisodicLog:
        return self._log

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    def submit(
        self,
        *,
        type: str,
        agent: str,
        lane: Lane | str = Lane.RESEARCH,
        args: dict[str, Any] | None = None,
        depends_on: Sequence[str] = (),
        origin: dict[str, Any] | None = None,
        deadline: str | None = None,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
        trace_id: str | None = None,
    ) -> Task | None:
        """Enqueue a task.

        Returns the task, or ``None`` if an identical ``idempotency_key`` is
        already in flight -- a no-op, per the note, not an error. This is what
        stops the screener running the same scan four times when events pile up.
        """
        lane = Lane.parse(lane)
        task_id = new_id("t")
        trace_id = trace_id or new_trace_id()
        created_at = _now()

        try:
            with self._lock, transaction(self._conn) as tx:
                tx.execute(
                    """
                    INSERT INTO tasks
                        (id, type, lane, agent, args, depends_on, origin, deadline,
                         idempotency_key, attempts, max_attempts, state, trace_id,
                         created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        type,
                        int(lane),
                        agent,
                        json.dumps(args or {}),
                        json.dumps(list(depends_on)),
                        json.dumps(origin or {}),
                        deadline,
                        idempotency_key,
                        max_attempts,
                        TaskState.PENDING.value,
                        trace_id,
                        created_at,
                    ),
                )
                self._log.append_in(
                    tx,
                    actor="bus",
                    kind="task.submitted",
                    trace_id=trace_id,
                    summary=f"{type} -> {agent} [{lane.name.lower()}]",
                    payload={
                        "task_id": task_id,
                        "lane": lane.name.lower(),
                        "idempotency_key": idempotency_key,
                    },
                )
        except sqlite3.IntegrityError:
            # The partial unique index rejected it: an identical key is live.
            return None

        self.wakeup.set()
        return self.get(task_id)

    # ------------------------------------------------------------------
    # Claim and complete
    # ------------------------------------------------------------------

    def claim(
        self,
        *,
        agent: str | None = None,
        lanes: Sequence[Lane] | None = None,
        ttl_sec: float | None = None,
    ) -> Task | None:
        """Claim the highest-priority runnable task, or ``None``.

        ``lanes`` restricts the claim to a subset, which is how separate worker
        pools are enforced: the critical pool passes the protected lanes and the
        background pool passes the rest, so an execution task can never queue
        behind an LLM call in research.

        A task is runnable when it is ``pending`` (or its claim has expired) and
        every dependency has reached ``done``.
        """
        ttl = ttl_sec if ttl_sec is not None else self.claim_ttl_sec
        now = time.time()
        claim_id = new_id("clm")

        with self._lock, transaction(self._conn) as tx:
            self._expire_claims_in(tx, now)

            where = ["state = 'pending'", "(not_before IS NULL OR not_before <= ?)"]
            params: list[Any] = [now]
            if agent is not None:
                where.append("agent = ?")
                params.append(agent)
            if lanes is not None:
                where.append(f"lane IN ({','.join('?' * len(lanes))})")
                params.extend(int(l) for l in lanes)

            rows = tx.execute(
                f"SELECT * FROM tasks WHERE {' AND '.join(where)} "
                f"ORDER BY lane ASC, created_at ASC",
                params,
            ).fetchall()

            for row in rows:
                task = Task.from_row(row)
                if task.deadline and task.deadline < _now():
                    self._transition_in(
                        tx, task, TaskState.SHED, summary="past deadline"
                    )
                    continue
                blocked, reason = self._dependency_state_in(tx, task)
                if blocked == "wait":
                    continue
                if blocked == "cancel":
                    self._transition_in(
                        tx,
                        task,
                        TaskState.CANCELLED,
                        summary=reason,
                        failure={"class": "fatal", "reason": reason},
                    )
                    continue

                tx.execute(
                    "UPDATE tasks SET state = ?, claim_id = ?, claimed_until = ?, "
                    "attempts = attempts + 1 WHERE id = ?",
                    (TaskState.CLAIMED.value, claim_id, now + ttl, task.id),
                )
                self._log.append_in(
                    tx,
                    actor="bus",
                    kind="task.claimed",
                    trace_id=task.trace_id,
                    summary=f"{task.type} claimed by {agent or 'worker'}",
                    payload={
                        "task_id": task.id,
                        "claim_id": claim_id,
                        "attempt": task.attempts + 1,
                    },
                )
                return self._get_in(tx, task.id)
        return None

    def renew(self, task_id: str, ttl_sec: float | None = None) -> bool:
        """Extend a live claim. ``False`` once the task is no longer held.

        The TTL exists to recover a holder that died silently. A holder that is
        alive and still working says so here -- without it, a 45-second research
        pass is requeued mid-run by whichever worker calls :meth:`claim` next.
        """
        ttl = ttl_sec if ttl_sec is not None else self.claim_ttl_sec
        with self._lock, transaction(self._conn) as tx:
            cur = tx.execute(
                "UPDATE tasks SET claimed_until = ? "
                "WHERE id = ? AND state IN ('claimed', 'running')",
                (time.time() + ttl, task_id),
            )
            return cur.rowcount == 1

    def start(self, task_id: str) -> Task | None:
        """Move a claimed task to ``running``."""
        with self._lock, transaction(self._conn) as tx:
            task = self._get_in(tx, task_id)
            if task is None or task.state is not TaskState.CLAIMED:
                return None
            self._transition_in(tx, task, TaskState.RUNNING)
            return self._get_in(tx, task_id)

    def complete(self, task_id: str, result: dict[str, Any]) -> Task | None:
        with self._lock, transaction(self._conn) as tx:
            task = self._get_in(tx, task_id)
            if task is None or task.state in TERMINAL_STATES:
                return None
            self._transition_in(tx, task, TaskState.DONE, result=result)
            return self._get_in(tx, task_id)

    def fail(
        self,
        task_id: str,
        failure: dict[str, Any],
        *,
        retryable: bool | None = None,
    ) -> Task | None:
        """Record a failure, retrying if attempts remain and it is retryable.

        A non-retryable failure goes straight to ``failed``. Retrying a fatal is
        how a bug becomes a loop instead of an alert.
        """
        with self._lock, transaction(self._conn) as tx:
            task = self._get_in(tx, task_id)
            if task is None or task.state in TERMINAL_STATES:
                return None

            may_retry = (
                failure.get("retryable", True) if retryable is None else retryable
            )
            if may_retry and task.attempts < task.max_attempts:
                delay = retry_delay(task.attempts, self.retry_backoff_base_sec)
                tx.execute(
                    "UPDATE tasks SET state = ?, claim_id = NULL, claimed_until = NULL, "
                    "not_before = ?, failure = ? WHERE id = ?",
                    (
                        TaskState.PENDING.value,
                        time.time() + delay,
                        json.dumps(failure),
                        task.id,
                    ),
                )
                self._log.append_in(
                    tx,
                    actor="bus",
                    kind="task.retrying",
                    trace_id=task.trace_id,
                    summary=(
                        f"{task.type}: {failure.get('reason', 'failed')} "
                        f"— retry in {delay:.1f}s"
                    ),
                    payload={
                        "task_id": task.id,
                        "attempt": task.attempts,
                        "max_attempts": task.max_attempts,
                        "retry_delay_sec": round(delay, 3),
                    },
                )
            else:
                self._transition_in(
                    tx, task, TaskState.FAILED, failure=failure
                )
                self._cancel_dependents_in(
                    tx, task.id, f"dependency {task.id} failed: {failure.get('reason')}"
                )
            return self._get_in(tx, task_id)

    def cancel(self, task_id: str, reason: str) -> Task | None:
        with self._lock, transaction(self._conn) as tx:
            task = self._get_in(tx, task_id)
            if task is None or task.state in TERMINAL_STATES:
                return None
            self._transition_in(
                tx, task, TaskState.CANCELLED, summary=reason,
                failure={"class": "fatal", "reason": reason},
            )
            self._cancel_dependents_in(tx, task.id, f"parent cancelled: {reason}")
            return self._get_in(tx, task_id)

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recover(self) -> dict[str, int]:
        """Restore queue state after a restart.

        Per the note: ``running``/``claimed`` tasks whose claim has expired are
        requeued; ``pending`` tasks past their deadline are dropped and logged.
        Returns counts, so boot can announce what it found.
        """
        now = time.time()
        with self._lock, transaction(self._conn) as tx:
            requeued = self._expire_claims_in(tx, now)

            expired = 0
            for row in tx.execute(
                "SELECT * FROM tasks WHERE state = 'pending' AND deadline IS NOT NULL "
                "AND deadline < ?",
                (_now(),),
            ).fetchall():
                self._transition_in(
                    tx, Task.from_row(row), TaskState.SHED, summary="deadline passed during downtime"
                )
                expired += 1
        return {"requeued": requeued, "expired": expired}

    def _expire_claims_in(self, tx: sqlite3.Connection, now: float) -> int:
        """Return tasks whose claim outlived its holder to ``pending``.

        A worker killed with SIGKILL cannot release its claim or decrement its
        attempt count. The TTL is what turns that silence into a retry.
        """
        rows = tx.execute(
            "SELECT * FROM tasks WHERE state IN ('claimed', 'running') "
            "AND claimed_until IS NOT NULL AND claimed_until < ?",
            (now,),
        ).fetchall()

        count = 0
        for row in rows:
            task = Task.from_row(row)
            if task.attempts >= task.max_attempts:
                self._transition_in(
                    tx,
                    task,
                    TaskState.FAILED,
                    summary="claim expired, attempts exhausted",
                    failure={
                        "class": "transient",
                        "reason": "worker died and attempts are exhausted",
                        "retryable": False,
                    },
                )
                self._cancel_dependents_in(
                    tx, task.id, f"dependency {task.id} failed: worker died"
                )
                continue
            tx.execute(
                "UPDATE tasks SET state = ?, claim_id = NULL, claimed_until = NULL, "
                "not_before = ? WHERE id = ?",
                (TaskState.PENDING.value, now, task.id),
            )
            self._log.append_in(
                tx,
                actor="bus",
                kind="task.claim_expired",
                trace_id=task.trace_id,
                summary=f"{task.type}: claim expired, requeued",
                payload={"task_id": task.id, "attempts": task.attempts},
                degraded=True,
            )
            count += 1
        return count

    # ------------------------------------------------------------------
    # Backpressure
    # ------------------------------------------------------------------

    def depth(self, lane: Lane | None = None) -> int:
        sql = "SELECT COUNT(*) FROM tasks WHERE state IN ('pending','claimed','running')"
        params: tuple[Any, ...] = ()
        if lane is not None:
            sql += " AND lane = ?"
            params = (int(lane),)
        with self._lock:
            return int(self._conn.execute(sql, params).fetchone()[0])

    def shed(self, *, limit: int | None = None) -> int:
        """Shed oldest sheddable tasks when research depth exceeds the limit.

        Only lanes where :attr:`Lane.sheddable` is true are eligible, so this
        can never drop an order, a risk check, or something you asked for.
        """
        threshold = limit if limit is not None else self.research_depth_limit
        with self._lock, transaction(self._conn) as tx:
            depth = int(
                tx.execute(
                    "SELECT COUNT(*) FROM tasks WHERE state = 'pending' AND lane >= ?",
                    (int(Lane.EVENT),),
                ).fetchone()[0]
            )
            if depth <= threshold:
                return 0
            rows = tx.execute(
                "SELECT * FROM tasks WHERE state = 'pending' AND lane >= ? "
                "ORDER BY created_at ASC LIMIT ?",
                (int(Lane.EVENT), depth - threshold),
            ).fetchall()
            for row in rows:
                self._transition_in(
                    tx, Task.from_row(row), TaskState.SHED, summary="shed under load"
                )
            return len(rows)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    # Reads take the lock too. The connection is shared across threads -- the
    # voice loop dispatches from its worker thread while the daemon drains from
    # its own -- and an unsynchronised SELECT against a connection that is
    # mid-transaction on another thread returns half-written rows, which
    # surfaces as `None is not a valid TaskState` rather than as anything that
    # names the actual problem. A read here is microseconds; the RLock is not
    # the bottleneck, and correctness under two threads is the whole point of
    # putting the queue in a database.

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._get_in(self._conn, task_id)

    def by_trace(self, trace_id: str) -> list[Task]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE trace_id = ? ORDER BY created_at", (trace_id,)
            ).fetchall()
        return [Task.from_row(r) for r in rows]

    def by_state(self, state: TaskState) -> list[Task]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE state = ? ORDER BY lane, created_at",
                (state.value,),
            ).fetchall()
        return [Task.from_row(r) for r in rows]

    def by_idempotency_key(self, key: str) -> list[Task]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE idempotency_key = ? ORDER BY created_at", (key,)
            ).fetchall()
        return [Task.from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_in(self, tx: sqlite3.Connection, task_id: str) -> Task | None:
        row = tx.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return Task.from_row(row) if row else None

    def _transition_in(
        self,
        tx: sqlite3.Connection,
        task: Task,
        state: TaskState,
        *,
        summary: str | None = None,
        result: dict[str, Any] | None = None,
        failure: dict[str, Any] | None = None,
    ) -> None:
        """Write a state change and its log entry in one transaction."""
        tx.execute(
            "UPDATE tasks SET state = ?, result = ?, failure = ?, "
            "claim_id = CASE WHEN ? THEN NULL ELSE claim_id END, "
            "claimed_until = CASE WHEN ? THEN NULL ELSE claimed_until END "
            "WHERE id = ?",
            (
                state.value,
                json.dumps(result) if result else task.result and json.dumps(task.result),
                json.dumps(failure) if failure else task.failure and json.dumps(task.failure),
                state in TERMINAL_STATES,
                state in TERMINAL_STATES,
                task.id,
            ),
        )
        self._log.append_in(
            tx,
            actor="bus",
            kind=f"task.{state.value}",
            trace_id=task.trace_id,
            summary=summary or f"{task.type} -> {state.value}",
            payload={"task_id": task.id, "agent": task.agent, "from": task.state.value},
            degraded=state in (TaskState.SHED, TaskState.CANCELLED),
        )

    def _dependency_state_in(
        self, tx: sqlite3.Connection, task: Task
    ) -> tuple[str, str]:
        """``("ready"|"wait"|"cancel", reason)`` for a task's dependencies."""
        for dep_id in task.depends_on:
            dep = self._get_in(tx, dep_id)
            if dep is None:
                return "cancel", f"dependency {dep_id} does not exist"
            if dep.state is TaskState.DONE:
                continue
            if dep.state in TERMINAL_STATES:
                reason = (dep.failure or {}).get("reason", dep.state.value)
                return "cancel", f"dependency {dep_id} {dep.state.value}: {reason}"
            return "wait", ""
        return "ready", ""

    def _cancel_dependents_in(
        self, tx: sqlite3.Connection, task_id: str, reason: str
    ) -> None:
        """Cancel everything downstream, preserving the parent's reason.

        A dependent is cancelled, never silently dropped -- the orchestrator has
        to be able to speak an honest failure.
        """
        rows = tx.execute(
            "SELECT * FROM tasks WHERE state NOT IN ('done','failed','cancelled','shed')"
        ).fetchall()
        for row in rows:
            task = Task.from_row(row)
            if task_id in task.depends_on:
                self._transition_in(
                    tx,
                    task,
                    TaskState.CANCELLED,
                    summary=reason,
                    failure={"class": "fatal", "reason": reason, "retryable": False},
                )
                self._cancel_dependents_in(tx, task.id, f"parent cancelled: {reason}")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
