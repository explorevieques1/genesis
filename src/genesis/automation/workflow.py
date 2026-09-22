# Spec: Genesis Markdown/70-Schemas/Workflow Schema.md
"""A workflow body, validated, and its compilation to an agent declaration.

There is exactly one scheduler. A workflow does not get a run loop of its own:
:func:`compile_declaration` turns it into an :class:`AgentDeclaration` whose
cadence is the workflow's trigger, and the daemon registers it like any agent.

Wiring is a chain. Every step has at most one ``next``; a ``check`` or a
pass/fail node (an action with ``branches``) also has an ``on_fail``. No step is the target of two edges and nothing loops, so the
runtime walks a path rather than scheduling a graph. The canvas draws the same
rules; this module is where they are true.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from genesis.agents.base import AgentDeclaration, Cadence
from genesis.automation.grant import WORKFLOW_GRANT, permits

__all__ = ["TRIGGER_INPUT", "Step", "Workflow", "agent_id_for", "compile_declaration"]

_ID = r"^[a-z0-9]+(-[a-z0-9]+)*$"

#: The reserved input name for the data a run started with: the event that
#: fired it, or the caller's data when the workflow runs as a process.
TRIGGER_INPUT = "trigger"

REFRESH_TARGETS = ("vault-map", "corpus-index")
PREDICATES = ("non_empty", "min_count", "compare")
OPS = (">", "<", ">=", "<=")


class Step(BaseModel):
    """One node. Which fields apply depends on ``kind``; the rest must be unset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=_ID)
    kind: Literal["gather", "check", "refresh", "run", "action"]
    next: str | None = None
    on_fail: str | None = None
    input: str | None = None
    # gather
    capability: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    # check
    predicate: Literal["non_empty", "min_count", "compare"] | None = None
    field: str | None = None
    op: Literal[">", "<", ">=", "<="] | None = None
    value: float | None = None
    # refresh
    target: Literal["vault-map", "corpus-index"] | None = None
    # run
    agent: str | None = None
    # action — a built-in node from `genesis.automation.actions`
    action: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    #: Repeat once per item of `input` -- an action fills its symbol setting,
    #: a gather fills the tool argument named by `each_arg`.
    each: bool = False
    each_arg: str | None = None

    def model_post_init(self, _: Any) -> None:
        need = {
            "gather": ("capability",),
            "check": ("input", "predicate"),
            "refresh": ("target",),
            "run": ("agent",),
            "action": ("action",),
        }[self.kind]
        missing = [name for name in need if getattr(self, name) is None]
        if missing:
            raise ValueError(f"step {self.id!r} ({self.kind}) needs {', '.join(missing)}")
        if self.kind == "action":
            from genesis.automation.actions import ACTIONS, validate_params

            action = ACTIONS.get(self.action or "")
            if action is None:
                raise ValueError(f"step {self.id!r}: unknown action {self.action!r}")
            validate_params(action, self.params, each=self.each)
            if self.each and not action.each:
                raise ValueError(f"step {self.id!r}: {action.label} cannot repeat for each item")
            if (self.each or action.needs_input) and self.input is None:
                raise ValueError(f"step {self.id!r}: {action.label} needs an input step")
        if self.on_fail is not None and not self.branches:
            raise ValueError(f"step {self.id!r}: only a check or a pass/fail node has a fail branch")
        if self.each and self.kind == "gather" and (not self.each_arg or self.input is None):
            raise ValueError(f"step {self.id!r}: repeat for each needs an input and the argument to fill")
        if self.each and self.kind not in ("gather", "action"):
            raise ValueError(f"step {self.id!r}: only tool and built-in nodes repeat for each item")
        if self.kind == "gather" and not permits(self.capability or ""):
            raise ValueError(
                f"step {self.id!r}: {self.capability!r} is outside the workflow grant"
            )
        if self.predicate == "min_count" and self.value is None:
            raise ValueError(f"step {self.id!r}: min_count needs value")
        if self.predicate == "compare" and None in (self.field, self.op, self.value):
            raise ValueError(f"step {self.id!r}: compare needs field, op and value")

    @property
    def branches(self) -> bool:
        if self.kind == "check":
            return True
        if self.kind == "action":
            from genesis.automation.actions import ACTIONS

            action = ACTIONS.get(self.action or "")
            return bool(action and action.branches)
        return False


class Workflow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=_ID)
    name: str = Field(min_length=1)
    trigger: Cadence
    start: str | None = None
    steps: tuple[Step, ...] = Field(default=(), max_length=40)
    #: Positions, notes and groups for the canvas. Never read by the runtime.
    layout: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, _: Any) -> None:
        by_id = {s.id: s for s in self.steps}
        if len(by_id) != len(self.steps):
            raise ValueError("step ids must be unique")
        if TRIGGER_INPUT in by_id:
            raise ValueError(f"{TRIGGER_INPUT!r} is reserved and cannot be a step id")
        if self.start is not None and self.start not in by_id:
            raise ValueError(f"start points at unknown step {self.start!r}")

        parent: dict[str, str] = {}
        for step in self.steps:
            for edge in (step.next, step.on_fail):
                if edge is None:
                    continue
                if edge not in by_id:
                    raise ValueError(f"step {step.id!r} points at unknown step {edge!r}")
                if edge == self.start or edge in parent:
                    raise ValueError(
                        f"step {edge!r} has two incoming edges — a step has one "
                        "previous step; use a check for a branch"
                    )
                parent[edge] = step.id

        for step in self.steps:
            # One parent each, so a step's ancestors are a single chain. Walking
            # it both refuses a cycle and says what an `input` may refer to.
            ancestors: list[str] = []
            at = step.id
            while at in parent:
                at = parent[at]
                if at == step.id or at in ancestors:
                    raise ValueError(f"step {step.id!r} is in a loop")
                ancestors.append(at)
            if step.input not in (None, TRIGGER_INPUT) and step.input not in ancestors:
                raise ValueError(
                    f"step {step.id!r}: input {step.input!r} is not an earlier step on its path"
                )

    def step(self, step_id: str) -> Step:
        return next(s for s in self.steps if s.id == step_id)


def _tools(workflow: Workflow) -> tuple[str, ...]:
    """What the gateway binds for this workflow.

    Its own gather capabilities -- least privilege. A workflow that runs a
    process gets the whole read grant instead, because the process may be
    edited after this one is saved and its steps run under this agent's id.
    Still inside the fence either way.
    """
    if any(s.kind == "action" and s.action == "flow.process" for s in workflow.steps):
        return WORKFLOW_GRANT
    return tuple(sorted({s.capability for s in workflow.steps if s.capability}))


_TIER_ORDER = ("none", "nano", "small", "large")


def _tier(workflow: Workflow) -> str:
    """The highest model tier any node runs. A workflow with a judgement node is not a reflex."""
    from genesis.automation.actions import ACTIONS

    tiers = [ACTIONS[s.action].model_tier for s in workflow.steps if s.kind == "action" and s.action in ACTIONS]
    return max(tiers, key=_TIER_ORDER.index, default="none")


def agent_id_for(workflow_id: str) -> str:
    return f"wf-{workflow_id}"


def compile_declaration(workflow: Workflow) -> AgentDeclaration:
    """The workflow as an agent the one scheduler already knows how to run."""
    return AgentDeclaration(
        id=agent_id_for(workflow.id),
        name=workflow.name,
        family="core",
        cadence=(workflow.trigger,),
        tools=_tools(workflow),
        memory={"read": ["shared"], "write": []},
        model_tier=_tier(workflow),
        timeout_sec=900 if _tier(workflow) != "none" else 300,
    )
