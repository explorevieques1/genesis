# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Which agent may call what. Deny by default, checked before dispatch.

MCP Gateway.md: *"Every agent declares its tools (Agent Contract). The gateway
enforces it -- a tool call outside the allow-list is rejected before it reaches
a server. This is structural, not advisory."* The value of that sentence is
entirely in *where* the check runs. An instruction in a prompt can be argued
with; a rejection in :meth:`AllowList.permits` cannot, and the agent that
ingests the most untrusted text in the system stays the furthest from the money
whatever that text says.

Entries are **capability patterns, never server or tool names.**
-------------------------------------------------------------------
Agent Contract.md declares tools as ``market-data.ohlcv``,
``genesis-charting.render``, ``obsidian.write``; MCP Gateway.md writes whole
grants as ``genesis-execution.*``. Read as capabilities, those are one syntax
with one meaning. Read as a mixture of capabilities and server names they are
two, and the ambiguity resolves in the dangerous direction -- ``market-data.*``
would grant either "anything about market data" or "everything on the server
called market-data", and those are not the same set.

So: one rule. An entry names a capability, optionally ending in ``.*`` to take
a whole namespace. The gateway resolves a call to its :class:`ToolSpec`, takes
that spec's capability, and matches. Which server ends up serving it is the
registry's business (see MCP Server Catalog.md §overlap), and an allow-list that
named servers would quietly change meaning every time a capability contest was
re-decided.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from genesis.mcp.errors import ToolNotAllowedError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from genesis.mcp.registry import ToolRegistry

__all__ = ["AllowList", "matches"]


def matches(pattern: str, capability: str) -> bool:
    """Does one allow-list entry grant one capability?

    Exact, or a ``prefix.*`` namespace grant. There is no ``*`` on its own and
    no interior wildcard: a bare ``*`` is a grant nobody can audit at a glance,
    and every real case is either one capability or one namespace.
    """
    if pattern.endswith(".*"):
        return capability.startswith(pattern[:-1])
    return pattern == capability


@dataclass(frozen=True)
class AllowList:
    """One agent's grants.

    Frozen, because an allow-list that could be widened at runtime is not a
    boundary. Tightening is expressed by building a new one -- the same
    direction-of-travel rule the orchestrator's ``tighten_autonomy`` enforces.
    """

    agent: str
    patterns: tuple[str, ...] = ()

    def permits(self, capability: str) -> bool:
        return any(matches(p, capability) for p in self.patterns)

    def check(self, capability: str, tool_id: str) -> None:
        """Raise unless permitted. The gateway calls this before dispatch.

        The error names the *tool id* rather than the capability, because the
        person reading the log wants to know what was actually reached for.
        """
        if not self.permits(capability):
            raise ToolNotAllowedError(self.agent, tool_id)

    def granted(self, registry: ToolRegistry) -> tuple[str, ...]:
        """Every registered tool id this allow-list actually opens.

        The honest answer to "what can this agent do?", which is a different
        question from what its declaration says -- a pattern grants nothing if
        no server ever registered a tool for it.
        """
        return tuple(
            sorted(spec.id for spec in registry if self.permits(spec.capability))
        )

    def unmatched(self, registry: ToolRegistry) -> tuple[str, ...]:
        """Patterns that match nothing registered.

        Almost always a typo or a capability renamed on one side only. Not an
        error -- a server may legitimately be disabled today -- but a thing to
        say out loud at start-up, because the failure it produces otherwise is
        an agent that mysteriously cannot do one of its jobs.
        """
        caps = [spec.capability for spec in registry]
        return tuple(
            p for p in self.patterns if not any(matches(p, c) for c in caps)
        )

    @classmethod
    def of(cls, agent: str, patterns: Iterable[str]) -> AllowList:
        return cls(agent=agent, patterns=tuple(patterns))
