# Spec: Genesis Markdown/10-Architecture/Orchestrator Tools.md
"""The note's acceptance criteria, one test each."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from genesis.bus.bus import TaskBus
from genesis.bus.task import Lane, TaskState
from genesis.orchestrator.plan import Plan, PlanTask
from genesis.orchestrator.tools import (
    ACCESSORS,
    TOOL_NAMES,
    AutonomyMode,
    OrchestratorTools,
    ResultTooLargeError,
    Tightening,
)


@pytest.fixture
def bus(tmp_path: Path) -> TaskBus:
    b = TaskBus(tmp_path / "genesis.db")
    yield b
    b.close()


@pytest.fixture
def tools(bus: TaskBus) -> OrchestratorTools:
    return OrchestratorTools(bus)


def plan(*tasks: dict, **extra) -> Plan:
    return Plan(tasks=[PlanTask(**t) for t in tasks], **extra)


THREE_STEP = plan(
    {"id": "t1", "type": "screen.sector", "agent": "screener"},
    {"id": "t2", "type": "idea.synthesize", "agent": "idea-synthesizer", "depends_on": ["t1"]},
    {"id": "t3", "type": "chart.markup", "agent": "chart-markup", "depends_on": ["t2"]},
    speak_after="t3",
)

FAN_OUT = plan(
    {"id": "t1", "type": "screen.sector", "agent": "screener", "args": {"sector": "semis"}},
    {"id": "t2", "type": "screen.sector", "agent": "screener", "args": {"sector": "energy"}},
    {"id": "t3", "type": "screen.sector", "agent": "screener", "args": {"sector": "financials"}},
)


# -- the surface --------------------------------------------------------------


def test_the_tool_surface_is_closed_and_small() -> None:
    public = {n for n in dir(OrchestratorTools) if not n.startswith("_")}
    assert public - ACCESSORS == TOOL_NAMES, "the orchestrator's tool surface changed"
    assert len(TOOL_NAMES) <= 16


# -- dispatch -----------------------------------------------------------------


def test_a_three_step_plan_dispatches_in_one_call(tools: OrchestratorTools, bus: TaskBus) -> None:
    handle = tools.dispatch(THREE_STEP)
    tasks = bus.by_trace(handle.plan_id)
    assert len(tasks) == 3
    assert len({t.trace_id for t in tasks}) == 1  # one plan, one trace


def test_dependencies_are_translated_to_bus_ids(tools: OrchestratorTools, bus: TaskBus) -> None:
    handle = tools.dispatch(THREE_STEP)
    t2 = bus.get(handle.task_ids["t2"])
    assert t2 is not None
    assert t2.depends_on == (handle.task_ids["t1"],)


def test_a_planned_task_always_lands_in_the_user_lane(tools: OrchestratorTools, bus: TaskBus) -> None:
    # The lane is the orchestrator's decision, never the planner's. A plan has
    # no field that could ask for execution priority.
    handle = tools.dispatch(THREE_STEP)
    assert all(bus.get(i).lane is Lane.USER for i in handle.task_ids.values())


def test_three_independent_tasks_are_all_immediately_runnable(
    tools: OrchestratorTools, bus: TaskBus
) -> None:
    tools.dispatch(FAN_OUT)
    claimed = [bus.claim(), bus.claim(), bus.claim()]
    assert all(t is not None for t in claimed)
    assert len({t.id for t in claimed}) == 3  # parallel, not a chain


def test_a_dependent_is_not_runnable_until_its_parent_is_done(
    tools: OrchestratorTools, bus: TaskBus
) -> None:
    handle = tools.dispatch(THREE_STEP)
    first = bus.claim()
    assert first.id == handle.task_ids["t1"]
    assert bus.claim() is None  # t2 and t3 are blocked, correctly


def test_redispatching_the_same_plan_while_it_runs_is_a_no_op(
    tools: OrchestratorTools, bus: TaskBus
) -> None:
    first = tools.dispatch(FAN_OUT)
    again = tools.dispatch(FAN_OUT)
    assert again.task_ids == first.task_ids
    assert len(bus.by_trace(first.plan_id)) == 3


def test_the_same_plan_runs_again_once_the_first_finished(
    tools: OrchestratorTools, bus: TaskBus
) -> None:
    first = tools.dispatch(FAN_OUT)
    for task_id in first.task_ids.values():
        bus.complete(task_id, {"spoken_summary": "done"})
    again = tools.dispatch(FAN_OUT)
    assert again.task_ids != first.task_ids  # asking tomorrow is a new scan


def test_cancelling_a_plan_cancels_every_task(tools: OrchestratorTools, bus: TaskBus) -> None:
    handle = tools.dispatch(FAN_OUT)
    assert tools.cancel(handle.plan_id, "you said stop") == 3
    assert all(
        bus.get(i).state is TaskState.CANCELLED for i in handle.task_ids.values()
    )


# -- await: voice never hangs -------------------------------------------------


def test_await_returns_within_its_timeout_on_slow_work(tools: OrchestratorTools) -> None:
    # Standing in for the note's four-minute backtest: nothing runs the task,
    # so this is the worst case, and it must still return promptly.
    handle = tools.dispatch(THREE_STEP)
    started = time.monotonic()
    state = tools.await_plan(handle.plan_id, timeout_ms=150)
    assert (time.monotonic() - started) < 1.0
    assert not state.done
    assert state.pending


def test_await_returns_immediately_once_everything_is_terminal(
    tools: OrchestratorTools, bus: TaskBus
) -> None:
    handle = tools.dispatch(FAN_OUT)
    for task_id in handle.task_ids.values():
        bus.complete(task_id, {"spoken_summary": "done"})
    state = tools.await_plan(handle.plan_id, timeout_ms=5000)
    assert state.done and not state.any_failed


# -- results: ids and summaries, never rows -----------------------------------


def test_result_summary_returns_only_the_spoken_summary(
    tools: OrchestratorTools, bus: TaskBus
) -> None:
    handle = tools.dispatch(FAN_OUT)
    task_id = handle.task_ids["t1"]
    bus.complete(task_id, {
        "spoken_summary": "Four candidates in semis.",
        "data": {"candidates": [{"symbol": f"S{i}"} for i in range(40)]},
    })
    assert tools.result_summary(task_id) == "Four candidates in semis."


def test_result_refuses_to_return_the_whole_object(tools: OrchestratorTools, bus: TaskBus) -> None:
    handle = tools.dispatch(FAN_OUT)
    bus.complete(handle.task_ids["t1"], {"data": {"candidates": list(range(500))}})
    with pytest.raises(ValueError, match="explicit field names"):
        tools.result(handle.task_ids["t1"], [])


def test_a_projection_that_is_really_a_payload_is_refused(
    tools: OrchestratorTools, bus: TaskBus
) -> None:
    handle = tools.dispatch(FAN_OUT)
    bus.complete(handle.task_ids["t1"], {
        "data": {"candidates": [{"symbol": f"SYM{i}", "score": i} for i in range(40)]}
    })
    with pytest.raises(ResultTooLargeError, match="not rows"):
        tools.result(handle.task_ids["t1"], ["candidates"])


def test_a_small_projection_is_allowed(tools: OrchestratorTools, bus: TaskBus) -> None:
    handle = tools.dispatch(FAN_OUT)
    bus.complete(handle.task_ids["t1"], {"data": {"count": 4, "top": "NVDA"}})
    assert tools.result(handle.task_ids["t1"], ["top"]) == {"top": "NVDA"}


# -- observe ------------------------------------------------------------------


def test_task_status_returns_states_and_nothing_else(tools: OrchestratorTools) -> None:
    handle = tools.dispatch(FAN_OUT)
    statuses = tools.task_status(list(handle.task_ids.values()))
    assert set(statuses.values()) == {"pending"}
    assert tools.task_status(["nope"]) == {"nope": "unknown"}


def test_queue_depth_reports_every_lane(tools: OrchestratorTools) -> None:
    tools.dispatch(FAN_OUT)
    depths = tools.queue_depth()
    assert depths["user"] == 3
    assert depths["execution"] == 0


def test_fleet_status_without_a_supervisor_is_empty_not_an_error(
    tools: OrchestratorTools,
) -> None:
    assert tools.fleet_status() == {}


# -- safety -------------------------------------------------------------------


def test_the_loosest_mode_is_not_expressible_as_a_tightening() -> None:
    # Not "rejected at runtime" -- absent from the type. There is no value to
    # pass that means auto-within-limits.
    assert not hasattr(Tightening, "AUTO_WITHIN_LIMITS")
    assert {t.name for t in Tightening} == {"HALT", "ADVISORY", "CONFIRM"}


def test_tightening_never_raises_autonomy(bus: TaskBus) -> None:
    tools = OrchestratorTools(bus, approval_mode=AutonomyMode.ADVISORY)
    assert tools.tighten_autonomy(Tightening.CONFIRM) is AutonomyMode.ADVISORY
    assert tools.approval_mode is AutonomyMode.ADVISORY


def test_tightening_tightens(bus: TaskBus) -> None:
    tools = OrchestratorTools(bus, approval_mode="auto-within-limits")
    assert tools.tighten_autonomy(Tightening.CONFIRM) is AutonomyMode.CONFIRM
    assert tools.tighten_autonomy(Tightening.HALT) is AutonomyMode.HALT


def test_an_autonomy_change_is_announced_once(bus: TaskBus) -> None:
    seen = []
    tools = OrchestratorTools(
        bus, approval_mode="confirm", on_autonomy_change=lambda m, r: seen.append((m, r))
    )
    tools.tighten_autonomy(Tightening.ADVISORY, "you said scale back")
    tools.tighten_autonomy(Tightening.CONFIRM)  # a no-op: already stricter
    assert seen == [(AutonomyMode.ADVISORY, "you said scale back")]


def test_request_approval_fails_closed_with_no_approver(tools: OrchestratorTools) -> None:
    assert tools.request_approval("prop-1")["approved"] is False


def test_halt_works_with_the_bus_closed(bus: TaskBus) -> None:
    fired = []
    tools = OrchestratorTools(bus, kill_switch=lambda reason: fired.append(reason))
    bus.close()  # the bus is the broken thing
    tools.halt("you said halt")
    assert fired == ["you said halt"]


def test_an_unwired_halt_raises_rather_than_pretending(tools: OrchestratorTools) -> None:
    with pytest.raises(RuntimeError, match="kill switch"):
        tools.halt()


# -- fleet control ------------------------------------------------------------


def test_set_cadence_is_transient_and_reverts_at_the_session_boundary(bus: TaskBus) -> None:
    import datetime as dt
    from zoneinfo import ZoneInfo

    from genesis.daemon.scheduler import Scheduler
    from helpers import echo_declaration

    scheduler = Scheduler()
    scheduler.register(echo_declaration(cadence=[{"type": "market-open", "interval_sec": 60}]))
    tools = OrchestratorTools(bus, scheduler=scheduler)

    assert tools.set_cadence("echo", 900) is True
    et = ZoneInfo("America/New_York")
    now = dt.datetime(2026, 8, 31, 10, 0, tzinfo=et)
    work = scheduler.due(now)
    scheduler.mark_ran(work[0], now)
    # 60s would be due again; the override says 900.
    assert scheduler.due(now + dt.timedelta(seconds=120)) == []
    assert scheduler.due(now + dt.timedelta(seconds=1000)) != []

    assert scheduler.clear_cadence_overrides() == ["echo"]
    assert scheduler.due(now + dt.timedelta(seconds=120)) != []


def test_set_cadence_on_an_unknown_agent_is_a_false_not_a_crash(bus: TaskBus) -> None:
    from genesis.daemon.scheduler import Scheduler

    assert OrchestratorTools(bus, scheduler=Scheduler()).set_cadence("nobody", 60) is False


def test_fleet_control_without_a_supervisor_answers_honestly(tools: OrchestratorTools) -> None:
    assert tools.start_agent("screener") is False
    assert tools.stop_agent("screener") is False
    assert tools.restart_agent("screener") is False


def test_tool_search_returns_nothing_until_the_gateway_exists(tools: OrchestratorTools) -> None:
    assert tools.tool_search("volume profile") == []
