# Spec: Genesis Markdown/10-Architecture/Daemon And Cadence.md
"""The loop: dispatch, drain, supervise, announce."""

from __future__ import annotations

import datetime as dt
import io
from pathlib import Path

import pytest

from genesis.agents import AgentState
from genesis.bus import Lane, TaskBus, TaskState
from genesis.daemon import Daemon, MarketCalendar, Scheduler, SessionState, Supervisor
from genesis.errors import FatalError, TransientError
from genesis.observability import Console
from helpers import EchoAgent, echo_declaration

OPEN = dt.datetime(2026, 8, 31, 14, 0, tzinfo=dt.UTC)      # 10:00 ET
CLOSED = dt.datetime(2026, 9, 1, 2, 0, tzinfo=dt.UTC)      # 22:00 ET prev day


@pytest.fixture
def parts(tmp_path: Path):
    bus = TaskBus(tmp_path / "genesis.db", claim_ttl_sec=5.0)
    calendar = MarketCalendar()
    console_out = io.StringIO()
    daemon = Daemon(
        bus, calendar=calendar, scheduler=Scheduler(calendar),
        supervisor=Supervisor(), console=Console(console_out),
    )
    agent = EchoAgent(echo_declaration(cadence=[{"type": "market-open", "interval_sec": 300}]))
    daemon.register(agent)
    yield daemon, agent, console_out
    bus.close()


# --------------------------------------------------------------------------
# Boot
# --------------------------------------------------------------------------


def test_boot_announces_itself(parts) -> None:
    daemon, agent, out = parts
    daemon.boot(OPEN)
    text = out.getvalue()
    assert "Genesis online" in text
    assert "Market open" in text
    assert "1 agent(s) idle" in text


def test_boot_announces_a_holiday(parts) -> None:
    daemon, agent, out = parts
    daemon.boot(dt.datetime(2026, 12, 25, 15, 0, tzinfo=dt.UTC))
    assert "holiday" in out.getvalue()


def test_boot_recovers_the_bus_before_starting_agents(parts) -> None:
    """A resumed task must not be raced by a freshly scheduled one."""
    daemon, agent, out = parts
    daemon.bus.submit(type="echo.run", agent="echo")
    daemon.bus.claim(ttl_sec=0.001)
    import time; time.sleep(0.02)

    result = daemon.boot(OPEN)
    assert result["requeued"] == 1
    assert "requeued" in out.getvalue()
    assert agent.status().state is AgentState.IDLE


# --------------------------------------------------------------------------
# Dispatch and drain
# --------------------------------------------------------------------------


def test_a_tick_dispatches_and_runs(parts) -> None:
    daemon, agent, out = parts
    daemon.boot(OPEN)
    report = daemon.tick(OPEN)
    assert report.session is SessionState.OPEN
    assert len(report.dispatched) == 1
    assert len(report.ran) == 1
    assert len(agent.runs) == 1


def test_market_closed_runs_the_other_roster(parts) -> None:
    daemon, agent, out = parts
    daemon.register(EchoAgent(echo_declaration(
        id="nightly", cadence=[{"type": "market-closed", "interval_sec": 300}]
    )))
    daemon.boot(CLOSED)
    report = daemon.tick(CLOSED)
    assert len(report.dispatched) == 1
    assert daemon.bus.get(report.dispatched[0]).agent == "nightly"


def test_critical_lanes_drain_before_research(parts) -> None:
    """An order must never queue behind a scan."""
    daemon, agent, out = parts
    daemon.boot(OPEN)
    daemon.bus.submit(type="echo.run", agent="echo", lane=Lane.RESEARCH,
                      idempotency_key="r1")
    daemon.bus.submit(type="echo.run", agent="echo", lane=Lane.EXECUTION,
                      idempotency_key="x1")

    report = daemon.tick(OPEN)
    lanes = [daemon.bus.get(tid).lane for tid in report.ran]
    assert lanes[0] is Lane.EXECUTION


def test_a_task_for_an_unregistered_agent_fails_honestly(parts) -> None:
    daemon, agent, out = parts
    daemon.boot(OPEN)
    task = daemon.bus.submit(type="ghost.run", agent="ghost", lane=Lane.RESEARCH)
    daemon.tick(OPEN)
    stored = daemon.bus.get(task.id)
    assert stored.state is TaskState.FAILED
    assert "no agent registered" in stored.failure["reason"]


