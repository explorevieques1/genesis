# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""The call path. Every tool call in Genesis goes through :meth:`Gateway.call`.

MCP Gateway.md draws it as::

    agent ──► gateway
                ├── allow-list check         → reject if outside
                ├── rate limit / quota
                ├── cache lookup             → return if fresh
                ├── dispatch to session      → queue, serialize per server
                ├── timeout + retry (typed)
                ├── fence the result
                └── log to Episodic Log
              ◄── typed result or typed failure

Every stage above is built. The order is the design, and two orderings in it
are load-bearing: the allow-list runs before anything reaches a server, so a
refused call costs nothing and reveals nothing; and the fence runs after
dispatch and before the return, so there is no code path on which a model sees
raw third-party text.

**Agents call capabilities, not servers.**
:meth:`call` takes ``market-data.ohlcv``, not ``alpaca.get_stock_bars``. Which
server serves it is the registry's decision and can be re-decided by tier
without touching a single agent -- the whole point of deduplicating at the
registry. A concrete tool id is accepted too, for the router handing back a specific
choice, but capability lookup wins if a string is somehow both.
"""

from __future__ import annotations

from dataclasses import replace
import re
from typing import TYPE_CHECKING, Any, Iterator

from genesis.config import ConfigError
from genesis.ids import new_trace_id
from genesis.mcp.allowlist import AllowList
from genesis.mcp.cache import ResultCache
from genesis.mcp.discovery import DiscoveredTool, normalize
from genesis.mcp.errors import ToolNotAllowedError, ToolNotRegisteredError
from genesis.mcp.fence import TrustLedger, UnsafeUrlError, check_url, text_of, wrap
from genesis.mcp.limits import RateLimiter
from genesis.mcp.registry import ToolRegistry
from genesis.mcp.router import DEFAULT_LIMIT, SearchBudget, Selection, ToolRouter
from genesis.mcp.runtime import GatewayRuntime, ToolResult
from genesis.mcp.servers import ServerConfig
from genesis.mcp.spec import ToolSpec, Trust

if TYPE_CHECKING:  # pragma: no cover - typing only
    from genesis.agents.base import AgentDeclaration
    from genesis.observability import EventLog

__all__ = ["Gateway"]


class Gateway:
    """One chokepoint. Built once at start-up, read from every agent thread."""

    def __init__(
        self,
        registry: ToolRegistry,
        runtime: GatewayRuntime,
        *,
        events: EventLog | None = None,
        trust: TrustLedger | None = None,
        cache: ResultCache | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.registry = registry
        self.runtime = runtime
        self.events = events
        #: Lowered whenever a source serves an injection attempt, and read by
        #: the router, which is where lowering it actually does something.
        self.trust = trust if trust is not None else TrustLedger()
        #: Present by default. A cache that had to be opted into would be a
        #: cache that is absent on the machine where it matters, and its own
        #: default policy is NO_CACHE — so an empty catalogue caches nothing
        #: and a described one caches exactly what it described.
        self.cache = cache if cache is not None else ResultCache()
        self.limiter = limiter if limiter is not None else RateLimiter()
        self.router = ToolRouter(registry, trust=self.trust)
        self._allow: dict[str, AllowList] = {}

    #: Build plan step 4, built. Every result from an untrusted tool is wrapped
    #: by :mod:`genesis.mcp.fence` before it leaves :meth:`call`. There is no
    #: switch to turn this off, and that is deliberate: a fence with an off
    #: position is a fence that is one config edit from absent.
    fences_untrusted: bool = True

    # ------------------------------------------------------------------
    # Building the catalogue
    # ------------------------------------------------------------------

    def register_server(
        self, config: ServerConfig, discovered: list[DiscoveredTool]
    ) -> int:
        """Catalogue what this server offers, filtered by what we asked for."""
        return self.registry.register_all(normalize(config, discovered))

    def connect_and_register(self, config: ServerConfig) -> int:
        """Open a session, ask the server what it has, catalogue the answer.

        Discovery is the one place a session is opened eagerly, because a
        catalogue built from a server we could not reach would be a catalogue
        that lies about what the system can do.
        """
        return self.register_server(config, self.discover(config))

    def discover(self, config: ServerConfig) -> list[DiscoveredTool]:
        """Open a session and ask what it has, without cataloguing.

        Split from registration so boot can discover every server concurrently
        (each spawn is seconds) while the catalogue is still written in one
        thread, in config order.
        """
        from genesis.mcp.transports import factory_for

        self.runtime.add(
            config.id, factory_for(config), idle_timeout_sec=config.idle_timeout_sec
        )
        # 90s, not the 30s call default: first contact includes the spawn, and
        # `uvx` resolving OpenBB alone takes ~30s -- more when others boot too.
        return _discovered_from(self.runtime.list_tools(config.id, timeout=90.0))

    # ------------------------------------------------------------------
    # Granting
    # ------------------------------------------------------------------

    def grant(self, declaration: AgentDeclaration) -> AllowList:
        """Bind an agent's declared tools to an enforced allow-list.

        Two refusals here, both at boot rather than at call time, because a
        misconfiguration that only shows up on the one call that matters is
        not a boundary anyone can rely on:

        **Nothing untrusted for the execution family, ever.** The catalogue is
        explicit: none of the general-purpose surface reaches Execution Family.
        The agent nearest the money keeps the fewest tools, and no prompt
        reaches this check.

        **No execution-class write, to anyone, in this phase.** The registry
        cannot hold one, so this is a second lock on the same door -- cheap,
        and the one that would catch a registry constructed wrongly.
        """
        allow = AllowList.of(declaration.id, declaration.tools)
        granted = [self.registry.get(tool_id) for tool_id in allow.granted(self.registry)]

        untrusted = [s.id for s in granted if s.trust is Trust.UNTRUSTED]
        if untrusted and declaration.family == "execution":
            raise ConfigError(
                f"execution agent {declaration.id!r} was granted untrusted tools "
                f"({', '.join(untrusted)}). The execution family reads no "
                f"third-party text — see MCP Server Catalog.md §general purpose"
            )

        from genesis.mcp.registry import EXECUTION_NAMESPACES

        execution = [
            s.id
            for s in granted
            if s.mutating and s.capability.startswith(EXECUTION_NAMESPACES)
        ]
        if execution and not self.registry.allow_execution_writes:
            raise ConfigError(  # pragma: no cover - the registry cannot hold these
                f"agent {declaration.id!r} was granted execution-class writes: {execution}"
            )

        self._allow[declaration.id] = allow
        return allow

    def revoke(self, agent: str) -> None:
        """Drop an agent's allow-list. Deny-by-default then applies to it."""
        self._allow.pop(agent, None)

    def tools_for(self, agent: str) -> tuple[str, ...]:
        """Everything this agent can actually reach. Empty is the honest default."""
        allow = self._allow.get(agent)
        return allow.granted(self.registry) if allow else ()

    # ------------------------------------------------------------------
    # Selecting — what an agent is shown before it decides
    # ------------------------------------------------------------------

    def select(
        self,
        agent: str,
        task: str,
        *,
        task_type: str = "",
        limit: int = DEFAULT_LIMIT,
    ) -> Selection:
        """The handful of tools worth putting in front of this agent.

        Selection is scoped to the allow-list, not merely filtered by it.
        Ranking the whole catalogue and trimming afterwards would give the same
        answer and leak the existence of tools this agent may not call into a
        selection log it can read — which is a map of the boundary, handed to
        the component the boundary exists to contain.
        """
        selection = self.router.select(
            task, self._granted_specs(agent), task_type=task_type, limit=limit
        )
        self._log_selection(agent, task, selection, event="tool.selected")
        return selection

    def tool_search(
        self,
        agent: str,
        query: str,
        *,
        budget: SearchBudget,
        limit: int = 5,
    ) -> Selection:
        """The escape hatch, for when the router did not guess right.

        The budget is spent inside the router, before ranking, so an exhausted
        one raises without touching the catalogue. Capped per reply because an
        uncapped search tool is a loop made of rephrasings.
        """
        selection = self.router.search(
            query, self._granted_specs(agent), budget=budget, limit=limit
        )
        self._log_selection(agent, query, selection, event="tool.searched")
        return selection

    def _granted_specs(self, agent: str) -> tuple[ToolSpec, ...]:
        allow = self._allow.get(agent)
        if allow is None:
            return ()
        return tuple(
            spec for spec in self.registry if allow.permits(spec.capability)
        )

    def _log_selection(
        self, agent: str, task: str, selection: Selection, *, event: str
    ) -> None:
        """Record what was chosen and, crucially, whether it was chosen.

        ``matched=False`` means nothing in the task touched anything the agent
        can reach, and the tools are a deterministic fallback. A log that could
        not tell the two apart would present a shrug as a decision, and the
        first person debugging a bad tool choice would be reading a rationale
        that was never had.
        """
        if self.events is None:
            return
        self.events.emit(
            event=event,
            agent=agent,
            trace_id=new_trace_id(),
            level="debug",
            data={
                # The task is not logged verbatim: it can carry the user's
                # words, and Working Memory owns what is quoted where.
                "task_terms": len(task.split()),
                "considered": selection.considered,
                "chosen": list(selection.ids),
                "matched": selection.matched,
                "scores": [list(s) for s in selection.scores],
            },
        )

    # ------------------------------------------------------------------
    # Calling
    # ------------------------------------------------------------------

    def call(
        self,
        agent: str,
        capability: str,
        arguments: dict[str, Any] | None = None,
        *,
        trace_id: str | None = None,
        timeout: float | None = None,
    ) -> ToolResult:
        """The whole call path, in order. The order is the design."""
        trace_id = trace_id or new_trace_id()
        spec = self._resolve(capability)

        # 1. Allow-list. First, and before anything reaches a server. An agent
        #    with no allow-list at all is denied rather than defaulted open.
        allow = self._allow.get(agent) or AllowList.of(agent, ())
        allow.check(spec.capability, spec.id)

        # 2. SSRF guard. Every URL-shaped argument, on every call, not only on
        #    tools we think fetch things — a server we did not write decides
        #    what its arguments mean, and "this one doesn't fetch" is exactly
        #    the assumption that ages badly.
        self._guard_urls(agent, trace_id, spec, arguments)

        # 3. Cache lookup, before the rate limit. The order is deliberate: a
        #    cached answer costs the quota nothing, and checking the limit
        #    first would spend a token to discover we already had the answer —
        #    which on a 25-calls-a-day key is the difference between a cache
        #    that helps and one that is decorative.
        hit = self.cache.get(spec, arguments)
        if hit is not None:
            self._log(
                "tool.cache_hit",
                agent,
                trace_id,
                spec,
                data={"age_sec": round(hit.age_sec, 3)},
                cost={"tool_calls": 0, "wall_ms": 0.0},
            )
            return replace(hit.result, latency_ms=0.0)

        # 4. Rate limit / quota. Raises RateLimitedError, which is transient,
        #    so the Task Bus backs off rather than this inventing a second
        #    retry machinery beside the one that already exists.
        self.limiter.check(spec.server)

        # 5. Dispatch. Serialized per server by the runtime, with one silent
        #    reconnect and then a typed MCPServerSessionError.
        try:
            result = self.runtime.call(
                spec.server,
                spec.name,
                arguments,
                # The catalogue's timeout, not a constant: `call_timeout_sec`
                # and per-tool overrides were configurable and then ignored,
                # which is worse than not offering the setting.
                timeout=timeout if timeout is not None else spec.timeout_sec,
            )
        except Exception as exc:
            # Degrade before failing. A stale answer, labelled, beats no
            # answer — Error Handling And Degradation. It is only ever reached
            # here, on the path where the live call already failed, so the
            # cache can never be the reason fresh data was not used.
            stale = self.cache.get(spec, arguments, allow_stale=True)
            if stale is not None:
                self._log(
                    "tool.served_stale",
                    agent,
                    trace_id,
                    spec,
                    level="warn",
                    data={
                        "age_sec": round(stale.age_sec, 3),
                        "error": type(exc).__name__,
                    },
                    degraded=True,
                )
                return replace(stale.result, latency_ms=0.0)
            self._log(
                "tool.failed",
                agent,
                trace_id,
                spec,
                level="warn",
                data={"error": type(exc).__name__, "reason": str(exc)},
            )
            raise

        # 6. Fence. Untrusted results are wrapped before they leave this
        #    method, so there is no code path on which a model sees raw
        #    third-party text.
        flags: tuple[str, ...] = ()
        if spec.trust is Trust.UNTRUSTED:
            result, flags = self._fence(result, spec)
            if flags:
                score = self.trust.penalise(spec.server, flags)
                self._log(
                    "tool.injection_detected",
                    agent,
                    trace_id,
                    spec,
                    level="warn",
                    data={"flags": list(flags), "trust_score": score},
                )

        # 7. Store. The *fenced* result is what goes in, so a cache hit and a
        #    live call are the same object to every caller. Caching the raw
        #    payload and fencing on the way out would be one code path that
        #    fences and one that could forget to.
        self.cache.put(spec, arguments, result)

        # 8. Log. Latency and outcome per call, feeding Observability.
        self._log(
            "tool.called",
            agent,
            trace_id,
            spec,
            data={"fenced": spec.trust is Trust.UNTRUSTED, "flags": list(flags)},
            cost={"tool_calls": 1, "wall_ms": round(result.latency_ms, 1)},
            degraded=bool(flags),
        )
        return result

    def _fence(self, result: ToolResult, spec: ToolSpec) -> tuple[ToolResult, tuple[str, ...]]:
        """Replace the payload with its fenced form. Not annotate it -- replace.

        Keeping the raw text alongside the wrapped text would leave a field
        somebody could reach for, and the whole guarantee is that there is no
        such field. What comes out of the gateway is quoted or it does not
        exist.
        """
        fenced = wrap(text_of(result.content), source=spec.server)
        return (
            replace(result, content=fenced.text, fence=fenced),
            fenced.flags,
        )

    def _guard_urls(
        self,
        agent: str,
        trace_id: str,
        spec: ToolSpec,
        arguments: dict[str, Any] | None,
    ) -> None:
        """Refuse to hand a server a URL that points back inside the machine."""
        for value in _strings_in(arguments or {}):
            if not _looks_like_url(value):
                continue
            try:
                check_url(value)
            except UnsafeUrlError as exc:
                self._log(
                    "tool.blocked_url",
                    agent,
                    trace_id,
                    spec,
                    level="warn",
                    data={"reason": str(exc)},
                )
                raise ToolNotAllowedError(agent, spec.id) from exc

    def _resolve(self, name: str) -> ToolSpec:
        spec = self.registry.for_capability(name) or self.registry.find(name)
        if spec is None:
            raise ToolNotRegisteredError(name)
        return spec

    def _log(
        self,
        event: str,
        agent: str,
        trace_id: str,
        spec: ToolSpec,
        *,
        level: str = "info",
        data: dict[str, Any] | None = None,
        cost: dict[str, Any] | None = None,
        degraded: bool = False,
    ) -> None:
        if self.events is None:
            return
        self.events.emit(
            event=event,
            agent=agent,
            trace_id=trace_id,
            level=level,
            data={"tool": spec.id, "capability": spec.capability, **(data or {})},
            cost=cost,
            degraded=degraded,
        )


