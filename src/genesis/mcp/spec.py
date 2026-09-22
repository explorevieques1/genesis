# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""One tool, as the gateway sees it.

The registry is a catalogue of these. Everything downstream -- allow-list
checks, the router, the fence, the cache -- reads fields off a :class:`ToolSpec`
rather than asking a server anything, so the catalogue is the single description
of what the system can do.

Three fields carry weight beyond bookkeeping:

``capability``
    *What this tool is for*, not what it is called. ``openbb.get_quote`` and
    ``market_data.quote`` are two implementations of ``market-data.quote``, and
    MCP Server Catalog.md is explicit that only one of them may be registered:
    three competing quote tools is a different failure from too many tools,
    because the router picks a defensible-but-wrong one and nothing notices.
``trust``
    Whether results are ``<untrusted>``-fenced before a model sees them. It is
    a property of the *source*, decided once here, rather than a judgement made
    at each call site where it could be forgotten.
``mutating``
    Whether the tool changes something in the world. Read paths and write paths
    are structurally different (Biological Design, afferent vs efferent), and
    the registry refuses to catalogue a mutating tool unless explicitly told to
    -- which is what keeps ``place_order`` out of the catalogue three phases
    before the risk engine exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "CachePolicy",
    "ToolSpec",
    "Trust",
    "split_tool_id",
]

#: Tool ids are ``server.tool``. Both halves are kebab/snake identifiers, and
#: the *first* dot is the separator -- server names never contain one, tool
#: names sometimes do.
_TOOL_ID = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*\.[A-Za-z0-9_.-]+$")


def split_tool_id(tool_id: str) -> tuple[str, str]:
    """``"alpaca.get_bars"`` -> ``("alpaca", "get_bars")``."""
    if not _TOOL_ID.match(tool_id):
        raise ValueError(
            f"tool id {tool_id!r} is not 'server.tool' with a kebab-case server"
        )
    server, _, name = tool_id.partition(".")
    return server, name


class Trust(str, Enum):
    """Where a result came from, and therefore how it must be handled.

    ``untrusted`` is not a judgement about a server's quality. Reuters is a fine
    newspaper; its text is still third-party text reaching a model, and the
    fence treats it as data either way.
    """

    #: Ours, or a deterministic local utility. Results reach a model as-is.
    TRUSTED = "trusted"
    #: Web, news, social, email, chat, issue trackers, any third-party server.
    #: Results are fenced before any model sees them (build plan step 4).
    UNTRUSTED = "untrusted"


@dataclass(frozen=True)
class CachePolicy:
    """When a result may be served from cache.

    Declared in step 1 and *enforced* in step 6 -- the field exists now so the
    catalogue is complete and servers can be described once, rather than
    revisited when the cache lands.

    ``bar_boundary`` is the interesting one. MCP Gateway.md: the cache is
    invalidated on bar close, never on a timer alone. A five-second TTL on a
    daily bar is both wasteful and wrong -- wasteful because the bar has not
    moved, wrong because at 16:00 it has, and no TTL knows that.
    """

    #: ``None`` means not cacheable at all.
    ttl_sec: float | None = None
    #: Invalidate when the relevant bar closes, regardless of remaining TTL.
    bar_boundary: bool = False

    @property
    def cacheable(self) -> bool:
        return self.ttl_sec is not None or self.bar_boundary


#: Nothing is cached until told otherwise. A wrong cache on market data is a
#: stale price presented as a live one, which is the failure mode that loses
#: money quietly.
NO_CACHE = CachePolicy()


@dataclass(frozen=True)
class ToolSpec:
    """One entry in the gateway catalogue."""

    #: ``server.tool``. Unique across the whole catalogue.
    id: str
    server: str
    name: str
    #: What this tool is *for*. The dedup key -- see the module docstring.
    capability: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    #: Words a person would use for this tool that neither its name nor its
    #: own description contains. Read by the router at capability weight.
    #:
    #: This is the maintenance surface of a deterministic router, and it is
    #: not an admission of defeat. A vendor writes "fetch an economic time
    #: series"; a person says "CPI". No lexical ranker bridges that, and no
    #: model-backed one should have to — the gap is a missing *fact about the
    #: catalogue*, and the catalogue is ours to state facts in. Recording it
    #: here costs one line and is testable; discovering it at runtime costs a
    #: model call on every selection, forever.
    keywords: tuple[str, ...] = ()
    trust: Trust = Trust.UNTRUSTED
    mutating: bool = True
    cache: CachePolicy = NO_CACHE
    #: How long this one tool may take. Per-tool rather than per-server
    #: because a server can host both a quote lookup and a deep-research agent
    #: that runs for minutes, and a single number would be either a hair
    #: trigger on one or no protection at all on the other.
    timeout_sec: float = 30.0
    #: Source trust tier from Market Data Sources.md; lower wins a capability
    #: contest. Tier 1 is the venue's own book, and is the only thing the
    #: Pre-Trade Risk Engine may ever read.
    tier: int = 9

    def __post_init__(self) -> None:
        server, name = split_tool_id(self.id)
        if server != self.server or name != self.name:
            raise ValueError(
                f"tool id {self.id!r} disagrees with server={self.server!r} "
                f"name={self.name!r}"
            )
        if not self.capability:
            raise ValueError(f"tool {self.id!r} has no capability")

    # Defaults are the unsafe-to-forget direction on purpose: a tool nobody
    # described is untrusted, mutating, uncacheable and bottom-tier. Every one
    # of those defaults costs performance or reach, never safety, so the
    # failure mode of an under-described server is a tool that does less than
    # it could -- not one that does more than it should.

    @property
    def read_only(self) -> bool:
        return not self.mutating

    def catalogue_line(self) -> str:
        """One line for a human reading the registered surface."""
        flags = "rw" if self.mutating else "ro"
        return f"{self.id} [{self.capability} · {flags} · {self.trust.value} · t{self.tier}]"
