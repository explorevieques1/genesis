# Spec: Genesis Markdown/00-Meta/Build Order.md  (Phase 1 exit criterion)
"""Shared daemon construction for the exit-criterion test and its child process."""

from __future__ import annotations

import io

from genesis.bus import TaskBus
from genesis.daemon import Daemon, MarketCalendar, Scheduler, Supervisor
from genesis.observability import Console

from helpers import EchoAgent, echo_declaration

# Short enough that the test does not sleep for 30 seconds, long enough that the
# crashing child cannot outlive its own claim before it is killed.
CRASH_TTL_SEC = 1.0

__all__ = ["CRASH_TTL_SEC", "build_daemon"]


def build_daemon(db: str) -> tuple[Daemon, EchoAgent]:
    bus = TaskBus(db, claim_ttl_sec=CRASH_TTL_SEC)
    calendar = MarketCalendar()
    agent = EchoAgent(echo_declaration(
        cadence=[{"type": "market-open", "interval_sec": 300}]
    ))
    daemon = Daemon(
        bus,
        calendar=calendar,
        scheduler=Scheduler(calendar),
        supervisor=Supervisor(),
        console=Console(io.StringIO()),
    )
    daemon.register(agent)
    return daemon, agent
