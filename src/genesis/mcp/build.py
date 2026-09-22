# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Assembling a live gateway from config, and who is allowed to use it.

Two things live here that are otherwise scattered: the start-up sequence that
turns ``mcp_servers.yaml`` into a connected, catalogued gateway, and the
per-agent allow-lists for the components that exist today.

**Start-up is degraded-tolerant on purpose.** A server that will not start is
recorded and skipped, never fatal. Error Handling And Degradation is explicit
that one feed down means proceed with less and label it; a gateway that refused
to boot because a news server was unreachable would take the whole system down
for the least important thing in it.

**Allow-lists are the minimum that works.** Agent Contract's checklist says so
in as many words. Each grant below is written to be read by someone asking
"why does *this* component get *that*?", and the answer has to be a sentence
about the job, not "it seemed useful".
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from genesis.config import load_secrets
from genesis.daemon.calendar import MarketCalendar

from genesis.mcp.cache import ResultCache
from genesis.mcp.gateway import Gateway
from genesis.mcp.registry import ToolRegistry
from genesis.mcp.runtime import GatewayRuntime
from genesis.mcp.servers import ServerConfig, load_servers
from genesis.observability import EventLog

__all__ = ["ALLOW_LISTS", "GatewayBuild", "build_gateway"]


#: Who may reach what. Capability patterns, per MCP Gateway.md §entries.
#:
#: The orchestrator is the general-purpose surface — MCP Server Catalog.md
#: §general purpose is explicit that generality is granted at the allow-list,
#: never at the tool surface, and that the orchestrator and the idea
#: synthesizer are where it is granted. Note what is *not* here: no execution,
#: no broker, no order. The agent nearest the money is granted nothing at all
#: until Phase 7, and it will not be granted any of this.
ALLOW_LISTS: dict[str, tuple[str, ...]] = {
    # The voice. Answers questions, writes what you tell it to write, and
    # searches the web when the answer is not already known.
    "orchestrator": (
        "vault.*",      # read, search, and write notes — the point of the desk
        "fs.*",         # read files already in the vault (a saved PDF, a CSV)
        "web.*",        # search and fetch, both fenced on arrival
        "news.*",
        "time.*",
        # The reading desk. Filings, macro series, papers and documents are
        # the four kinds of primary source a person asks about out loud, and
        # every one of them is a read.
        "filings.*",
        "macro.*",
        "papers.*",
        "convert.*",   # a PDF on disk -> markdown a note can hold
        "repo.*",      # "what's failing in Genesis" is a question with an answer
        # The free market-data surface. All tier 3 — fine for answering a
        # question out loud, never for sizing a position. That restriction is
        # structural rather than a matter of this grant: Pre-Trade Risk Engine
        # reads tier 1, and nothing granted here is tier 1.
        "market-data.*",
        "fundamentals.*",
        "corporate.*",     # dividends, splits
        "analyst.*",       # recommendations, consensus, price targets
        "calendar.*",      # earnings, dividends, splits, IPOs, econ releases
        "screen.*",
        "ta.*",            # rsi, macd, full technical read
        "analytics.*",     # correlation and other descriptive statistics
        # Direct voice commands to the chart on the desk — the note grants
        # this to the orchestrator by name. Never to Execution Family.
        "chart.*",
        # Exa's deep-research agent: minutes per call, and it costs credits.
        # Granted because "research X for me" is the desk's whole point —
        # but it belongs on a Task Bus lane, never awaited by a spoken turn.
        "research.*",
    ),
    # The person at the keyboard, driving the terminal by hand.
    #
    # The patterns are the orchestrator's reading surface, deliberately, and
    # that symmetry is the design: anything Genesis can look up, a person can
    # look up themselves, through the same gateway and the same audit line.
    # A terminal where the model can reach further than its operator is one
    # where the operator cannot check the model's work.
    #
    # What is NOT copied across: `vault.*` (its writes), `chart.*` (it drives
    # the desktop chart) and `research.*` (minutes per call, and it costs
    # credits — a spend that belongs on a lane, not behind Enter). Reads only,
    # and `server/tool_routes.py` refuses a mutating tool a second time even
    # if a pattern here ever widened by accident.
    "operator": (
        "fs.read", "fs.list", "fs.stat",
        "vault.read", "vault.search",
        "web.*", "news.*", "time.*",
        "filings.*", "macro.*", "papers.*", "repo.*",
        "market-data.*", "fundamentals.*", "corporate.*",
        "analyst.*", "calendar.*", "screen.*", "ta.*", "analytics.*",
    ),
    # Research. Reads widely, writes only into the vault.
    "idea-synthesizer": (
        "vault.read", "vault.search", "vault.create", "vault.edit",
        "web.*", "news.*", "ta.*", "research.*",
        "filings.*", "macro.*", "papers.*", "convert.*",
        # Reads widely, and an idea starts from a screen or a number as often
        # as from an article.
        "market-data.*", "fundamentals.*", "analyst.*", "calendar.*",
        "screen.*", "analytics.*", "corporate.*",
    ),
    # Deep research on a *subject* rather than a symbol. It reads more
    # untrusted text than anything except the news agent, so it gets the
    # reading surface and nothing else: no vault write (it writes through the
    # research store, not through an MCP server), no market data, no chart.
    #
    # `research.*` is Exa's deep-research agent — minutes and real credits per
    # call. Granted here because this is the one agent whose entire job is
    # worth that spend, and it runs on a Task Bus lane where nothing is
    # waiting on it.
    "topic-researcher": (
        "web.*", "news.*", "papers.*", "research.*",
        "filings.*", "macro.*", "convert.*",
    ),
    # The top-down read. Prices and derived statistics, nothing written by a
    # stranger: this agent's output is the frame every other research agent
    # conditions on, which makes it the wrong place for text a page supplied.
    "market-analyst": (
        "market-data.*", "ta.*", "analytics.*", "screen.*", "macro.*",
        # genesis-tradingview-mcp allow-lists this agent by name, and these
        # four are the whole of what it gets: the afferent half. Reading the
        # chart on the desk is cheap, safe and retryable; driving it is not
        # the market analyst's job, so no `chart.*` and nothing mutating.
        # Afferent and efferent are different nerves — Biological Design.
        "chart.quote", "chart.ohlcv", "chart.watchlist", "chart.status",
    ),
    # The Phase 4 news agent: the most untrusted text in the system, and
    # therefore the narrowest grant. No vault writes — it produces results on
    # the bus, and something else decides what is worth keeping.
    "news-catalyst": (
        "web.*", "news.*",
        # A catalyst is usually a filing, a macro release or a scheduled event,
        # not a headline about one. MCP Server Catalog grants this agent
        # "news, filings, calendar, web fetch" — all four now exist.
        "filings.*", "macro.*", "calendar.*",
        # A dividend cut and a reverse split are catalysts, and both are facts
        # rather than prices. Note what is still absent: no `market-data.*`.
        # The agent that ingests the most untrusted text in the system has no
        # reason to read a quote, and the narrowest grant that does the job is
        # the one that survives a prompt injection.
        "corporate.*",
    ),
    # --- Charting Family -------------------------------------------------
    #
    # Five narrow grants rather than one shared "charting" grant, because a
    # per-agent allow-list that several agents share is not a per-agent
    # allow-list. Each of these is the minimum that works, per the Agent
    # Contract checklist.
    #
    # Note what NONE of them has: `web.*` and `news.*`. The charting family
    # reasons about numbers this system computed. Giving the agent that draws
    # your levels a channel for text written by strangers would be inviting a
    # prompt injection into the one output a trader acts on without re-reading.

    # Bars in, a Markup Spec and a rendered chart out. `vault.create` because
    # the note requires a chart note next to the image.
    "chart-markup": (
        "market-data.ohlcv", "market-data.quote", "market-data.snapshot",
        "genesis-charting.*",
        "vault.create", "vault.edit",
        # Applying the mark to the desktop chart. Navigation and markup only —
        # `chart.*` cannot reach the Trade panel by construction (see
        # genesis-tradingview-mcp hard rule 1).
        "chart.*",
    ),
    # Reads a chart it did not fetch and a spec it did not write. No vault
    # write: an interpretation is a result on the bus, and something else
    # decides whether it is worth keeping.
    "pattern-recognition": (
        "market-data.ohlcv",
        "genesis-charting.render", "genesis-charting.structure",
    ),
    # Several timeframes of one symbol, and a composite of them.
    "multi-timeframe": (
        "market-data.ohlcv",
        "genesis-charting.render_composite", "genesis-charting.structure",
    ),
    # The reflex. The narrowest grant in the system and the one that matters
    # most: it must keep working when everything else is degraded, so it
    # depends on the smallest possible surface — bars and a quote.
    "level-watcher": ("market-data.ohlcv", "market-data.quote"),
    # The non-price half. Macro series and batch bars are its whole diet.
    "data-viz": (
        "market-data.ohlcv", "market-data.ohlcv-batch", "market-data.overview",
        "macro.series", "macro.search",
        "genesis-charting.render_analytics",
        "vault.create", "vault.edit",
    ),
    # Watchdog reads the machine's own state and nothing else. No web, so a
    # health probe can never be the thing that ingests an injection.
    # Watchdog reads the machine's own state and nothing else. Deliberately
    # NOT granted `repo.*`, even though filing a defect is its job and the
    # server is wired: issue and PR bodies are prose written by strangers, and
    # the one component whose answer to "is the system healthy" must be
    # believed is the last one that should be reading untrusted text. Filing a
    # defect is a write, which is a separate grant on a separate day.
    "watchdog": ("time.*", "git.*", "fs.list", "fs.stat"),
}


