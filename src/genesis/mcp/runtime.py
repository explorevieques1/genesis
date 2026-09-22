# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Long-lived server sessions, driven from a threaded system.

MCP Gateway.md asks for four things here: one long-lived session per server
rather than per call, queue-based dispatch so calls to one server serialize, one
silent reconnect on session loss and then a typed error, and an optional idle
timeout for stateless servers.

**The asyncio problem, and why it is solved this way.**
Nothing in Genesis is async. The Task Bus, the daemon, the orchestrator and the
voice loop are all threads. The MCP SDK is asyncio-only, and its sessions are
nested async context managers that must be entered and exited *in the same
task* -- so a session cannot be opened by one caller and used by another unless
something holds it open in between.

So: one event loop, on one daemon thread this module owns, for the whole
process. Sessions live in per-server *keeper* tasks that open the context
managers and then park until shutdown. Callers stay synchronous --
:meth:`GatewayRuntime.call` blocks -- and the async world never leaks past this
file. The alternative, making the fleet async, is a rewrite of Phase 1 to
accommodate a Phase 3 dependency.

**Serialization is a lock, and a lock is the queue.**
One :class:`asyncio.Lock` per server, whose waiters are FIFO. Calls to the same
server queue behind each other exactly as the note asks; calls to different
servers do not interact at all.

**What counts as session loss, and what does not.**
Only transport failures reconnect. A tool that returns an error is *working*
-- it answered -- and reconnecting would discard a healthy session over a bad
argument. A timeout also does not reconnect: a slow tool is not a dead socket,
and tearing down the session would abandon whatever else was queued behind it.
Both surface as typed failures without touching the connection.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import threading
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Protocol

from genesis.errors import DegradedError, TransientError
from genesis.mcp.errors import MCPServerSessionError

__all__ = [
    "GatewayRuntime",
    "ServerSession",
    "SessionFactory",
    "SessionLike",
    "ToolCallError",
    "ToolResult",
]


class ToolCallError(DegradedError):
    """The server answered, and the answer was an error.

    Degraded rather than transient on purpose: the session is fine, the call is
    not, and retrying an identical call against a healthy server just spends
    the rate limit to get the same answer.
    """


@dataclass(frozen=True)
class ToolResult:
    """What a tool returned.

    ``content`` is raw as it leaves the runtime and **fenced** by the time it
    leaves the gateway, for anything from an untrusted source. The runtime does
    not fence, because it does not know a tool's trust -- that is a property of
    the catalogue entry, not of the socket.
    """

    tool: str
    server: str
    content: Any
    structured: dict[str, Any] | None = None
    latency_ms: float = 0.0
    #: Set by the gateway when the payload was wrapped. Carries the detection
    #: flags and the provenance, so a caller can see *why* something is
    #: suspicious without re-scanning it.
    fence: Any = None


class SessionLike(Protocol):
    """The slice of ``mcp.ClientSession`` this module uses.

    A protocol rather than the SDK type so the runtime's reconnect, idle and
    serialization behaviour can be tested against a fake that fails on demand.
    Session loss is not reproducible on request against a real server, which
    means untested is the same as unverified.
    """

    async def list_tools(self) -> Any: ...
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...
    async def send_ping(self) -> Any: ...


#: Opens an initialized session and keeps it alive for the lifetime of the
#: stack. Everything transport-specific lives behind this one callable.
SessionFactory = Callable[[AsyncExitStack], Awaitable[SessionLike]]


def _is_protocol_error(exc: BaseException) -> bool:
    """Is this a JSON-RPC error from a live server, rather than a dead one?

    Duck-typed rather than ``isinstance(exc, McpError)`` because this module
    deliberately does not import the SDK -- that import lives in
    ``transports.py`` alone, which is what lets every rule here be tested
    against a fake. An SDK error carries ``.error`` with a numeric ``.code``;
    a broken pipe does not.
    """
    error = getattr(exc, "error", None)
    return error is not None and isinstance(getattr(error, "code", None), int)


