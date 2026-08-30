# Spec: Genesis Markdown/00-Meta/Build Order.md  (Phase 1 exit criterion)
"""The Phase 1 exit criterion, as one automated test.

*"A no-op echo agent registers, is scheduled, runs on a cadence, survives a
kill -9, and its runs appear in the Episodic Log."*

Each clause below is a separate assertion, and the whole thing is exercised
end to end at the bottom. The kill is a real ``SIGKILL`` of a real child
process holding a real claim -- not a simulated exception, because an exception
would run ``finally`` blocks and release the claim, which is precisely the
behaviour that does not happen when a process is killed.
"""

from __future__ import annotations

import datetime as dt
import io
import subprocess
import sys
import time
from pathlib import Path

import pytest

from genesis.agents import AgentState
from genesis.bus import Lane, TaskBus, TaskState
from genesis.daemon import Daemon, MarketCalendar, Scheduler, Supervisor
from genesis.observability import Console
from helpers import EchoAgent, echo_declaration

from tests.crash.echo_fixture import CRASH_TTL_SEC, build_daemon

pytestmark = pytest.mark.crash

WORKER = Path(__file__).parent / "daemon_worker.py"
MARKET_OPEN = dt.datetime(2026, 8, 31, 14, 0, tzinfo=dt.UTC)  # 10:00 ET


@pytest.fixture
def daemon(tmp_path: Path):
    d, agent = build_daemon(str(tmp_path / "genesis.db"))
    yield d, agent
    d.shutdown(grace_sec=0)


def run_worker(db: Path, mode: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(WORKER), str(db), mode],
        capture_output=True, text=True, timeout=90,
    )


# --------------------------------------------------------------------------
# 1. registers
# --------------------------------------------------------------------------


def test_the_echo_agent_registers(daemon) -> None:
    d, agent = daemon
    assert d.scheduler.is_registered("echo")
    assert "echo" in d.supervisor.agent_ids
    assert d.scheduler.declaration("echo").model_tier == "none"


def test_boot_starts_the_agent(daemon) -> None:
    d, agent = daemon
    d.boot(MARKET_OPEN)
    assert agent.status().state is AgentState.IDLE
    assert agent.health().alive


# --------------------------------------------------------------------------
# 2. is scheduled, 3. runs on a cadence
# --------------------------------------------------------------------------


def test_the_agent_is_scheduled_and_runs_on_its_cadence(daemon) -> None:
    d, agent = daemon
    d.boot(MARKET_OPEN)

    first = d.tick(MARKET_OPEN)
    assert first.dispatched, "cadence should have dispatched work"
    assert first.ran, "the dispatched task should have run in the same tick"
    assert len(agent.runs) == 1

    # Inside the interval: nothing new.
    assert d.tick(MARKET_OPEN + dt.timedelta(seconds=60)).dispatched == []
    assert len(agent.runs) == 1

    # Past the interval: it runs again.
    d.tick(MARKET_OPEN + dt.timedelta(seconds=301))
    assert len(agent.runs) == 2


def test_nothing_runs_when_the_market_is_shut(daemon) -> None:
    d, agent = daemon
    d.boot(MARKET_OPEN)
    christmas = dt.datetime(2026, 12, 25, 15, 0, tzinfo=dt.UTC)
    assert d.tick(christmas).dispatched == []
    assert agent.runs == []


# --------------------------------------------------------------------------
# 4. survives kill -9
# --------------------------------------------------------------------------


def test_the_worker_really_dies_by_signal(tmp_path: Path) -> None:
    """Guard: if this ever exits cleanly, the test below proves nothing."""
    proc = run_worker(tmp_path / "genesis.db", "crash")
    assert proc.returncode == -9, f"expected SIGKILL, got {proc.returncode}"


def test_a_task_in_flight_when_the_process_dies_is_not_lost(tmp_path: Path) -> None:
    db = tmp_path / "genesis.db"
    crashed = run_worker(db, "crash")
    task_id = crashed.stdout.strip().splitlines()[0]

    bus = TaskBus(db, claim_ttl_sec=CRASH_TTL_SEC)
    assert bus.get(task_id).state is TaskState.RUNNING, "claim outlived the process"

    time.sleep(CRASH_TTL_SEC + 0.2)
    counts = bus.recover()
    assert counts["requeued"] == 1
    assert bus.get(task_id).state is TaskState.PENDING, "work must not be lost"
    bus.close()


def test_the_restarted_daemon_completes_the_orphaned_task(tmp_path: Path) -> None:
    db = tmp_path / "genesis.db"
    crashed = run_worker(db, "crash")
    task_id = crashed.stdout.strip().splitlines()[0]

    time.sleep(CRASH_TTL_SEC + 0.2)
    resumed = run_worker(db, "resume")
    assert resumed.returncode == 0, resumed.stderr
    assert "runs=1" in resumed.stdout, "the restarted agent should have run it once"

    bus = TaskBus(db)
    assert bus.get(task_id).state is TaskState.DONE
    bus.close()


