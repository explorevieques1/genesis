# Spec: Genesis Markdown/10-Architecture/Orchestrator.md
"""What the planner is allowed to know about the fleet.

Orchestrator.md: *"The orchestrator picks the agent, not the tool. Agents pick
their own tools through the MCP Gateway. This keeps the orchestrator's context
small no matter how many tools exist."*

This registry is the whole of the planner's world model -- one line per agent,
built from the agent's own :class:`~genesis.agents.base.AgentDeclaration` so it
cannot drift from what is actually running. Nothing here describes a *tool*. If
this file ever grows tool schemas, the orchestrator's latency criterion is gone
and the [[MCP Gateway]] is being bypassed.

**Execution agents are not registrable.** :meth:`CapabilityRegistry.register`
raises on the execution family, which means the catalogue handed to the model
never mentions the risk engine, the order manager, the broker adapter or the
kill switch. A model cannot plan a task for an agent it has never heard of, and
this is a stronger guarantee than telling it not to. Voice reaches execution
through [[Approval Modes]] and the [[Pre-Trade Risk Engine]], never through a
planned task.

An **empty registry is the honest Phase 3 state**: no read-only agents exist
yet, so there is nothing to plan for, and the planner says so by declining
instead of inventing an agent name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from genesis.agents.base import AgentDeclaration

__all__ = ["Capability", "CapabilityRegistry"]

#: Keeps one catalogue line honest-sized. The planner prompt is on the voice
#: latency path, and a paragraph per agent across thirty agents is a prompt
#: nobody budgeted for.
MAX_SUMMARY_CHARS = 160


@dataclass(frozen=True)
class Capability:
    """One agent, as the planner sees it."""

    agent: str
    family: str
    summary: str
    #: The task types this agent accepts. Empty means "not yet declared", and
    #: :func:`~genesis.orchestrator.plan.validate_plan` then skips the type
    #: check rather than rejecting everything -- an under-specified agent
    #: should be unhelpful, not a hard failure.
    task_types: tuple[str, ...] = ()
    args_hint: str = ""

    def catalogue_line(self) -> str:
        types = " | ".join(self.task_types) if self.task_types else "(no declared types)"
        line = f"- {self.agent}: {self.summary}\n  types: {types}"
        if self.args_hint:
            line += f"\n  args: {self.args_hint}"
        return line


@dataclass
class CapabilityRegistry:
    """The planner's agent catalogue.

    Falsy when empty, so the planner's first check reads as
    ``if not self.registry: decline`` -- and declines without paying for a
    model call that could only hallucinate.
    """

    _by_agent: dict[str, Capability] = field(default_factory=dict)

    def register(self, capability: Capability) -> None:
        if capability.family == "execution":
            raise ValueError(
                f"agent {capability.agent!r} is in the execution family and may not "
                f"appear in the planner's catalogue — see Safety Invariants §1"
            )
        if len(capability.summary) > MAX_SUMMARY_CHARS:
            raise ValueError(
                f"summary for {capability.agent!r} is {len(capability.summary)} chars, "
                f"over the {MAX_SUMMARY_CHARS} limit"
            )
        self._by_agent[capability.agent] = capability

    def register_declaration(
        self,
        declaration: AgentDeclaration,
        *,
        summary: str,
        task_types: tuple[str, ...] = (),
        args_hint: str = "",
    ) -> None:
        """Register from the agent's own declaration.

        Family and id come from the declaration rather than the caller, so a
        registration cannot claim a family the agent does not have -- which is
        what would otherwise let an execution agent in through a typo.
        """
        self.register(
            Capability(
                agent=declaration.id,
                family=declaration.family,
                summary=summary,
                task_types=task_types,
                args_hint=args_hint,
            )
        )

    def get(self, agent: str) -> Capability | None:
        return self._by_agent.get(agent)

    @property
    def agents(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_agent))

    def catalogue(self) -> str:
        """The agent list as the planner prompt renders it."""
        return "\n".join(
            self._by_agent[a].catalogue_line() for a in self.agents
        )

    def __len__(self) -> int:
        return len(self._by_agent)

    def __bool__(self) -> bool:
        return bool(self._by_agent)

    def __contains__(self, agent: object) -> bool:
        return agent in self._by_agent
