# Spec: Genesis Markdown/60-UI/Automation.md
"""A workflow fires from the one scheduler, walks its chain, and stays deleted."""

from __future__ import annotations

import datetime as dt
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from genesis.automation.runner import register_all, sync
from genesis.automation.store import VersionConflict, WorkflowStore
from genesis.automation.workflow import Workflow
from genesis.bus import TaskBus, TaskState
from genesis.daemon import Daemon, MarketCalendar, Scheduler, Supervisor
from genesis.observability import Console

SEVEN_ET = dt.datetime(2026, 8, 31, 11, 0, tzinfo=dt.UTC)


@dataclass
class Result:
    content: Any
    structured: dict[str, Any] | None = None


@dataclass
class FakeGateway:
    items: list[dict[str, Any]] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)
    granted: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def call(self, agent: str, capability: str, arguments: dict | None = None, **_: Any):
        self.calls.append((agent, capability))
        return Result(content=str(self.items), structured={"results": self.items})

    def grant(self, declaration) -> None:  # noqa: ANN001
        self.granted[declaration.id] = declaration.tools

    def revoke(self, agent: str) -> None:
        self.granted.pop(agent, None)


def workflow(**overrides: Any) -> Workflow:
    base = {
        "id": "tesla-news", "name": "Tesla news",
        "trigger": {"type": "cron", "at": "07:00"},
        "start": "news",
        "steps": [
            {"id": "news", "kind": "gather", "capability": "news.search",
             "args": {"query": "Tesla"}, "next": "enough"},
            {"id": "enough", "kind": "check", "input": "news", "predicate": "min_count",
             "value": 2, "next": "synopsis", "on_fail": "quiet"},
            {"id": "synopsis", "kind": "run", "agent": "topic-researcher", "input": "news"},
            {"id": "quiet", "kind": "run", "agent": "digest"},
        ],
    }
    base.update(overrides)
    return Workflow.model_validate(base)


@pytest.fixture
def world(tmp_path: Path):
    bus = TaskBus(tmp_path / "genesis.db", claim_ttl_sec=5.0)
    store = WorkflowStore(tmp_path / "workflows.db")
    gateway = FakeGateway(items=[{"title": "a"}, {"title": "b"}])

    def daemon() -> Daemon:
        calendar = MarketCalendar()
        return Daemon(bus, calendar=calendar, scheduler=Scheduler(calendar),
                      supervisor=Supervisor(), console=Console(io.StringIO()))

    yield bus, store, gateway, daemon
    store.close()
    bus.close()


def _submitted(bus: TaskBus, agent: str) -> list:
    """Whatever state it reached -- the tick drains what the workflow submits."""
    return [t for state in TaskState for t in bus.by_state(state) if t.agent == agent]


def test_an_enabled_workflow_fires_from_the_scheduler_and_takes_the_pass_branch(world) -> None:
    bus, store, gateway, make = world
    store.save(workflow(), author="operator", enabled=True)
    daemon = make()
    assert register_all(daemon, store, gateway) == 1
    assert gateway.granted["wf-tesla-news"] == ("news.search",)

    report = daemon.tick(SEVEN_ET)
    assert len(report.dispatched) == 1
    assert gateway.calls == [("wf-tesla-news", "news.search")]

    run = store.runs("tesla-news")[0]
    assert run["status"] == "ok"
    assert [s["status"] for s in run["steps"]] == ["ok", "ok", "ok", "skipped"]
    follow_up = _submitted(bus, "topic-researcher")
    assert len(follow_up) == 1 and follow_up[0].args["input"]["structured"]["results"]
    assert _submitted(bus, "digest") == []


def test_a_failed_check_takes_the_fail_branch(world) -> None:
    bus, store, gateway, make = world
    gateway.items = []
    store.save(workflow(), author="operator", enabled=True)
    daemon = make()
    register_all(daemon, store, gateway)
    daemon.tick(SEVEN_ET)

    run = store.runs("tesla-news")[0]
    assert run["status"] == "ok", "a branch taken is not a failure"
    assert len(_submitted(bus, "digest")) == 1
    assert _submitted(bus, "topic-researcher") == []


def test_a_failed_check_without_a_branch_fails_the_run_loudly(world) -> None:
    bus, store, gateway, make = world
    gateway.items = []
    wf = workflow(steps=[
        {"id": "news", "kind": "gather", "capability": "news.search", "next": "enough"},
        {"id": "enough", "kind": "check", "input": "news", "predicate": "non_empty"},
    ])
    store.save(wf, author="operator", enabled=True)
    daemon = make()
    register_all(daemon, store, gateway)
    daemon.tick(SEVEN_ET)

    assert store.runs("tesla-news")[0]["status"] == "failed"
    assert bus.log.by_kind("automation.run.failed")
    assert daemon.supervisor.record("wf-tesla-news").consecutive == 0, "work failed, not the agent"


def test_a_disabled_workflow_is_not_registered(world) -> None:
    _bus, store, gateway, make = world
    store.save(workflow(), author="orchestrator", enabled=False)
    daemon = make()
    assert register_all(daemon, store, gateway) == 0
    assert daemon.tick(SEVEN_ET).dispatched == []


def test_delete_unregisters_and_a_restart_does_not_resurrect_it(world) -> None:
    _bus, store, gateway, make = world
    store.save(workflow(), author="operator", enabled=True)
    daemon = make()
    register_all(daemon, store, gateway)

    store.delete("tesla-news", author="operator")
    assert sync(daemon, store, "tesla-news", gateway) is False
    assert daemon.supervisor.agent("wf-tesla-news") is None
    assert "wf-tesla-news" not in gateway.granted
    assert daemon.tick(SEVEN_ET).dispatched == []

    restarted = make()
    assert register_all(restarted, store, gateway) == 0
    assert restarted.tick(SEVEN_ET).dispatched == []


def test_a_same_day_restart_does_not_double_fire(world) -> None:
    _bus, store, gateway, make = world
    store.save(workflow(), author="operator", enabled=True)
    first = make()
    register_all(first, store, gateway)
    assert len(first.tick(SEVEN_ET).dispatched) == 1

    second = make()
    register_all(second, store, gateway)
    assert second.tick(SEVEN_ET + dt.timedelta(hours=3)).dispatched == []


def test_versions_append_and_a_stale_edit_is_refused(world) -> None:
    _bus, store, _gateway, _make = world
    v1 = store.save(workflow(), author="operator")
    store.save(workflow(name="Tesla news v2"), author="operator", base_version=v1.version)
    with pytest.raises(VersionConflict):
        store.save(workflow(name="lost update"), author="operator", base_version=v1.version)
    history = store.versions("tesla-news")
    assert [v.version for v in history] == [2, 1]
    assert history[0].body["name"] == "Tesla news v2"
