# Spec: Genesis Markdown/10-Architecture/Orchestrator.md
"""The plan: what the planner emits, and what it is not allowed to emit.

Orchestrator.md's planning section gives the shape -- an ordered task list with
owners, explicit ``depends_on``, and a ``speak_after``. This module is that
shape plus the validation that stands between a language model's JSON and the
:mod:`genesis.bus`.

That validation is the load-bearing part, and it is worth being explicit about
why it is structural rather than a prompt instruction. The planner is an LLM
reading an utterance that may itself be quoting something adversarial. Under
Biological Design the fix is not a better instruction, because *a reflex cannot
be talked out of firing by a persuasive prompt*. So the constraints live here,
in deterministic code the model does not run:

**A plan cannot name an execution agent.** :class:`~genesis.orchestrator.registry.CapabilityRegistry`
refuses to hold one, so an execution agent is not in the catalogue the model
sees; and :func:`validate_plan` rejects the family again by name even if one
somehow were. Two independent refusals, because this is the boundary Safety
Invariants §1 draws.

**A plan cannot choose a lane.** Lane is assigned by
:meth:`~genesis.orchestrator.tools.OrchestratorTools.dispatch`, always
``Lane.USER``. There is no field here to put ``execution`` in. Priority is not
a thing the model gets an opinion about.

**A plan cannot be a cycle, a dangling reference, or unbounded.** The bus would
deadlock on the first, cancel on the second, and drown on the third.

Every rejection raises :class:`PlanError` with the reason in plain words,
because the caller's job on a rejection is to fail open -- hand the utterance
to the large tier -- and the reason is what makes that decision auditable
rather than mysterious.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

__all__ = [
    "MAX_ARGS_CHARS",
    "MAX_TASKS",
    "Plan",
    "PlanError",
    "PlanTask",
    "topological_order",
    "validate_plan",
]

#: A voice request that decomposes into more than this is not a voice request.
#: The cap is a backstop against a model that answers a vague utterance with a
#: forty-step research programme the operator never asked for.
MAX_TASKS = 8

#: Args are parameters, not payloads. Anything larger is a model trying to pass
#: data through the orchestrator, which is exactly what Orchestrator Tools
#: forbids: *"The orchestrator moves ids and summaries. Never rows."*
MAX_ARGS_CHARS = 2_000

_ID = r"^[a-z][a-z0-9_]{0,23}$"
#: ``screen.sector``, ``idea.synthesize`` -- a namespaced verb, per Conventions.
_TYPE = r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9_]*)+$"
_AGENT = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class PlanError(ValueError):
    """A plan that must not be dispatched, and why.

    Always caught by the planner and turned into a fail-open answer. It reaches
    the operator as a spoken sentence, never as a traceback.
    """


class PlanTask(BaseModel):
    """One task in a plan, in the note's task shape.

    ``extra="forbid"`` is doing real work: this object is built from model
    output, and a hallucinated ``lane: execution`` or ``priority: 0`` key must
    be a loud rejection rather than a silently ignored field.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=_ID)
    type: str = Field(pattern=_TYPE)
    agent: str = Field(pattern=_AGENT)
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: tuple[str, ...] = ()

    @field_validator("depends_on", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    @field_validator("args")
    @classmethod
    def _bounded_and_serialisable(cls, v: dict[str, Any]) -> dict[str, Any]:
        # Serialisability is checked here rather than at submit time because the
        # bus stores args as JSON, and a value that cannot round-trip would fail
        # inside a transaction rather than at the boundary where it can be
        # explained.
        try:
            encoded = json.dumps(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"args are not JSON-serialisable: {exc}") from exc
        if len(encoded) > MAX_ARGS_CHARS:
            raise ValueError(
                f"args are {len(encoded)} chars, over the {MAX_ARGS_CHARS} limit — "
                f"pass a reference, not a payload"
            )
        return v


class Plan(BaseModel):
    """An ordered task list with owners. The planner's whole output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    utterance: str = ""
    tasks: tuple[PlanTask, ...]
    #: Which task's ``spoken_summary`` gets said out loud. Defaults to the last
    #: task in topological order, which is the sink the operator asked for.
    speak_after: str | None = None
    verbosity: Literal["terse", "brief", "full"] = "brief"

    @field_validator("tasks", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(t.id for t in self.tasks)

    def task(self, task_id: str) -> PlanTask | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def topological_order(tasks: tuple[PlanTask, ...]) -> tuple[PlanTask, ...]:
    """Dependency order, deterministic, or raise on a cycle.

    Deterministic matters: the same plan must submit in the same order every
    time, or a retry produces a different set of bus ids and the Episodic Log
    stops being comparable across runs. Ties break on the plan's own ordering,
    so ``t1, t2, t3`` stays ``t1, t2, t3``.
    """
    position = {t.id: i for i, t in enumerate(tasks)}
    remaining = {t.id: set(t.depends_on) for t in tasks}
    ordered: list[PlanTask] = []
    by_id = {t.id: t for t in tasks}

    while remaining:
        ready = sorted(
            (tid for tid, deps in remaining.items() if not deps),
            key=lambda tid: position[tid],
        )
        if not ready:
            stuck = ", ".join(sorted(remaining))
            raise PlanError(f"the plan has a dependency cycle among: {stuck}")
        for tid in ready:
            ordered.append(by_id[tid])
            del remaining[tid]
        for deps in remaining.values():
            deps.difference_update(ready)
    return tuple(ordered)


def parse_plan(data: Any, *, utterance: str = "") -> Plan:
    """Build a :class:`Plan` from decoded JSON, or raise :class:`PlanError`.

    Pydantic's own error is wrapped rather than propagated so that every
    rejection from this module is one exception type -- the planner's fail-open
    branch catches exactly one thing, which is how it stays impossible to leak
    a validation error onto the voice path.
    """
    if not isinstance(data, dict):
        raise PlanError(f"expected a JSON object, got {type(data).__name__}")
    payload = dict(data)
    payload.setdefault("utterance", utterance)
    try:
        return Plan.model_validate(payload)
    except ValidationError as exc:
        raise PlanError(_first_error(exc)) from exc


def validate_plan(plan: Plan, registry: Any = None, *, max_tasks: int = MAX_TASKS) -> Plan:
    """Return the plan, in dependency order, or raise :class:`PlanError`.

    ``registry`` is a :class:`~genesis.orchestrator.registry.CapabilityRegistry`
    or ``None``. With one, every agent and task type must be in it -- an
    invented agent is the single most common planner failure, and dispatching
    it would produce a task that fails at claim time with nothing useful to say.
    """
    if not plan.tasks:
        raise PlanError("the plan has no tasks")
    if len(plan.tasks) > max_tasks:
        raise PlanError(
            f"the plan has {len(plan.tasks)} tasks, over the limit of {max_tasks}"
        )

    ids = [t.id for t in plan.tasks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise PlanError(f"duplicate task id(s): {', '.join(sorted(duplicates))}")

    known = set(ids)
    for task in plan.tasks:
        if task.id in task.depends_on:
            raise PlanError(f"task {task.id!r} depends on itself")
        for dep in task.depends_on:
            if dep not in known:
                raise PlanError(
                    f"task {task.id!r} depends on {dep!r}, which is not in the plan"
                )

    ordered = topological_order(plan.tasks)

    if registry is not None:
        for task in plan.tasks:
            capability = registry.get(task.agent)
            if capability is None:
                raise PlanError(
                    f"no agent named {task.agent!r} — known agents: "
                    f"{', '.join(registry.agents) or 'none'}"
                )
            # Belt and braces. The registry already refuses to hold an
            # execution agent, so reaching this line means something upstream
            # is wrong -- which is precisely when a second check earns its keep.
            if capability.family == "execution":
                raise PlanError(
                    f"agent {task.agent!r} is in the execution family; a planned "
                    f"task may never reach it (Safety Invariants §1)"
                )
            if capability.task_types and task.type not in capability.task_types:
                raise PlanError(
                    f"agent {task.agent!r} does not handle {task.type!r} — it handles: "
                    f"{', '.join(capability.task_types)}"
                )

    speak_after = plan.speak_after or ordered[-1].id
    if speak_after not in known:
        raise PlanError(
            f"speak_after names {speak_after!r}, which is not a task in the plan"
        )

    return plan.model_copy(update={"tasks": ordered, "speak_after": speak_after})


def _first_error(exc: ValidationError) -> str:
    """Pydantic's first complaint, as a sentence rather than a dump."""
    errors = exc.errors()
    if not errors:
        return "the plan did not validate"
    first = errors[0]
    where = ".".join(str(p) for p in first.get("loc", ())) or "plan"
    return f"{where}: {first.get('msg', 'invalid')}"