@dataclass
class GatewayBuild:
    """What start-up managed to assemble, and what it could not."""

    gateway: Gateway
    connected: tuple[str, ...] = ()
    failed: dict[str, str] = field(default_factory=dict)
    skipped: tuple[str, ...] = ()

    @property
    def tool_count(self) -> int:
        return len(self.gateway.registry)

    @property
    def empty(self) -> tuple[str, ...]:
        """Servers that started, answered, and contributed nothing.

        The single most useful line in a start-up report, because it is the
        symptom of the failure that otherwise looks like success: a wrong
        package name, a toolset that needs enabling, a `tools:` block naming
        tools this version renamed. The server is *up*, so nothing errors —
        the capability is simply, silently, not there.

        Reported rather than raised. A server with no tools is not a reason to
        refuse to boot, for the same reason a dead one is not.
        """
        return tuple(
            server
            for server in self.connected
            if not self.gateway.registry.by_server(server)
        )

    def summary(self) -> str:
        parts = [f"{self.tool_count} tools from {len(self.connected)} servers"]
        if self.failed:
            parts.append(f"{len(self.failed)} unavailable")
        if self.empty:
            parts.append(f"{len(self.empty)} registered nothing")
        return ", ".join(parts)


def build_gateway(
    servers: tuple[ServerConfig, ...] | None = None,
    *,
    events: EventLog | None = None,
    grant: bool = True,
) -> GatewayBuild:
    """Connect to every enabled server, catalogue it, and grant allow-lists.

    ``allow_writes=True`` and ``allow_execution_writes=False`` is the Phase 3-6
    posture in one line: Genesis may write your vault, and may not go anywhere
    near an order.
    """
    # Servers name the environment variables they need; load the secrets file
    # into the environment first so a caller does not have to export by hand.
    # Only names in SECRET_ENV_VARS are read — an env var may supply a
    # credential, never change behaviour.
    load_secrets(Path("~/.genesis/.env"))

    registry = ToolRegistry(allow_writes=True, allow_execution_writes=False)
    runtime = GatewayRuntime()
    runtime.start()
    # The cache is handed the real market calendar, not a 86400-second
    # divisor: "the current daily bar" ends at the New York close, which is
    # not midnight anywhere and moves on half days. Without it the cache would
    # miss for the eight hours between the close and 00:00 UTC — correct
    # answers, needlessly bought.
    gateway = Gateway(
        registry, runtime, events=events, cache=ResultCache(calendar=MarketCalendar())
    )

    build = GatewayBuild(gateway=gateway)
    enabled = []
    for config in servers if servers is not None else load_servers():
        if not config.enabled:
            build.skipped += (config.id,)
            continue
        # Configured before connecting, so a server that is slow to start
        # cannot be hammered by whatever retries the connection.
        if config.rate_limit is not None:
            gateway.limiter.configure(
                config.id,
                per_minute=config.rate_limit.per_minute,
                burst=config.rate_limit.burst,
            )
        enabled.append(config)

    # Spawning is the slow part -- seconds per server, a minute in sequence --
    # so discovery runs concurrently. Registration stays in this thread and in
    # config order, so the catalogue is the same whichever server answers first.
    # ponytail: fixed pool of 8, tune if spawn bursts pressure an 8 GB machine
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="mcp-discover") as pool:
        futures = [(c, pool.submit(gateway.discover, c)) for c in enabled]
        for config, future in futures:
            try:
                gateway.register_server(config, future.result())
                build.connected += (config.id,)
            except Exception as exc:  # noqa: BLE001 - one dead server is not fatal
                build.failed[config.id] = str(exc)

    if grant:
        _grant_all(gateway)
    return build


def _grant_all(gateway: Gateway) -> None:
    """Bind the allow-lists to whatever actually registered.

    Deliberately tolerant of patterns that match nothing: a grant for a server
    that failed to start is not an error, it is a component that will be
    unavailable to that agent until the server comes back.
    """
    from genesis.agents.base import AgentDeclaration

    for agent_id, patterns in ALLOW_LISTS.items():
        gateway.grant(
            AgentDeclaration(
                id=agent_id,
                name=agent_id.replace("-", " ").title(),
                family="core" if agent_id == "orchestrator" else "research",
                cadence=[{"type": "on-demand"}],
                tools=patterns,
            )
        )
