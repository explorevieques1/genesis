# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""A programmable MCP session.

The runtime's interesting behaviour is all failure behaviour -- one silent
reconnect, a typed error on the second, no reconnect on a slow tool or a bad
argument. None of that is reproducible on request against a real server, so the
runtime is written against a protocol and tested against this.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any


class _ErrorData:
    """The shape an SDK error carries: a numeric JSON-RPC code."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message


class FakeProtocolError(Exception):
    """A live server rejecting a call — shaped like the SDK's McpError."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.error = _ErrorData(-32602, message)


@dataclass
class FakeResult:
    content: Any = "ok"
    isError: bool = False  # noqa: N815 - the SDK's spelling
    structuredContent: dict[str, Any] | None = None  # noqa: N815


@dataclass
class FakeTools:
    tools: list[Any] = field(default_factory=list)


class FakeSession:
    """One session. Fails exactly as instructed, and records what happened."""

    def __init__(self, server: FakeServer) -> None:
        self._server = server
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        s = self._server
        self.calls.append((name, arguments))
        s.calls.append(name)

        s.concurrent += 1
        s.max_concurrent = max(s.max_concurrent, s.concurrent)
        try:
            if s.drop_next:
                s.drop_next -= 1
                raise ConnectionResetError("transport went away")
            if s.protocol_error_next:
                s.protocol_error_next -= 1
                raise FakeProtocolError("Invalid arguments for tool")
            if s.error_next:
                s.error_next -= 1
                return FakeResult(content="boom", isError=True)
            await asyncio.sleep(s.latency_sec)
            return FakeResult(content=s.reply if s.reply is not None else f"{name}:ok")
        finally:
            s.concurrent -= 1

    async def list_tools(self) -> Any:
        return FakeTools(tools=list(self._server.tools))

    async def send_ping(self) -> Any:
        if self._server.ping_fails:
            raise ConnectionResetError("no pong")
        return {}


@dataclass
class FakeServer:
    """The programmable bit. One per test."""

    #: Raise a transport error on the next N calls.
    drop_next: int = 0
    #: Return an isError result on the next N calls (server answered, badly).
    error_next: int = 0
    #: Fail to open a session on the next N connects.
    connect_fails: int = 0
    latency_sec: float = 0.0
    ping_fails: bool = False
    #: What call_tool returns. None means an echo of the tool name.
    reply: str | None = None
    #: Raise a JSON-RPC protocol error on the next N calls (server alive, call
    #: rejected) rather than a transport failure.
    protocol_error_next: int = 0
    tools: list[Any] = field(default_factory=list)

    opens: int = 0
    closes: int = 0
    calls: list[str] = field(default_factory=list)
    concurrent: int = 0
    max_concurrent: int = 0

    def factory(self):
        async def _open(stack: AsyncExitStack):
            if self.connect_fails:
                self.connect_fails -= 1
                raise ConnectionRefusedError("server not up")
            self.opens += 1
            stack.push_async_callback(self._closed)
            return FakeSession(self)

        return _open

    async def _closed(self) -> None:
        self.closes += 1