def _discovered_from(listing: Any) -> list[DiscoveredTool]:
    """SDK ``ListToolsResult`` -> our own shape. The seam, crossed once.

    Both spellings of every field are read. The SDK renamed ``inputSchema`` to
    ``input_schema`` and ``readOnlyHint`` to ``read_only_hint`` in v2, keeping
    the old names only as wire aliases -- so a ``getattr`` for the camelCase
    name returns the default and *nothing fails*. That is the worst shape a bug
    can have: every tool silently got an empty schema, which the router would
    later have had to plan with. ``test_sdk_shapes.py`` pins this against the
    real type so the next rename breaks a test instead of a phase.
    """
    out = []
    for tool in getattr(listing, "tools", []) or []:
        annotations = getattr(tool, "annotations", None)
        out.append(
            DiscoveredTool(
                name=tool.name,
                description=getattr(tool, "description", "") or "",
                input_schema=_either(tool, "input_schema", "inputSchema") or {},
                read_only_hint=_read_only_hint(annotations),
            )
        )
    return out


def _either(obj: Any, *names: str) -> Any:
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _read_only_hint(annotations: Any) -> bool | None:
    """The server's own claim about whether a tool only reads.

    ``destructiveHint`` overrides: a server that says a tool is both read-only
    and destructive has contradicted itself, and the safe reading of a
    contradiction is the dangerous one.
    """
    if annotations is None:
        return None
    if _either(annotations, "destructive_hint", "destructiveHint") is True:
        return False
    return _either(annotations, "read_only_hint", "readOnlyHint")


def _strings_in(value: Any) -> Iterator[str]:
    """Every string anywhere in an argument tree.

    Recursive because a URL hides just as well in ``{"pages": [{"url": ...}]}``
    as at the top level, and a guard that only checked top-level arguments
    would be a guard against the naive case only.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings_in(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings_in(item)


_URLISH = re.compile(r"^\s*[a-zA-Z][a-zA-Z0-9+.-]*://")


def _looks_like_url(value: str) -> bool:
    """Anything with a scheme. Deliberately generous.

    ``file://`` and ``gopher://`` are not URLs we would fetch, which is the
    point of noticing them: check_url rejects the scheme, and a narrower test
    that only recognised http(s) would wave them straight through.
    """
    return bool(_URLISH.match(value))
