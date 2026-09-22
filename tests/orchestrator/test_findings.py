# Spec: Genesis Markdown/40-Memory/Research Directory.md
"""Findings: a plan's pieces are remembered, and a fresh one is not rerun."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from genesis.bus.bus import TaskBus
from genesis.bus.task import TaskState
from genesis.orchestrator.plan import Plan, PlanTask
from genesis.orchestrator.runner import PlanRunner
from genesis.orchestrator.tools import OrchestratorTools
from genesis.research.schema import ResearchNote
from genesis.research.store import ResearchStore

ROWS = [{"symbol": "ADBE", "name": "Adobe Inc."}, {"symbol": "NVDA", "name": "NVIDIA Corporation"}]


@pytest.fixture(autouse=True)
def snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("genesis.screener.snapshot.load_snapshot", lambda: SimpleNamespace(rows=ROWS))


@pytest.fixture
def bus(tmp_path: Path) -> TaskBus:
    b = TaskBus(tmp_path / "genesis.db")
    yield b
    b.close()


@pytest.fixture
def store(tmp_path: Path) -> ResearchStore:
    return ResearchStore(path=tmp_path / "research.db", vault=None, graph=None)


@pytest.fixture
def runner(bus: TaskBus, store: ResearchStore) -> PlanRunner:
    return PlanRunner(OrchestratorTools(bus), await_ms=0, research=store)


def plan(*tasks: dict, utterance: str = "has Adobe drifted from fair value", **extra) -> Plan:
    return Plan(tasks=[PlanTask(**t) for t in tasks], utterance=utterance, **extra)


VALUE = {"id": "t1", "type": "company.valuation", "agent": "fundamental", "args": {"subject": "Adobe"}}


def settle(runner: PlanRunner, bus: TaskBus, summaries: dict[str, str], *, degraded: bool = False):
    """Complete every pending task (parents first), then collect the spoken answer."""
    for _ in range(4):
        for task in bus.by_state(TaskState.PENDING):
            if all(bus.get(d).state is TaskState.DONE for d in task.depends_on):
                bus.complete(task.id, {"spoken_summary": summaries[task.type],
                                       "data": {"gap": -0.12}, "degraded": degraded})
    answers = runner.collect()
    assert len(answers) == 1
    return answers[0]


def stored(store: ResearchStore, *, hours_ago: float, summary: str = "Adobe is 12% under fair value.",
           degraded: bool = False) -> None:
    store.put(ResearchNote(
        id=f"res_fnd_old_{hours_ago}", kind="finding", subject="ADBE:company.valuation",
        title="ADBE — company.valuation", created_by="fundamental", summary=summary,
        created=datetime.now(UTC) - timedelta(hours=hours_ago), half_life_hours=24 * 60,
        degraded=degraded, caveats=("x",) if degraded else (),
    ), mirror=False)


def submitted(bus: TaskBus) -> int:
    return sum(len(bus.by_state(state)) for state in TaskState)


def test_a_finished_task_becomes_a_finding_on_its_prompts_trace(runner, bus, store) -> None:
    runner.run(plan(VALUE))
    settle(runner, bus, {"company.valuation": "Adobe is 12% under fair value."})

    [finding] = store.findings("ADBE")
    assert finding.subject == "ADBE:company.valuation"
    assert finding.data["result"] == {"gap": -0.12}
    assert store.by_trace(finding.trace_id) == [finding]


def test_a_fresh_finding_answers_instead_of_rerunning(runner, bus, store) -> None:
    stored(store, hours_ago=2)
    answer = runner.run(plan(VALUE))
    assert answer.source == "plan:reused"
    assert "12% under fair value" in answer.text and answer.text.startswith("As of")
    assert submitted(bus) == 0


def test_a_stale_finding_reruns_and_says_what_changed(runner, bus, store) -> None:
    stored(store, hours_ago=30)
    runner.run(plan(VALUE))
    assert submitted(bus) == 1
    answer = settle(runner, bus, {"company.valuation": "Adobe is 3% under fair value."})
    assert answer.text.startswith("Adobe is 3% under fair value.")
    assert "Last time" in answer.text and "12%" in answer.text


def test_a_degraded_finding_is_never_reused(runner, bus, store) -> None:
    stored(store, hours_ago=1, degraded=True)
    runner.run(plan(VALUE))
    assert submitted(bus) == 1


def test_refresh_bypasses_reuse(runner, bus, store) -> None:
    stored(store, hours_ago=1)
    runner.run(plan(VALUE, utterance="refresh Adobe fair value"))
    assert submitted(bus) == 1


def test_a_task_others_depend_on_is_rerun_even_when_fresh(runner, bus, store) -> None:
    stored(store, hours_ago=1)
    chart = {"id": "t2", "type": "chart.markup", "agent": "chart-markup",
             "args": {"symbol": "ADBE"}, "depends_on": ["t1"]}
    runner.run(plan(VALUE, chart, speak_after="t2"))
    assert submitted(bus) == 2  # the chart reads t1's result off the bus


def test_part_reused_part_run_speaks_both(runner, bus, store) -> None:
    stored(store, hours_ago=1)
    chips = {"id": "t2", "type": "company.valuation", "agent": "fundamental", "args": {"subject": "NVDA"}}
    first = runner.run(plan(VALUE, chips))
    assert submitted(bus) == 1
    assert first.text.startswith("As of")  # what is known is said before the wait


def test_recall_names_what_is_stored_for_the_planner(runner, store) -> None:
    stored(store, hours_ago=1)
    assert "ADBE:company.valuation" in runner.known("what about Adobe earnings?")
    assert runner.known("what about semis?") == ""


def test_a_slow_plan_is_remembered_even_if_nobody_collects_it(runner, bus, store) -> None:
    """The typed path never calls collect(); learning must not wait for a listener."""
    import time

    runner.run(plan(VALUE))  # await_ms=0: returns "running"
    [task] = bus.by_state(TaskState.PENDING)
    bus.complete(task.id, {"spoken_summary": "Adobe is 12% under fair value.", "data": {}})
    deadline = time.monotonic() + 5
    while not store.findings("ADBE") and time.monotonic() < deadline:
        time.sleep(0.05)
    assert store.findings("ADBE")
