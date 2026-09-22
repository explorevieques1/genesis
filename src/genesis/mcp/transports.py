# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Opening a real session to a real server. The only file that imports the SDK.

Everything else in this package works against
:class:`~genesis.mcp.runtime.SessionLike`, so the registry, the allow-list, the
discovery rules and the runtime's reconnect behaviour are all testable without
the MCP SDK installed and without spawning a process. That is not tidiness: the
rules being tested here are the ones that keep ``place_order`` out of the
catalogue, and they must be exercised on every test run, not only on a machine
where ``uvx`` works.

The SDK import is therefore *inside* the factory. That is about testability
rather than about the dependency being optional -- it is a core dependency,
because from Phase 3 onward every agent reaches the world through here.
"""

from __future__ import annotations

from contextlib import AsyncExitStack

from genesis.mcp.runtime import SessionFactory, SessionLike
from genesis.mcp.servers import ServerConfig

__all__ = ["factory_for"]


def factory_for(config: ServerConfig) -> SessionFactory:
    """A callable that opens one initialized session for this server."""

    async def _open(stack: AsyncExitStack) -> SessionLike:
        from mcp import ClientSession

        if config.transport == "stdio":
            from mcp import StdioServerParameters
            from mcp.client.stdio import get_default_environment, stdio_client

            params = StdioServerParameters(
                command=config.command or "",
                args=config.expanded_args,
                # The SDK's default environment is a deliberately short
                # inherited allow-list. Merging our named keys onto it, rather
                # than passing os.environ, means a server process sees the two
                # secrets it was promised and nothing else in the environment.
                env={**get_default_environment(), **config.child_env()},
            )
            streams = await stack.enter_async_context(stdio_client(params))
        else:
            from mcp.client.streamable_http import (
                create_mcp_http_client,
                streamable_http_client,
            )

            # Headers are resolved here rather than at load time so a rotated
            # key takes effect on the next reconnect, not the next restart.
            http_client = create_mcp_http_client(headers=config.resolved_headers())
            await stack.enter_async_context(http_client)
            streams = await stack.enter_async_context(
                streamable_http_client(config.url or "", http_client=http_client)
            )

        read, write = streams[0], streams[1]
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    return _open
