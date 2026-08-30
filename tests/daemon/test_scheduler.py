# Spec: Genesis Markdown/10-Architecture/Daemon And Cadence.md
"""Cadence firing rules."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from genesis.daemon import MarketCalendar, Scheduler, SessionState
from helpers import echo_declaration

ET = ZoneInfo("America/New_York")


@pytest.fixture
def sched() -> Scheduler:
    return Scheduler(MarketCalendar())


def at(hh: int, mm: int = 0, day: int = 31) -> dt.datetime:
    return dt.datetime(2026, 8, day, hh, mm, tzinfo=ET)


def test_registration_is_idempotent(sched: Scheduler) -> None:
    sched.register(echo_declaration())
    sched.register(echo_declaration())
    assert sched.agent_ids == ["echo"]


def test_reregistering_keeps_run_history(sched: Scheduler) -> None:
    """A supervised restart must not make an agent instantly due again."""
    sched.register(echo_declaration())
    work = sched.due(at(10))[0]
    sched.mark_ran(work, at(10))

    sched.register(echo_declaration())
    assert sched.due(at(10, 0)) == []


def test_market_open_cadence_fires_only_in_market_hours(sched: Scheduler) -> None:
    sched.register(echo_declaration(cadence=[{"type": "market-open", "interval_sec": 60}]))
    assert sched.due(at(10)) != []
    assert sched.due(at(22)) == []


def test_market_open_covers_premarket_and_afterhours(sched: Scheduler) -> None:
    """A gap scan at 08:00 is market work."""
    sched.register(echo_declaration(cadence=[{"type": "market-open", "interval_sec": 60}]))
    assert sched.due(at(8)) != []
    assert sched.due(at(17)) != []


def test_market_closed_cadence_is_the_complement(sched: Scheduler) -> None:
    sched.register(echo_declaration(cadence=[{"type": "market-closed", "interval_sec": 60}]))
    assert sched.due(at(22)) != []
    assert sched.due(at(10)) == []


def test_interval_is_respected_after_a_run(sched: Scheduler) -> None:
    sched.register(echo_declaration(cadence=[{"type": "market-open", "interval_sec": 300}]))
    work = sched.due(at(10))[0]
    sched.mark_ran(work, at(10))

    assert sched.due(at(10, 4)) == [], "must not fire before the interval elapses"
    assert sched.due(at(10, 5)) != []


def test_cron_fires_once_per_day(sched: Scheduler) -> None:
    sched.register(echo_declaration(cadence=[{"type": "cron", "at": "07:00"}]))
    work = sched.due(at(7, 0))
    assert work != []
    sched.mark_ran(work[0], at(7, 0))
    assert sched.due(at(7, 1)) == []
    assert sched.due(at(12, 0)) == []


def test_cron_does_not_fire_before_its_time(sched: Scheduler) -> None:
    sched.register(echo_declaration(cadence=[{"type": "cron", "at": "07:00"}]))
    assert sched.due(at(6, 59)) == []


def test_cron_missed_while_down_fires_once_late_not_repeatedly(sched: Scheduler) -> None:
    """A daemon down at 07:00 fires the brief once when it returns, not hourly."""
    sched.register(echo_declaration(cadence=[{"type": "cron", "at": "07:00"}]))
    work = sched.due(at(11, 0))
    assert work != [], "the missed cron should fire once on return"
    sched.mark_ran(work[0], at(11, 0))
    assert sched.due(at(11, 30)) == []


def test_cron_fires_again_the_next_day(sched: Scheduler) -> None:
    sched.register(echo_declaration(cadence=[{"type": "cron", "at": "07:00"}]))
    work = sched.due(at(7, 0, day=31))
    sched.mark_ran(work[0], at(7, 0, day=31))
    assert sched.due(dt.datetime(2026, 9, 1, 7, 0, tzinfo=ET)) != []


def test_on_demand_never_fires_from_the_clock(sched: Scheduler) -> None:
    sched.register(echo_declaration(cadence=[{"type": "on-demand"}]))
    assert sched.due(at(10)) == []
    assert sched.due(at(22)) == []


def test_event_cadence_fires_only_on_its_event(sched: Scheduler) -> None:
    sched.register(echo_declaration(cadence=[{"type": "event", "on": ["news.spike"]}]))
    assert sched.due(at(10)) == []
    assert [w.agent_id for w in sched.subscribers("news.spike")] == ["echo"]
    assert sched.subscribers("level.touched") == []


def test_multiple_cadences_on_one_agent(sched: Scheduler) -> None:
    """The Idea Synthesizer shape: interval + cron + event."""
    sched.register(echo_declaration(cadence=[
        {"type": "market-open", "interval_sec": 900},
        {"type": "cron", "at": "07:00"},
        {"type": "event", "on": ["news.spike"]},
    ]))
    assert len(sched.due(at(7, 0))) == 2  # interval + cron, not the event


def test_nothing_is_due_on_a_holiday_for_market_open(sched: Scheduler) -> None:
    """'Scans on Christmas' is the failure the note names."""
    sched.register(echo_declaration(cadence=[{"type": "market-open", "interval_sec": 60}]))
    christmas = dt.datetime(2026, 12, 25, 10, 0, tzinfo=ET)
    assert sched.due(christmas) == []


def test_closed_work_runs_on_a_holiday(sched: Scheduler) -> None:
    sched.register(echo_declaration(cadence=[{"type": "market-closed", "interval_sec": 60}]))
    assert sched.due(dt.datetime(2026, 12, 25, 10, 0, tzinfo=ET)) != []


def test_naive_datetime_is_rejected(sched: Scheduler) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        sched.due(dt.datetime(2026, 8, 31, 10, 0))


def test_next_run_at_reports_the_upcoming_fire(sched: Scheduler) -> None:
    sched.register(echo_declaration(cadence=[{"type": "market-open", "interval_sec": 300}]))
    work = sched.due(at(10))[0]
    sched.mark_ran(work, at(10))
    assert sched.next_run_at("echo", at(10)) == at(10, 5)
