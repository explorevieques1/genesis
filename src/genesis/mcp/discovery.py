# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Turning what a server says it has into what we are willing to catalogue.

Kept apart from both the registry and the runtime on purpose. Normalisation is
pure -- a server's tool list plus our config in, :class:`ToolSpec` objects out --
so the rules that decide whether ``place_order`` reaches the catalogue are
testable without spawning a process or opening a socket. A safety boundary that
can only be exercised against a live server is a safety boundary nobody
exercises.

:class:`DiscoveredTool` is the seam. The runtime converts the SDK's types into
it, and nothing downstream of here imports the MCP SDK.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from genesis.mcp.servers import ServerConfig, ToolConfig
from genesis.mcp.spec import NO_CACHE, ToolSpec, Trust

__all__ = ["DiscoveredTool", "normalize"]

#: Verbs that are never a read, whatever anyone claims.
#:
#: ``read_only: true`` on a server is an operator's assertion, and it buys bulk
#: registration -- worth having, because most utility servers ship no
#: annotations at all and naming forty tools by hand is how a catalogue stops
#: being maintained. The assertion is about the server as it was *when it was
#: written*, though, and servers gain tools. This is the tripwire for the case
#: where one gains a dangerous one: a tool whose name contains one of these is
#: refused even under a read-only claim, and the refusal is recorded.
#:
#: It is a reflex, not a proof -- deterministic, sub-millisecond, and incapable
#: of being talked out of firing, but only as good as its list. The actual
#: guarantee for anything that can write is the explicit allow-list path
#: (``read_only: false`` obliges naming every tool). This is the cheap second
#: layer for the case where somebody's claim was simply wrong.
_MUTATING_VERBS = frozenset(
    {
        "order",
        "buy",
        "sell",
        "trade",
        "execute",
        "cancel",
        "liquidate",
        "withdraw",
        "transfer",
        "wire",
        "deposit",
        "delete",
        "destroy",
        "drop",
    }
)


def _tripped(name: str) -> str | None:
    """The verb that fired, if any. Word-boundary matched, not substring.

    Substring matching would refuse ``get_borderline`` for containing "order",
    and a tripwire that fires on innocent names is one somebody switches off.
    """
    parts = set(re.split(r"[^a-z0-9]+", name.lower()))
    hit = parts & _MUTATING_VERBS
    return sorted(hit)[0] if hit else None


@dataclass(frozen=True)
class DiscoveredTool:
    """One tool as its server described it, before we form an opinion."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    #: The server's ``annotations.readOnlyHint``. ``None`` means it did not say,
    #: which we read as "assume it writes" -- see :func:`normalize`.
    read_only_hint: bool | None = None


def normalize(
    config: ServerConfig, discovered: list[DiscoveredTool]
) -> list[ToolSpec]:
    """Apply our config to a server's own account of itself.

    Precedence is always *ours over theirs*. A server is authoritative about the
    shape of its arguments and nothing else: it does not get to declare itself
    trusted, nor to tell us how long its answers stay true. Those are claims
    about the world, and a compromised or merely optimistic server making them
    is exactly the failure the gateway exists to contain.

    Where neither we nor the server said, the default is the unsafe-to-forget
    direction: untrusted, mutating, uncacheable. An under-described server ends
    up able to do less than it could, never more than it should.
    """
    specs: list[ToolSpec] = []
    for tool in discovered:
        tripped = _tripped(tool.name)
        override = config.tools.get(tool.name)
        if override is None and config.explicit_only:
            # Not named, and this server can write. Silence is a refusal.
            continue
        override = override or ToolConfig()

        # The tripwire outranks a blanket read-only claim, but not a per-tool
        # declaration: an operator who names `mutating: true` for the thing has
        # already looked at it, and Phase 7 must be able to catalogue
        # `propose_order` on purpose.
        if tripped and override.mutating is None and config.read_only:
            continue

        specs.append(
            ToolSpec(
                id=f"{config.id}.{tool.name}",
                server=config.id,
                name=tool.name,
                capability=_capability(override, config, tool),
                description=tool.description,
                input_schema=tool.input_schema,
                # Server-level first, then the tool's own. Both apply: a FRED
                # tool is about macro *and* about whatever it does.
                keywords=tuple(dict.fromkeys(config.keywords + override.keywords)),
                trust=override.trust or config.trust,
                mutating=_mutating(override, config, tool),
                cache=override.cache.to_policy() if override.cache else NO_CACHE,
                tier=override.tier if override.tier is not None else config.tier,
                timeout_sec=(
                    override.timeout_sec
                    if override.timeout_sec is not None
                    else config.call_timeout_sec
                ),
            )
        )
    return specs


def _capability(
    override: ToolConfig, config: ServerConfig, tool: DiscoveredTool
) -> str:
    """What this tool is *for*, in the one vocabulary allow-lists speak.

    Three sources, and the fallback is the interesting one. A bare tool name is
    a legal capability and a useless one: allow-list entries are exact or
    ``prefix.*``, so ``get_company_facts`` can only ever be granted by naming
    it, one tool at a time, forever. ``capability_prefix`` is how a server that
    we bulk-register still lands inside a namespace somebody can grant, deny,
    and route on.
    """
    if override.capability:
        return override.capability
    if config.capability_prefix:
        return f"{config.capability_prefix}.{tool.name}"
    return tool.name


def _mutating(
    override: ToolConfig, config: ServerConfig, tool: DiscoveredTool
) -> bool:
    """Three sources, in descending order of how much we believe them.

    Our explicit declaration wins. Then our claim that the whole server is
    read-only. Only then the server's own hint -- and an *absent* hint is not
    evidence of anything, so it reads as mutating.
    """
    if override.mutating is not None:
        return override.mutating
    if config.read_only:
        return False
    return tool.read_only_hint is not True