#: In-band failures, by the prefix the server writes them with. Exa answers a
#: bad argument this way; mcp-server-fetch answers an HTTP 403 this way. Both
#: are prefixes of the *whole* result, which is what makes them safe to match:
#: a page containing the words cannot trigger it.
_INBAND_ERROR_PREFIXES = ("MCP error -", "Failed to fetch ")


def _inband_error(raw: Any) -> bool:
    """Did the server report a failure as ordinary text instead of ``isError``?

    Exa's hosted endpoint answers a bad argument with a normal, successful
    result whose only content is "MCP error -32602: ...". Without this the
    error string becomes the page a research agent then reads and cites — a
    failed fetch that looks exactly like a successful one, which is the
    quietest way a tool can lie about having worked.
    """
    content = getattr(raw, "content", None) or []
    if len(content) != 1:
        return False
    text = getattr(content[0], "text", "")
    return text.startswith(_INBAND_ERROR_PREFIXES)


def _explain(exc: BaseException | None) -> str:
    """Flatten an ExceptionGroup down to something an operator can act on.

    anyio task groups surface a failed connect as "unhandled errors in a
    TaskGroup (1 sub-exception)", which says nothing at all -- the actual cause
    (a missing binary, a server that crashed on an incompatible SDK version, a
    bad argument) is one level down. A server that will not start is the most
    common thing to debug here, so the message must carry the reason.
    """
    if exc is None:
        return "no reason recorded"
    inner = getattr(exc, "exceptions", None)
    if inner:
        return "; ".join(_explain(e) for e in inner)
    return f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------
# The owned event loop
# --------------------------------------------------------------------------