def test_the_task_is_executed_exactly_once_across_the_crash(tmp_path: Path) -> None:
    """Not zero (lost) and not twice (duplicated).

    The idempotency key is what guarantees the second half: the restarted
    daemon's own cadence tries to enqueue the same scheduled run, and the live
    key makes that a no-op rather than a second copy.
    """
    db = tmp_path / "genesis.db"
    crashed = run_worker(db, "crash")
    task_id = crashed.stdout.strip().splitlines()[0]

    time.sleep(CRASH_TTL_SEC + 0.2)
    run_worker(db, "resume")

    bus = TaskBus(db)
    key_tasks = bus.by_idempotency_key("cadence:echo:market-open")
    assert len(key_tasks) == 1, f"expected one task for the key, got {len(key_tasks)}"
    assert key_tasks[0].id == task_id
    assert key_tasks[0].state is TaskState.DONE

    done = [t for t in bus.by_trace("tr_exit_criterion") if t.state is TaskState.DONE]
    assert len(done) == 1
    bus.close()


def test_the_retry_is_visible_as_a_second_attempt(tmp_path: Path) -> None:
    """Exactly-once execution, but the attempt count must tell the truth."""
    db = tmp_path / "genesis.db"
    crashed = run_worker(db, "crash")
    task_id = crashed.stdout.strip().splitlines()[0]

    time.sleep(CRASH_TTL_SEC + 0.2)
    run_worker(db, "resume")

    bus = TaskBus(db)
    assert bus.get(task_id).attempts == 2
    bus.close()


# --------------------------------------------------------------------------
# 5. runs appear in the Episodic Log
# --------------------------------------------------------------------------


def test_the_whole_crash_and_recovery_is_in_the_episodic_log(tmp_path: Path) -> None:
    db = tmp_path / "genesis.db"
    run_worker(db, "crash")
    time.sleep(CRASH_TTL_SEC + 0.2)
    run_worker(db, "resume")

    bus = TaskBus(db)
    kinds = [e.kind for e in bus.log.by_trace("tr_exit_criterion")]

    assert kinds == [
        "task.submitted",
        "task.claimed",
        "task.running",
        "task.claim_expired",
        "task.claimed",
        "task.running",
        "task.done",
    ], kinds
    bus.close()


def test_every_log_entry_has_trace_actor_and_kind(tmp_path: Path) -> None:
    db = tmp_path / "genesis.db"
    run_worker(db, "crash")
    time.sleep(CRASH_TTL_SEC + 0.2)
    run_worker(db, "resume")

    bus = TaskBus(db)
    entries = list(bus.log)
    assert entries, "the log must not be empty"
    for entry in entries:
        assert entry.trace_id, f"{entry.kind} has no trace_id"
        assert entry.actor, f"{entry.kind} has no actor"
        assert entry.kind
    bus.close()


def test_the_crash_is_labelled_degraded_not_silently_retried(tmp_path: Path) -> None:
    """A lost worker is a degradation, and it must be visible as one."""
    db = tmp_path / "genesis.db"
    run_worker(db, "crash")
    time.sleep(CRASH_TTL_SEC + 0.2)
    run_worker(db, "resume")

    bus = TaskBus(db)
    expired = [e for e in bus.log.by_trace("tr_exit_criterion")
               if e.kind == "task.claim_expired"]
    assert len(expired) == 1
    assert expired[0].degraded is True
    bus.close()


# --------------------------------------------------------------------------
# The whole criterion, in one test
# --------------------------------------------------------------------------


def test_phase1_exit_criterion(tmp_path: Path) -> None:
    """Register -> schedule -> run on cadence -> kill -9 -> resume -> exactly once."""
    db = tmp_path / "genesis.db"

    crashed = run_worker(db, "crash")
    assert crashed.returncode == -9
    task_id = crashed.stdout.strip().splitlines()[0]

    time.sleep(CRASH_TTL_SEC + 0.2)
    resumed = run_worker(db, "resume")
    assert resumed.returncode == 0, resumed.stderr

    bus = TaskBus(db)
    task = bus.get(task_id)

    assert task.state is TaskState.DONE                       # not lost
    assert task.attempts == 2                                 # the retry is honest
    assert len(bus.by_idempotency_key("cadence:echo:market-open")) == 1  # not duplicated
    assert task.result["status"] == "ok"
    assert task.result["agent"] == "echo"

    kinds = [e.kind for e in bus.log.by_trace("tr_exit_criterion")]
    assert kinds[0] == "task.submitted"
    assert "task.claim_expired" in kinds                      # the crash is recorded
    assert kinds[-1] == "task.done"
    bus.close()
