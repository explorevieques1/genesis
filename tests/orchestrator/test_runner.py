# Spec: Genesis Markdown/10-Architecture/Orchestrator Tools.md
"""Running a plan: the three behaviours the note says to get right."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from genesis.bus.bus import TaskBus
from genesis.bus.task import TaskState
from genesis.memory.working import WorkingMemory
from genesis.orchestrator.plan import Plan, PlanTask
from genesis.orchestrator.runner import PlanRunner
from genesis.orchestrator.tools import OrchestratorTools


@pytest.fixture
def bus(tmp_path: Path) -> TaskBus:
    b = TaskBus(tmp_path / "genesis.db")
    yield b
    b.close()


@pytest.fixture
def runner(bus: TaskBus) -> PlanRunner:
    return PlanRunner(OrchestratorTools(bus), memory=WorkingMemory(), await_ms=100)


def plan(*tasks: dict, **extra) -> Plan:
    return Plan(tasks=[PlanTask(**t) for t in tasks], utterance="find a setup in semis", **extra)


ONE = plan({"id": "t1", "type": "screen.sector", "agent": "screener"})
CHAIN = plan(
    {"id": "t1", "type": "screen.sector", "agent": "screener"},
    {"id": "t2", "type": "chart.markup", "agent": "chart-markup", "depends_on": ["t1"]},
    speak_after="t2",
)


def complete(bus: TaskBus, task_id: str, summary: str) -> None:
    bus.complete(task_id, {"spoken_summary": summary, "data": {"rows": list(range(50))}})


def finish_in_background(bus: TaskBus, summaries: dict[str, str], *, delay: float = 0.05):
    """Complete tasks by type shortly after they are submitted.

    Stands in for a running daemon, so the await path is exercised the way it
    actually runs rather than by reaching into the runner's state.
    """

    def work() -> None:
        time.sleep(delay)
        deadline = time.monotonic() + 2.0
        remaining = dict(summaries)
        while remaining and time.monotonic() < deadline:
            for task in bus.by_state(TaskState.PENDING):
                if task.type in remaining and not task.depends_on:
                    complete(bus, task.id, remaining.pop(task.type))
                elif task.type in remaining and all(
                    bus.get(d).state is TaskState.DONE for d in task.depends_on
                ):
                    complete(bus, task.id, remaining.pop(task.type))
            time.sleep(0.01)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread


# -- never block on slow work -------------------------------------------------


def test_slow_work_gets_an_acknowledgement_not_a_hang(runner: PlanRunner) -> None:
    answer = runner.run(CHAIN)
    assert "I'll tell you when it's done" in answer.text
    assert runner.watching  # still ours to speak for


def test_a_finished_plan_speaks_the_agents_own_summary(runner: PlanRunner, bus: TaskBus) -> None:
    finish_in_background(bus, {"screen.sector": "Four candidates in semis. Top is NVDA."})
    answer = runner.run(ONE)
    if answer.source.endswith(":running"):  # the work landed after the window
        answer = _await_collect(runner)
    assert answer.text == "Four candidates in semis. Top is NVDA."
    assert not runner.watching


def test_the_result_is_spoken_from_speak_after_not_the_last_finisher(
    runner: PlanRunner, bus: TaskBus
) -> None:
    finish_in_background(bus, {
        "screen.sector": "Forty candidates.",
        "chart.markup": "Marked up NVDA on the daily.",
    })
    answer = runner.run(CHAIN)
    if answer.source.endswith(":running"):
        answer = _await_collect(runner)
    assert answer.text == "Marked up NVDA on the daily."


def test_collect_is_quiet_while_work_is_still_running(runner: PlanRunner) -> None:
    runner.run(CHAIN)
    assert runner.collect() == []
    assert runner.watching


def test_a_plan_that_finishes_inside_the_await_window_speaks_at_once(bus: TaskBus) -> None:
    # Fast work: the answer comes back from run() itself, with no "on it" and
    # nothing left to announce later.
    runner = PlanRunner(OrchestratorTools(bus), await_ms=2000)
    finish_in_background(bus, {"screen.sector": "Four candidates in semis."}, delay=0.0)
    answer = runner.run(ONE)
    assert answer.text == "Four candidates in semis."
    assert not runner.watching


# -- fail honestly ------------------------------------------------------------


def test_a_failed_dependency_is_spoken_naming_the_real_cause(
    runner: PlanRunner, bus: TaskBus
) -> None:
    runner.run(CHAIN)
    handle = runner.tools.handle(runner.watching[0])
    bus.fail(
        handle.task_ids["t1"],
        {
            "class": "degraded",
            "reason": "the market data feed did not respond",
            "retryable": False,
            "spoken_summary": "couldn't reach the feed",
        },
        retryable=False,
    )
    said = runner.collect()[0].text
    # The chart task is cancelled and looks broken; the screener is the cause.
    assert said == "The screener couldn't reach the feed, so I don't have the rest of it."


def test_a_failure_on_the_spoken_task_reads_as_one_sentence(
    runner: PlanRunner, bus: TaskBus
) -> None:
    runner.run(ONE)
    handle = runner.tools.handle(runner.watching[0])
    bus.fail(
        handle.task_ids["t1"],
        {"class": "fatal", "reason": "no scan named that", "retryable": False},
        retryable=False,
    )
    assert runner.collect()[0].text == "The screener failed: no scan named that."


def test_a_long_failure_reason_is_clipped_before_it_is_spoken(
    runner: PlanRunner, bus: TaskBus
) -> None:
    runner.run(ONE)
    handle = runner.tools.handle(runner.watching[0])
    bus.fail(
        handle.task_ids["t1"],
        {"class": "fatal", "reason": "traceback " * 200, "retryable": False},
        retryable=False,
    )
    assert len(runner.collect()[0].text) < 200


def test_a_result_with_no_summary_says_so_rather_than_inventing_one(
    runner: PlanRunner, bus: TaskBus
) -> None:
    runner.run(ONE)
    handle = runner.tools.handle(runner.watching[0])
    bus.complete(handle.task_ids["t1"], {"data": {"rows": [1, 2, 3]}})
    said = runner.collect()[0].text
    assert "didn't give me anything to say" in said


def test_a_dispatch_fault_is_still_an_answer(bus: TaskBus) -> None:
    class BrokenTools(OrchestratorTools):
        def dispatch(self, plan):  # noqa: ANN001, ANN201
            raise RuntimeError("the database is gone")

    answer = PlanRunner(BrokenTools(bus)).run(ONE)
    assert "couldn't start that" in answer.text
    assert "database is gone" in answer.text


# -- the orchestrator's context stays small -----------------------------------


def test_the_runner_never_reads_a_task_payload(runner: PlanRunner, bus: TaskBus) -> None:
    runner.run(ONE)
    handle = runner.tools.handle(runner.watching[0])
    complete(bus, handle.task_ids["t1"], "Four candidates.")
    answer = runner.collect()[0]
    # 50 rows were in the result; one sentence came out.
    assert answer.text == "Four candidates."


def test_the_plan_is_recorded_in_working_memory(runner: PlanRunner) -> None:
    runner.run(CHAIN)
    plan_record = runner.memory.plan
    assert plan_record is not None
    assert set(plan_record["tasks"]) == {"t1", "t2"}
    assert plan_record["speak_after"] == "t2"


def _await_collect(runner: PlanRunner, timeout: float = 2.0):
    """Poll collect() the way the idle voice loop does."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        answers = runner.collect()
        if answers:
            return answers[0]
        time.sleep(0.02)
    raise AssertionError("the plan never finished")