class _LoopThread:
    """One asyncio loop, on one daemon thread, for the whole process.

    Daemon so a hung server can never keep the process alive after the daemon
    has decided to exit -- the shutdown path a stuck MCP session would otherwise
    block is the same one the kill switch depends on.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="mcp-runtime", daemon=True
        )
        self._thread.start()
        self._started.wait(timeout=5.0)
        if self._loop is None:  # pragma: no cover - only on a broken interpreter
            raise RuntimeError("MCP runtime event loop did not start")

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._started.set()
        self._loop.run_forever()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("MCP runtime is not started")
        return self._loop

    def run(self, coro: Awaitable[Any], timeout: float | None) -> Any:
        """Run a coroutine on the loop and block until it finishes.

        The timeout is enforced on *this* side as well as inside the coroutine,
        so a coroutine that manages to block the loop still cannot block a
        caller forever.
        """
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)  # type: ignore[arg-type]
        try:
            return fut.result(timeout)
        except TimeoutError:
            fut.cancel()
            raise

    def stop(self) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._loop = None
        self._thread = None
        self._started.clear()


# --------------------------------------------------------------------------
# One server
# --------------------------------------------------------------------------


class ServerSession:
    """One long-lived session, with the reconnect and idle rules attached.

    Lives entirely on the runtime's event loop; every method here is awaited
    from that loop and never from a caller's thread.
    """

    def __init__(
        self,
        server: str,
        factory: SessionFactory,
        *,
        idle_timeout_sec: float | None = None,
    ) -> None:
        self.server = server
        self._factory = factory
        self._idle_timeout = idle_timeout_sec
        self._lock = asyncio.Lock()
        self._session: SessionLike | None = None
        self._keeper: asyncio.Task[None] | None = None
        self._ready: asyncio.Event = asyncio.Event()
        self._closing: asyncio.Event = asyncio.Event()
        self._error: BaseException | None = None
        self._last_used = 0.0
        #: Counted, not just logged. A server that reconnects on every other
        #: call is failing slowly, and Agent — Watchdog needs a number to see it.
        self.reconnects = 0

    # -- connection lifecycle ------------------------------------------

    async def _keep(self) -> None:
        """Hold the session's context managers open until asked to close."""
        try:
            async with AsyncExitStack() as stack:
                self._session = await self._factory(stack)
                self._error = None
                self._ready.set()
                await self._closing.wait()
        except BaseException as exc:  # noqa: BLE001 - recorded, re-raised to caller
            self._error = exc
            self._ready.set()  # unblock the waiter; it inspects _error
        finally:
            self._session = None

    async def _connect(self) -> SessionLike:
        if self._session is not None:
            return self._session
        self._ready.clear()
        self._closing.clear()
        self._error = None
        self._keeper = asyncio.create_task(self._keep(), name=f"mcp-{self.server}")
        await self._ready.wait()
        if self._session is None:
            raise MCPServerSessionError(
                f"could not open a session to {self.server!r}: {_explain(self._error)}"
            )
        return self._session

    async def _disconnect(self) -> None:
        self._closing.set()
        keeper, self._keeper = self._keeper, None
        if keeper is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(keeper, timeout=5.0)
        self._session = None
        self._ready.clear()

    # -- calling --------------------------------------------------------

    async def call(
        self, tool: str, arguments: dict[str, Any] | None, timeout: float
    ) -> ToolResult:
        """One tool call, serialized against every other call to this server."""
        async with self._lock:
            try:
                return await self._attempt(tool, arguments, timeout)
            except MCPServerSessionError:
                # The one silent reconnect. A dropped socket is not news; the
                # second failure is, and it leaves here as a typed error.
                self.reconnects += 1
                await self._disconnect()
                try:
                    return await self._attempt(tool, arguments, timeout)
                except MCPServerSessionError as exc:
                    await self._disconnect()
                    raise MCPServerSessionError(
                        f"{self.server}: session lost twice calling {tool!r} — {exc.reason}",
                        spoken_summary=f"I lost the connection to {self.server}.",
                    ) from exc

    async def _attempt(
        self, tool: str, arguments: dict[str, Any] | None, timeout: float
    ) -> ToolResult:
        session = await self._connect()
        started = time.perf_counter()
        try:
            async with asyncio.timeout(timeout):
                raw = await session.call_tool(tool, arguments or {})
        except TimeoutError as exc:
            # Deliberately not a reconnect: a slow tool is not a dead socket,
            # and tearing the session down would abandon whatever is queued.
            raise TransientError(
                f"{self.server}.{tool} timed out after {timeout:.0f}s"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - classified by shape, below
            if _is_protocol_error(exc):
                # The server spoke, and said no. "Invalid params" is a bad
                # argument, not a dead socket: reconnecting would tear down a
                # healthy session and abandon everything queued behind it, to
                # fix nothing. Degraded, like any other answer we cannot use.
                raise ToolCallError(f"{self.server}.{tool}: {exc}") from exc
            raise MCPServerSessionError(f"{self.server}: {exc!r}") from exc

        if getattr(raw, "isError", False) or _inband_error(raw):
            raise ToolCallError(f"{self.server}.{tool} returned an error: {raw}")

        self._last_used = time.monotonic()
        return ToolResult(
            tool=tool,
            server=self.server,
            content=getattr(raw, "content", raw),
            structured=getattr(raw, "structuredContent", None),
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    async def list_tools(self, timeout: float = 30.0) -> Any:
        async with self._lock:
            session = await self._connect()
            async with asyncio.timeout(timeout):
                return await session.list_tools()

    async def ping(self, timeout: float = 5.0) -> bool:
        """Cheap liveness, for Agent — Watchdog. No LLM, no tool call.

        Does not take the lock: a health probe that queues behind a slow tool
        call reports "unhealthy" for the one reason that is not a health
        problem, and the watchdog would restart a server that was merely busy.
        """
        session = self._session
        if session is None:
            return False
        try:
            async with asyncio.timeout(timeout):
                await session.send_ping()
        except Exception:  # noqa: BLE001 - any failure is a failed probe
            return False
        return True

    def idle_for(self) -> float:
        return time.monotonic() - self._last_used if self._last_used else 0.0

    async def reap_if_idle(self) -> bool:
        """Close a stateless server that nobody has used lately."""
        if self._idle_timeout is None or self._session is None:
            return False
        if self.idle_for() < self._idle_timeout:
            return False
        if self._lock.locked():
            return False
        async with self._lock:
            await self._disconnect()
        return True

    async def aclose(self) -> None:
        async with self._lock:
            await self._disconnect()

    @property
    def connected(self) -> bool:
        return self._session is not None


# --------------------------------------------------------------------------
# All servers
# --------------------------------------------------------------------------


class GatewayRuntime:
    """The synchronous face of every MCP session in the process.

    Callers are threads and stay threads. Nothing above this class awaits
    anything.
    """

    def __init__(self) -> None:
        self._thread = _LoopThread()
        self._sessions: dict[str, ServerSession] = {}
        self._started = False

    def start(self) -> None:
        self._thread.start()
        self._started = True
        # Close sessions at exit even if the owner never calls stop(). A stdio
        # server that ignores stdin EOF (stock-market does) is otherwise
        # orphaned on every exit, and a dev auto-restart turns that into a pile.
        atexit.register(self.stop)

    def add(
        self,
        server: str,
        factory: SessionFactory,
        *,
        idle_timeout_sec: float | None = None,
    ) -> ServerSession:
        """Register a server. Does **not** connect -- connection is lazy.

        Connecting on registration would make start-up depend on every server
        being up, which is the opposite of what a degradation ladder is for:
        one dead news server must not stop the system from booting.
        """
        if not self._started:
            raise RuntimeError("GatewayRuntime.start() before add()")

        async def _make() -> ServerSession:
            return ServerSession(server, factory, idle_timeout_sec=idle_timeout_sec)

        session = self._thread.run(_make(), timeout=5.0)
        self._sessions[server] = session
        return session

    def call(
        self,
        server: str,
        tool: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> ToolResult:
        session = self._session(server)
        # The outer budget is deliberately looser than the inner one: the inner
        # timeout is the tool's, this one only catches a wedged event loop.
        return self._thread.run(
            session.call(tool, arguments, timeout), timeout=timeout + 5.0
        )

    def list_tools(self, server: str, *, timeout: float = 30.0) -> Any:
        return self._thread.run(
            self._session(server).list_tools(timeout), timeout=timeout + 5.0
        )

    def health(self, server: str, *, timeout: float = 5.0) -> bool:
        return self._thread.run(self._session(server).ping(timeout), timeout=timeout + 2.0)

    def reap_idle(self) -> tuple[str, ...]:
        """Close idle stateless sessions. The daemon calls this on a cadence."""
        closed = []
        for name, session in self._sessions.items():
            if self._thread.run(session.reap_if_idle(), timeout=10.0):
                closed.append(name)
        return tuple(closed)

    def _session(self, server: str) -> ServerSession:
        try:
            return self._sessions[server]
        except KeyError:
            raise MCPServerSessionError(f"no session configured for {server!r}") from None

    @property
    def servers(self) -> tuple[str, ...]:
        return tuple(sorted(self._sessions))

    def stop(self) -> None:
        # Concurrently: a server that ignores stdin EOF costs the SDK's ~2s
        # grace before it is terminated, and seventeen of those in a row is
        # most of a restart.
        async def close_all() -> None:
            await asyncio.gather(
                *(s.aclose() for s in self._sessions.values()), return_exceptions=True
            )

        if self._sessions:
            with contextlib.suppress(Exception):
                self._thread.run(close_all(), timeout=15.0)
        self._sessions.clear()
        self._thread.stop()
        self._started = False

    def __enter__(self) -> GatewayRuntime:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
