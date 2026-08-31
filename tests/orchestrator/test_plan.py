# Spec: Genesis Markdown/10-Architecture/Orchestrator.md
"""Plan validation -- the wall between model output and the bus.

Every test here is a thing a language model has actually done to a JSON schema,
written as the rejection it must produce.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from genesis.orchestrator.plan import (
    MAX_ARGS_CHARS,
    Plan,
    PlanError,
    PlanTask,
    parse_plan,
    topological_order,
    validate_plan,
)
from genesis.orchestrator.registry import Capability, CapabilityRegistry


@pytest.fixture
def registry() -> CapabilityRegistry:
    r = CapabilityRegistry()
    r.register(
        Capability(
            agent="screener",
            family="research",
            summary="Runs saved scans across the universe.",
            task_types=("screen.sector", "screen.watchlist"),
        )
    )
    r.register(
        Capability(
            agent="idea-synthesizer",
            family="research",
            summary="Fuses research into ranked trade ideas.",
            task_types=("idea.synthesize",),
        )
    )
    r.register(
        Capability(
            agent="chart-markup",
            family="charting",
            summary="Levels and zones onto a chart.",
            task_types=("chart.markup",),
        )
    )
    return r


def make(tasks: list[dict], **extra) -> Plan:
    return Plan(tasks=[PlanTask(**t) for t in tasks], **extra)


# -- the worked example from Orchestrator Tools -------------------------------


def test_the_notes_worked_example_validates(registry: CapabilityRegistry) -> None:
    plan = make(
        [
            {"id": "t1", "type": "screen.sector", "agent": "screener",
             "args": {"sector": "semiconductors", "direction": "long"}},
            {"id": "t2", "type": "idea.synthesize", "agent": "idea-synthesizer",
             "depends_on": ["t1"]},
            {"id": "t3", "type": "chart.markup", "agent": "chart-markup",
             "depends_on": ["t2"], "args": {"timeframes": ["1D", "1H"]}},
        ],
        speak_after="t3",
    )
    validated = validate_plan(plan, registry)
    assert validated.ids == ("t1", "t2", "t3")
    assert validated.speak_after == "t3"


# -- structure ----------------------------------------------------------------


def test_a_cycle_is_rejected(registry: CapabilityRegistry) -> None:
    plan = make([
        {"id": "t1", "type": "screen.sector", "agent": "screener", "depends_on": ["t2"]},
        {"id": "t2", "type": "idea.synthesize", "agent": "idea-synthesizer", "depends_on": ["t1"]},
    ])
    with pytest.raises(PlanError, match="cycle"):
        validate_plan(plan, registry)


def test_a_dangling_dependency_is_rejected(registry: CapabilityRegistry) -> None:
    plan = make([
        {"id": "t1", "type": "idea.synthesize", "agent": "idea-synthesizer",
         "depends_on": ["t9"]},
    ])
    with pytest.raises(PlanError, match="not in the plan"):
        validate_plan(plan, registry)


def test_self_dependency_is_rejected(registry: CapabilityRegistry) -> None:
    plan = make([
        {"id": "t1", "type": "screen.sector", "agent": "screener", "depends_on": ["t1"]},
    ])
    with pytest.raises(PlanError, match="depends on itself"):
        validate_plan(plan, registry)


def test_duplicate_ids_are_rejected(registry: CapabilityRegistry) -> None:
    plan = make([
        {"id": "t1", "type": "screen.sector", "agent": "screener"},
        {"id": "t1", "type": "screen.watchlist", "agent": "screener"},
    ])
    with pytest.raises(PlanError, match="duplicate"):
        validate_plan(plan, registry)


def test_an_empty_plan_is_rejected(registry: CapabilityRegistry) -> None:
    with pytest.raises(PlanError, match="no tasks"):
        validate_plan(Plan(tasks=()), registry)


def test_too_many_tasks_is_rejected(registry: CapabilityRegistry) -> None:
    plan = make([
        {"id": f"t{i}", "type": "screen.sector", "agent": "screener"} for i in range(9)
    ])
    with pytest.raises(PlanError, match="over the limit"):
        validate_plan(plan, registry)


def test_topological_order_is_deterministic() -> None:
    tasks = tuple(
        PlanTask(id=i, type="screen.sector", agent="screener", depends_on=d)
        for i, d in [("t3", ("t1",)), ("t1", ()), ("t2", ("t1",))]
    )
    once = topological_order(tasks)
    again = topological_order(tasks)
    assert [t.id for t in once] == [t.id for t in again] == ["t1", "t3", "t2"]


def test_validation_returns_tasks_in_dependency_order(registry: CapabilityRegistry) -> None:
    # The dependent listed first: the bus needs the parent submitted first, so
    # validation has to reorder rather than trust the model's ordering.
    plan = make([
        {"id": "t2", "type": "idea.synthesize", "agent": "idea-synthesizer", "depends_on": ["t1"]},
        {"id": "t1", "type": "screen.sector", "agent": "screener"},
    ])
    assert validate_plan(plan, registry).ids == ("t1", "t2")


def test_speak_after_defaults_to_the_last_task_in_order(registry: CapabilityRegistry) -> None:
    plan = make([
        {"id": "t2", "type": "idea.synthesize", "agent": "idea-synthesizer", "depends_on": ["t1"]},
        {"id": "t1", "type": "screen.sector", "agent": "screener"},
    ])
    assert validate_plan(plan, registry).speak_after == "t2"


def test_speak_after_naming_an_absent_task_is_rejected(registry: CapabilityRegistry) -> None:
    plan = make(
        [{"id": "t1", "type": "screen.sector", "agent": "screener"}], speak_after="t7"
    )
    with pytest.raises(PlanError, match="speak_after"):
        validate_plan(plan, registry)


# -- the catalogue ------------------------------------------------------------


def test_an_invented_agent_is_rejected(registry: CapabilityRegistry) -> None:
    plan = make([{"id": "t1", "type": "screen.sector", "agent": "market-wizard"}])
    with pytest.raises(PlanError, match="no agent named"):
        validate_plan(plan, registry)


def test_a_task_type_the_agent_does_not_handle_is_rejected(registry: CapabilityRegistry) -> None:
    plan = make([{"id": "t1", "type": "chart.markup", "agent": "screener"}])
    with pytest.raises(PlanError, match="does not handle"):
        validate_plan(plan, registry)


def test_an_agent_with_no_declared_types_accepts_any_type(registry: CapabilityRegistry) -> None:
    registry.register(Capability(agent="scratch", family="core", summary="Anything."))
    plan = make([{"id": "t1", "type": "some.thing", "agent": "scratch"}])
    assert validate_plan(plan, registry).ids == ("t1",)


# -- the execution boundary ---------------------------------------------------


def test_the_registry_refuses_to_hold_an_execution_agent() -> None:
    r = CapabilityRegistry()
    with pytest.raises(ValueError, match="execution family"):
        r.register(
            Capability(agent="order-manager", family="execution", summary="Places orders.")
        )
    assert "order-manager" not in r


def test_validation_rejects_an_execution_agent_even_if_one_got_registered(
    registry: CapabilityRegistry,
) -> None:
    # Reaching past register() the way a bug would, to prove the second check
    # is a real independent refusal and not decoration.
    registry._by_agent["order-manager"] = Capability(
        agent="order-manager", family="execution", summary="Places orders."
    )
    plan = make([{"id": "t1", "type": "order.place", "agent": "order-manager"}])
    with pytest.raises(PlanError, match="execution family"):
        validate_plan(plan, registry)


def test_a_plan_cannot_name_a_lane() -> None:
    # There is no lane field, so a model asking for the execution lane produces
    # a validation error rather than a privileged task.
    with pytest.raises(PlanError, match="lane"):
        parse_plan({"tasks": [
            {"id": "t1", "type": "screen.sector", "agent": "screener", "lane": "execution"}
        ]})


# -- args are parameters, not payloads ----------------------------------------


def test_oversized_args_are_rejected() -> None:
    with pytest.raises(PlanError, match="args"):
        parse_plan({"tasks": [{
            "id": "t1", "type": "screen.sector", "agent": "screener",
            "args": {"rows": ["x" * 100 for _ in range(MAX_ARGS_CHARS // 50)]},
        }]})


def test_unserialisable_args_are_rejected() -> None:
    # Constructed directly rather than parsed, which is how a hand-built plan
    # would reach the validator. Pydantic's own error is correct here; only
    # parse_plan promises to wrap everything as PlanError.
    with pytest.raises(ValidationError, match="not JSON-serialisable"):
        PlanTask(id="t1", type="screen.sector", agent="screener", args={"f": object()})


# -- shapes -------------------------------------------------------------------


def test_a_non_object_response_is_rejected() -> None:
    with pytest.raises(PlanError, match="expected a JSON object"):
        parse_plan([{"id": "t1"}])


@pytest.mark.parametrize("bad", ["T1", "t-1", "", "a" * 30])
def test_malformed_task_ids_are_rejected(bad: str) -> None:
    with pytest.raises(PlanError):
        parse_plan({"tasks": [{"id": bad, "type": "screen.sector", "agent": "screener"}]})


@pytest.mark.parametrize("bad", ["screen", "Screen.Sector", "screen sector", ""])
def test_malformed_task_types_are_rejected(bad: str) -> None:
    with pytest.raises(PlanError):
        parse_plan({"tasks": [{"id": "t1", "type": bad, "agent": "screener"}]})
