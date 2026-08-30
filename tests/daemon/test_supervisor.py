# Spec: Genesis Markdown/10-Architecture/Daemon And Cadence.md
"""Crash -> backoff restart -> degraded, and knowing when to stop trying."""

from __future__ import annotations

import datetime as dt

import pytest

from genesis.agents import AgentState
from genesis.daemon import Supervisor
from genesis.daemon.supervisor import BACKOFF_CAP_SEC
from helpers import EchoAgent

T0 = dt.datetime(2026, 8, 31, 10, 0, tzinfo=dt.UTC)


@pytest.fixture
def events() -> list[tuple[str, dict]]:
    return []


@pytest.fixture
def sup(events: list) -> Supervisor:
    return Supervisor(on_event=lambda name, data: events.append((name, data)))


@pytest.fixture
def agent(sup: Supervisor) -> EchoAgent:
    a = EchoAgent()
    sup.supervise(a)
    a.start()
    return a


def test_backoff_is_exponential_and_capped(sup: Supervisor, agent: EchoAgent) -> None:
    """1, 2, 4, 8... capped at 60."""
    rec = sup.record("echo")
    seen = []
    for i in range(10):
        rec.consecutive = i + 1
        seen.append(rec.backoff_sec())
    assert seen[:5] == [1.0, 2.0, 4.0, 8.0, 16.0]
    assert max(seen) == BACKOFF_CAP_SEC


def test_a_crash_schedules_a_restart(sup: Supervisor, agent: EchoAgent) -> None:
    assert sup.note_crash("echo", "boom", T0) is True
    assert sup.due_restarts(T0) == []
    assert sup.due_restarts(T0 + dt.timedelta(seconds=1)) == ["echo"]


def test_restart_brings_the_agent_back(sup: Supervisor, agent: EchoAgent) -> None:
    sup.note_crash("echo", "boom", T0)
    assert sup.restart("echo", T0 + dt.timedelta(seconds=1))
    assert agent.status().state is AgentState.IDLE
    assert agent.starts == 2


def test_five_crashes_in_ten_minutes_gives_up(
    sup: Supervisor, agent: EchoAgent, events: list
) -> None:
    """A supervisor that restarts forever turns a bug into a loop."""
    for i in range(4):
        assert sup.note_crash("echo", "boom", T0 + dt.timedelta(seconds=i)) is True
    assert sup.note_crash("echo", "boom", T0 + dt.timedelta(seconds=5)) is False

    assert agent.status().state is AgentState.DEGRADED
    assert sup.record("echo").given_up
    assert ("agent.down", ...) or events
    assert events[-1][0] == "agent.down"
    assert events[-1][1]["agent"] == "echo"


def test_a_given_up_agent_is_not_restarted(sup: Supervisor, agent: EchoAgent) -> None:
    for i in range(5):
        sup.note_crash("echo", "boom", T0 + dt.timedelta(seconds=i))
    assert sup.due_restarts(T0 + dt.timedelta(hours=1)) == []
    assert sup.restart("echo", T0 + dt.timedelta(hours=1)) is False


def test_crashes_outside_the_window_do_not_count(sup: Supervisor, agent: EchoAgent) -> None:
    for i in range(4):
        sup.note_crash("echo", "boom", T0 + dt.timedelta(seconds=i))
    later = T0 + dt.timedelta(minutes=20)
    assert sup.note_crash("echo", "boom", later) is True, "window should have slid"
    assert not sup.record("echo").given_up


def test_a_clean_run_resets_backoff_but_not_the_crash_budget(
    sup: Supervisor, agent: EchoAgent
) -> None:
    """Crashing five times in ten minutes spends the budget even with good runs between."""
    for i in range(4):
        sup.note_crash("echo", "boom", T0 + dt.timedelta(seconds=i))
        sup.note_healthy("echo")
    assert sup.record("echo").consecutive == 0
    assert sup.note_crash("echo", "boom", T0 + dt.timedelta(seconds=5)) is False


def test_health_report_covers_the_fleet(sup: Supervisor, agent: EchoAgent) -> None:
    report = sup.health_report()
    assert report["echo"]["alive"] is True
    assert report["echo"]["given_up"] is False


def test_degraded_agents_are_listed(sup: Supervisor, agent: EchoAgent) -> None:
    for i in range(5):
        sup.note_crash("echo", "boom", T0 + dt.timedelta(seconds=i))
    assert sup.degraded_agents() == ["echo"]


def test_a_failed_restart_counts_as_another_crash(sup: Supervisor, agent: EchoAgent) -> None:
    def boom() -> None:
        raise RuntimeError("still broken")

    agent.on_start = boom  # type: ignore[method-assign]
    sup.note_crash("echo", "boom", T0)
    assert sup.restart("echo", T0 + dt.timedelta(seconds=1)) is False
    assert len(sup.record("echo").crashes) == 2
