# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""The one chokepoint between every agent and every tool.

Nothing in Genesis calls an MCP server directly. An agent asks the gateway, and
the gateway decides whether the call is allowed, which session it goes down,
and how the result is wrapped before a model may look at it.

Build order for this package is `30-MCP/MCP Gateway Build Plan.md`. Steps 1-3
(registry, allow-list enforcement, persistent runtime) are here. The fence
(step 4), the router (step 5) and the cache (step 6) are not yet built, and the
call path in :mod:`genesis.mcp.gateway` names the seams where they land.

.. note::
   ``genesis.mcp`` and the upstream ``mcp`` SDK are different packages. Imports
   here are absolute, so ``import mcp`` inside this package still reaches the
   SDK -- but read twice before adding a relative import.
"""

from genesis.mcp.errors import (
    MCPServerSessionError,
    ToolNotAllowedError,
    ToolNotRegisteredError,
)
from genesis.mcp.registry import ToolRegistry
from genesis.mcp.spec import CachePolicy, ToolSpec, Trust

__all__ = [
    "CachePolicy",
    "MCPServerSessionError",
    "ToolNotAllowedError",
    "ToolNotRegisteredError",
    "ToolRegistry",
    "ToolSpec",
    "Trust",
]
