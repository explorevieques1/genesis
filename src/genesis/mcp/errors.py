# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Typed failures the gateway raises.

Each one maps onto a class from :mod:`genesis.errors`, because the Task Bus
branches on that class and a gateway-specific hierarchy that did not would
silently opt out of the retry machinery.

The mapping is the design, not an implementation detail:

``MCPServerSessionError`` is **transient**
    A lost session is the ordinary failure of a long-lived connection. The
    runtime already spent its one silent reconnect before raising, so a retry
    above is a second chance at a genuinely flaky server, not a loop.
``ToolNotAllowedError`` is **fatal**
    An agent asking for a tool outside its allow-list is a bug or an attack,
    and neither improves on retry. Retrying would also turn a rejected call
    into a rate-limited hammer against the boundary that just held.
``ToolNotRegisteredError`` is **fatal**
    The catalogue is the world. A tool that is not in it does not exist, and no
    amount of waiting will register it.
"""

from __future__ import annotations

from genesis.errors import FatalError, TransientError

__all__ = [
    "MCPServerSessionError",
    "ToolNotAllowedError",
    "ToolNotRegisteredError",
]


class MCPServerSessionError(TransientError):
    """A server session was lost and did not come back on one reconnect.

    The gateway reconnects **once**, silently, because a single dropped socket
    is not news. The second failure is news, and it surfaces as this.
    """


class ToolNotAllowedError(FatalError):
    """An agent called a tool outside its allow-list.

    Raised *before* dispatch, which is the entire point: the News agent cannot
    reach the broker even if something persuaded it to try, because the check
    lives outside the model.
    """

    def __init__(self, agent: str, tool: str) -> None:
        super().__init__(
            f"agent {agent!r} may not call {tool!r} — not in its allow-list",
            spoken_summary="An agent asked for a tool it isn't allowed to use. I blocked it.",
        )
        self.agent = agent
        self.tool = tool


class ToolNotRegisteredError(FatalError):
    """No such tool in the catalogue."""

    def __init__(self, tool: str) -> None:
        super().__init__(f"tool {tool!r} is not registered in the gateway catalogue")
        self.tool = tool
