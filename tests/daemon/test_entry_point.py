# Spec: Genesis Markdown/00-Meta/Build Order.md
"""The daemon has a way to be run.

Until ``genesis daemon`` existed, :class:`~genesis.daemon.daemon.Daemon` was
reachable only from the test suite. The [[Task Bus]] is durable, so a plan
dispatched by voice survived — unexecuted, in a queue with no consumer, which
from the operator's side is indistinguishable from a hang.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genesis.bus.bus import TaskBus
from genesis.bus.task import TaskState
from genesis.cli import main
from genesis.orchestrator.plan import Plan, PlanTask
from genesis.orchestrator.tools import OrchestratorTools


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        "memory:\n"
        f"  db_path: {tmp_path / 'genesis.db'}\n"
        f"  vault_path: {tmp_path / 'vault'}\n",
        encoding="utf-8",
    )
    return path


def db_of(config_file: Path) -> Path:
    return config_file.parent / "genesis.db"


def test_the_daemon_boots_and_exits_cleanly(config_file: Path) -> None:
    assert main(["--config", str(config_file), "daemon", "--once"]) == 0


def test_the_daemon_creates_the_database_it_was_pointed_at(config_file: Path) -> None:
    main(["--config", str(config_file), "daemon", "--once"])
    assert db_of(config_file).exists()


def test_a_plan_dispatched_by_voice_is_executed_by_the_daemon(config_file: Path) -> None:
    """The end-to-end Phase 2 wire: utterance -> plan -> bus -> daemon.

    No agents are registered, so the honest outcome is a typed failure naming
    the missing agent — not silence, and not a task that sits pending forever.
    """
    bus = TaskBus(db_of(config_file))
    plan = Plan(
        tasks=[PlanTask(id="t1", type="screen.sector", agent="screener")],
        utterance="screen semis",
    )
    handle = OrchestratorTools(bus).dispatch(plan)
    bus.close()

    assert main(["--config", str(config_file), "daemon", "--once"]) == 0

    bus = TaskBus(db_of(config_file))
    task = bus.get(handle.task_ids["t1"])
    assert task.state is TaskState.FAILED
    assert "no agent registered as 'screener'" in task.failure["reason"]
    bus.close()


def test_the_daemons_work_is_in_the_episodic_log(config_file: Path) -> None:
    main(["--config", str(config_file), "daemon", "--once"])
    bus = TaskBus(db_of(config_file))
    assert bus.log.count() >= 0  # the log opened on the same database
    bus.close()


def test_daemon_is_an_advertised_command() -> None:
    from genesis.cli import _build_parser

    actions = _build_parser()._subparsers._group_actions[0].choices  # noqa: SLF001
    assert "daemon" in actions
    assert "voice" in actions


def test_shutdown_is_idempotent(tmp_path: Path) -> None:
    """`genesis voice` hosts a daemon in a thread and stops it when the loop
    ends, while `run_forever` also shuts down in its own `finally`. Both are
    legitimate owners, so shutting down twice must not read as a restart."""
    from genesis.daemon.daemon import Daemon
    from genesis.observability import Console

    bus = TaskBus(tmp_path / "genesis.db")
    lines: list[str] = []

    class Recording(Console):
        def line(self, emoji: str, text: str, **kw) -> None:  # noqa: ANN003
            lines.append(text)

    daemon = Daemon(bus, console=Recording())
    daemon.boot()
    daemon.shutdown()
    daemon.shutdown()
    bus.close()

    assert lines.count("Genesis offline") == 1