def test_a_degraded_agent_is_not_dispatched_to(parts) -> None:
    daemon, agent, out = parts
    daemon.boot(OPEN)
    agent.mark_degraded("feed stale")
    assert daemon.tick(OPEN).dispatched == []


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------


def test_a_transient_failure_is_retried_not_treated_as_a_crash(parts) -> None:
    """The work failed, not the agent — the bus retries and nobody restarts."""
    daemon, agent, out = parts
    daemon.boot(OPEN)
    agent.fail_with = TransientError("blip")
    daemon.tick(OPEN)

    assert len(daemon.supervisor.record("echo").crashes) == 0
    task = daemon.bus.by_state(TaskState.PENDING)
    assert task, "a transient failure must leave the task retryable"
    assert task[0].not_before is not None, "and it must back off, not spin"


def test_a_fatal_failure_counts_as_a_crash(parts) -> None:
    """It is the agent that is broken, not the work."""
    daemon, agent, out = parts
    daemon.boot(OPEN)
    agent.fail_with = FatalError("bad config")
    daemon.tick(OPEN)
    assert len(daemon.supervisor.record("echo").crashes) == 1


def test_repeated_fatals_give_up_and_emit_agent_down(parts) -> None:
    """Five crashes inside the ten-minute window spends the budget.

    Work is submitted directly rather than via the cadence: the agent's 300s
    interval would spread five runs over 25 minutes, and the sliding window
    would (correctly) have dropped the early crashes by then.
    """
    daemon, agent, out = parts
    daemon.boot(OPEN)
    agent.fail_with = FatalError("bad config")

    now = OPEN
    for i in range(5):
        daemon.bus.submit(type="echo.run", agent="echo", lane=Lane.RESEARCH,
                          idempotency_key=f"fatal-{i}")
        daemon.tick(now)
        now += dt.timedelta(seconds=10)

    assert daemon.supervisor.record("echo").given_up
    assert agent.status().state is AgentState.DEGRADED
    assert [e.kind for e in daemon.bus.log.by_kind("agent.down")], "agent.down not logged"


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


def test_an_event_is_logged_before_it_fans_out(parts) -> None:
    """Nothing is lost on a crash mid-fanout."""
    daemon, agent, out = parts
    daemon.register(EchoAgent(echo_declaration(
        id="watcher", cadence=[{"type": "event", "on": ["news.spike"]}]
    )))
    daemon.boot(OPEN)
    daemon.publish("news.spike", {"symbols": ["NVDA"]})

    logged = daemon.bus.log.by_kind("news.spike")
    assert logged, "the event must be persisted before dispatch"
    subscriber_tasks = [t for t in daemon.bus.by_state(TaskState.PENDING)
                        if t.agent == "watcher"]
    assert len(subscriber_tasks) == 1
    assert subscriber_tasks[0].trace_id == logged[0].trace_id


def test_non_subscribers_are_not_woken(parts) -> None:
    daemon, agent, out = parts
    daemon.boot(OPEN)
    daemon.publish("news.spike", {})
    assert [t for t in daemon.bus.by_state(TaskState.PENDING) if t.agent == "echo"] == []


def test_a_session_change_emits_a_market_event(parts) -> None:
    daemon, agent, out = parts
    daemon.boot(dt.datetime(2026, 8, 31, 13, 0, tzinfo=dt.UTC))  # premarket
    daemon.tick(dt.datetime(2026, 8, 31, 13, 0, tzinfo=dt.UTC))
    daemon.tick(OPEN)  # crosses into open
    assert daemon.bus.log.by_kind("market.open")


# --------------------------------------------------------------------------
# Restart
# --------------------------------------------------------------------------


def test_a_crashed_agent_is_restarted_after_backoff(parts) -> None:
    daemon, agent, out = parts
    daemon.boot(OPEN)
    daemon.supervisor.note_crash("echo", "boom", OPEN)

    assert daemon.tick(OPEN).restarted == []
    later = OPEN + dt.timedelta(seconds=2)
    assert daemon.tick(later).restarted == ["echo"]
    assert agent.starts == 2


def test_shutdown_stops_every_agent(parts) -> None:
    daemon, agent, out = parts
    daemon.boot(OPEN)
    daemon.shutdown(grace_sec=0)
    assert agent.status().state is AgentState.DOWN
    assert "Genesis offline" in out.getvalue()
