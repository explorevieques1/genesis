# Spec: Genesis Markdown/10-Architecture/Observability.md
"""The ``genesis`` command-line entry point.

Console style is the house style from Conventions.md: a leading emoji per line,
indentation for hierarchy. See :mod:`genesis.observability`.

Three commands carry the system: ``config`` proves the loader works and refuses
to start on a bad file, ``daemon`` runs the spine, and ``voice`` is the surface
you talk to.

``daemon`` matters more than its size suggests. The [[Task Bus]] is durable, so
a plan dispatched by voice survives with or without something to run it -- but
survives *unexecuted*. Until this command existed the queue had no consumer
outside the test suite, which meant Phase 1's spine had never actually run.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from genesis import __version__
from genesis.config import (
    DEFAULT_CONFIG_PATH,
    Config,
    ConfigError,
    default_config_text,
    load_config,
    load_secrets,
)
from genesis.errors import DegradedError, FatalError
from genesis.llm.tiers import TIERS, set_tier
from genesis.observability import Console

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
#: A command ran but could not do its job -- no data, vendor down, store
#: empty. Distinct from a config error so a scheduler can tell "try again
#: later" from "this will never work until a human edits something".
EXIT_RUNTIME_ERROR = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="genesis",
        description="Genesis Agent -- autonomous trading system.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"genesis {__version__}",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        metavar="PATH",
        help=f"config file (default: {DEFAULT_CONFIG_PATH})",
    )

    sub = parser.add_subparsers(dest="command")

    cfg = sub.add_parser("config", help="inspect and manage configuration")
    cfg_sub = cfg.add_subparsers(dest="config_command", required=True)
    cfg_sub.add_parser("check", help="validate the config stack and report")
    set_tier_cmd = cfg_sub.add_parser(
        "set-tier", help="point one model tier at one backend and model"
    )
    set_tier_cmd.add_argument("tier", choices=list(TIERS))
    set_tier_cmd.add_argument("backend", help="anthropic, ollama, gemini, groq, openrouter, none")
    set_tier_cmd.add_argument("model", nargs="?", default="", help="model name")
    cfg_sub.add_parser("usage", help="what the model tiers cost today")
    cfg_sub.add_parser("show", help="print the effective configuration")
    init = cfg_sub.add_parser(
        "init", help="write the default template to the config path"
    )
    init.add_argument(
        "--force", action="store_true", help="overwrite an existing config file"
    )

    run = sub.add_parser("daemon", help="run the daemon: the forever loop that executes tasks")
    run.add_argument(
        "--tick",
        type=float,
        default=None,
        metavar="SEC",
        help="seconds between ticks (default: the daemon's own cadence)",
    )
    run.add_argument(
        "--once",
        action="store_true",
        help="boot, run a single tick, report, and exit -- a smoke test",
    )

    mcp = sub.add_parser("mcp", help="inspect the tool gateway (Phase 3)")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_sub.add_parser(
        "check", help="connect to every enabled server and report what registered"
    )
    mcp_tools = mcp_sub.add_parser("tools", help="print the registered tool surface")
    mcp_tools.add_argument(
        "--agent",
        metavar="ID",
        help="show only what this agent is allowed to reach",
    )

    chart = sub.add_parser(
        "chart", help="draw a marked-up chart from the market data store"
    )
    chart.add_argument(
        "symbol",
        help="AAPL, ESZ5, or a canonical id like FUT:CME:ES:2025-12. "
        "A bare futures root is refused — see Open Questions §13.",
    )
    chart.add_argument(
        "timeframe", nargs="?", default="1D", help="1D, 1H, 15m… (default: 1D)"
    )
    chart.add_argument("--bars", type=int, default=0, help="how many bars to draw")
    chart.add_argument("--out", type=Path, help="where to write the PNG")
    chart.add_argument(
        "--consumer",
        default="chart_markup",
        help="which fallback chain to use (default: chart_markup)",
    )
    chart.add_argument(
        "--no-fetch",
        action="store_true",
        help="store only — fail rather than reach a vendor",
    )

    # Parity, not convenience: Operating Model §1 says anything Genesis can do,
    # a person can do by hand, through the same door. Every mode below runs the
    # same agent the orchestrator would dispatch, writes to the same directory,
    # and leaves the same audit line. A capability reachable only by saying a
    # sentence and hoping the router picks it is not shipped.
    res = sub.add_parser(
        "research", help="run the research family by hand"
    )
    res.add_argument(
        "subject", nargs="*",
        help="what to research — a subject, not a ticker: \"W.D. Gann\", "
             "\"gamma squeezes\". Omit it and use --regime or --ideas.",
    )
    res.add_argument(
        "--regime", action="store_true",
        help="the top-down market read instead of a topic",
    )
    res.add_argument(
        "--ideas", action="store_true",
        help="fuse the research already gathered into ranked ideas",
    )
    res.add_argument(
        "--quick", action="store_true",
        help="search the subject as typed; skip sub-question planning",
    )
    res.add_argument(
        "--summarise", "--summarize", dest="summarise", action="store_true",
        help="fuse the notes already stored on the subject into one synopsis; "
             "reads the directory, never the web",
    )
    res.add_argument("--list", action="store_true", help="list the directory")
    res.add_argument("--show", metavar="ID", help="print one note in full")
    res.add_argument("--no-tools", action="store_true", help="skip the MCP gateway")

    can = sub.add_parser(
        "canvas", help="the research canvas and the knowledge graph behind it"
    )
    can.add_argument(
        "query", nargs="*",
        help="open a canvas on this — a subject, a ticker, a theme",
    )
    can.add_argument("--list", action="store_true", help="list canvases")
    can.add_argument("--show", metavar="ID", help="print one canvas")
    can.add_argument("--graph", action="store_true", help="what is in the graph")
    can.add_argument(
        "--backfill", action="store_true",
        help="project every research note into the graph (idempotent)",
    )
    can.add_argument("--depth", type=int, default=1, help="hops to expand (default 1)")
    # Parity with the drag-a-line gesture on the Research page. A claim you can
    # make with the mouse you can make by hand, through the same store.
    can.add_argument(
        "--link", nargs=3, metavar=("SRC", "KIND", "DST"),
        help="assert an edge in the graph, under your own namespace",
    )
    can.add_argument(
        "--unlink", nargs=3, metavar=("SRC", "KIND", "DST"),
        help="retract an edge you asserted (an agent's edge is refused)",
    )

    srv = sub.add_parser(
        "serve", help="run the local UI server (HTTP + WebSocket, loopback only)"
    )
    srv.add_argument("--port", type=int, default=8765)
    srv.add_argument(
        "--host", default="127.0.0.1",
        help="loopback only; this surface can launch local apps",
    )
    srv.add_argument(
        "--no-daemon", action="store_true",
        help="serve the UI only; typed commands cannot reach the fleet "
             "until `genesis daemon` runs",
    )

    comp = sub.add_parser(
        "company", help="everything Genesis knows about a company"
    )
    comp.add_argument("symbol", help="a ticker, e.g. NVDA")
    comp.add_argument(
        "--refresh", action="store_true", help="bypass the cache and refetch"
    )
    comp.add_argument(
        "--no-edgar",
        action="store_true",
        help="skip SEC EDGAR — faster, but loses as-filed numbers and filed dates",
    )
    comp.add_argument(
        "--json", action="store_true", help="print the summary as JSON"
    )
    comp.add_argument(
        "--field", metavar="NAME", help="print one field with its provenance"
    )

    ib = sub.add_parser("ibkr", help="the IBKR feed: health and tier-1 promotion")
    ib_sub = ib.add_subparsers(dest="ibkr_command", required=True)
    ib_sub.add_parser(
        "check", help="connect to IB Gateway and report what actually works"
    )
    rec = ib_sub.add_parser(
        "reconcile",
        help="diff IBKR against Databento — the gate for promoting IBKR to tier 1",
    )
    rec.add_argument("symbol", help="e.g. ESZ5 or FUT:CME:ES:2025-12")
    rec.add_argument("timeframe", nargs="?", default="1H")
    rec.add_argument(
        "--days", type=int, default=2, help="how far back to compare (default: 2)"
    )

    ks = sub.add_parser("killswitch", help="the kill switch: a separate process that halts trading")
    ks_sub = ks.add_subparsers(dest="killswitch_command", required=True)
    ks_sub.add_parser("serve", help="run the kill switch process (genesis serve starts one for you)")
    fire = ks_sub.add_parser("fire", help="halt now: cancel working orders, keep protective stops")
    fire.add_argument("--flatten", action="store_true", help="also close every position at market")
    fire.add_argument("--reason", default="cli")

    acct = sub.add_parser(
        "account",
        help="what you own, what it cost, what it's worth (the accountant, by hand)",
    )
    acct.add_argument(
        "--reconcile", action="store_true",
        help="compare the ledger against the broker's own report and record the finding",
    )
    acct.add_argument("--json", action="store_true", help="print the snapshot as JSON")

    sub.add_parser("biology", help="the organ map: each organ and the build status of its notes")

    # The DNA organ's parity twin. Biological Design calls the vault and the
    # prompts the genome; this is how a person reads it without opening 220
    # files, through the same door the `DNA` module uses.
    dna_p = sub.add_parser("dna", help="the genome: the vault, the prompts, and whether the body map still tells the truth")
    dna_sub = dna_p.add_subparsers(dest="dna_command")
    dna_sub.add_parser("status", help="how much of the genome is expressed, by status")
    dna_check = dna_sub.add_parser("check", help="the six kinds of drift between spec and code")
    dna_check.add_argument("--fix", action="store_true",
                           help="reconnect cut nerves and move stale `spec` statuses on")
    dna_show = dna_sub.add_parser("show", help="one note: its status, its code, and what points at it")
    dna_show.add_argument("note", help="a note name, as a [[wikilink]] spells it")
    dna_sub.add_parser("prompts", help="every system prompt, where it lives and how big it is")
    dna_sub.add_parser("map", help="regenerate 00-Meta/Vault Map.md from the vault")

    # What this desk may trade. A safety control, so it has a door of its own
    # rather than being a number in a config nobody reads.
    uni = sub.add_parser("universe", help="the tradeable universe: futures roots, the S&P 500 and the core ETFs")
    uni_sub = uni.add_subparsers(dest="universe_command")
    uni_sub.add_parser("show", help="what is allowed, where it came from, and how old it is")
    uni_sub.add_parser("refresh", help="fetch S&P 500 membership and write the snapshot")

    idea = sub.add_parser("idea", help="your trade ideas: record one, list the desk")
    idea_sub = idea.add_subparsers(dest="idea_command", required=True)
    add = idea_sub.add_parser(
        "add", help="record an idea — no invalidation, no idea",
    )
    add.add_argument("symbol", help="a root on the allow-list (NQ) or a contract (FUT:CME:NQ:2026-12)")
    add.add_argument("direction", choices=["long", "short"])
    add.add_argument("--thesis", required=True, help="why, in your own words")
    add.add_argument("--entry", metavar="LOW-HIGH", help="the entry zone, e.g. 20000-20050")
    add.add_argument("--stop", type=float, metavar="PRICE",
                     help="where it's wrong, as a price — without it nothing can be sized")
    add.add_argument("--target", type=float, action="append", default=[], metavar="PRICE")
    add.add_argument("--wrong-if", metavar="CONDITION",
                     help="where it's wrong as a condition, if not (only) a price")
    add.add_argument("--why", metavar="TEXT", help="why that voids the idea")
    add.add_argument("--setup", default="")
    add.add_argument("--timeframe", choices=["scalp", "intraday", "swing", "position"], default="swing")
    add.add_argument("--horizon", type=int, default=5, metavar="DAYS")
    add.add_argument("--confidence", type=float, default=0.5)
    idea_sub.add_parser("list", help="the live ideas on the desk, yours and the synthesizer's")

    plan = sub.add_parser(
        "plan", help="a plan of action from the ideas on the desk — ranked, sized by the gate",
    )
    plan.add_argument("--no-save", action="store_true", help="show it without writing the brief")
    plan.add_argument("--json", action="store_true")
    plan.add_argument("--port", type=int, default=8765, help="the running server (default 8765)")

    mem = sub.add_parser("memory", help="the memory fabric: recall, consolidation, embeddings")
    mem_sub = mem.add_subparsers(dest="memory_command", required=True)
    mem_sub.add_parser("stats", help="what each layer holds")
    mem_sub.add_parser(
        "consolidate", help="run the nightly passes now (the daemon runs them at 21:00)"
    )
    mem_search = mem_sub.add_parser("search", help="semantic recall: what else is like this?")
    mem_search.add_argument("query")
    mem_search.add_argument(
        "--namespace", action="append", default=[],
        help="namespaces to search; repeatable. Filtering happens before scoring.",
    )
    mem_search.add_argument("--limit", type=int, default=10)
    mem_sub.add_parser(
        "install-embedder", help="download the local embedding model (~130 MB, once)"
    )

    listen = sub.add_parser("voice", help="run the voice loop (Phase 2)")
    listen.add_argument(
        "--silent", action="store_true", help="run without opening the speakers"
    )
    listen.add_argument(
        "--wake-model", default="tiny.en", help="local wake model size (default: tiny.en)"
    )
    listen.add_argument(
        "--say", metavar="TEXT", help="speak one line and exit -- a voice smoke test"
    )
    listen.add_argument(
        "--no-daemon",
        action="store_true",
        help="do not host a daemon; assume `genesis daemon` is running elsewhere",
    )
    listen.add_argument(
        "--no-tools",
        action="store_true",
        help="skip the MCP gateway; answer from the model alone (starts faster)",
    )

    return parser


def _open_bus(config: Config):
    """The one database the daemon and the voice loop share.

    Both processes open the same file. That is the intended arrangement rather
    than a compromise: the bus is the handoff, and a plan dispatched by voice
    is picked up by whichever daemon is running -- or waits durably until one
    is, which is the property Phase 1 was built for.
    """
    from genesis.bus.bus import TaskBus

    config.memory.db_path.parent.mkdir(parents=True, exist_ok=True)
    return TaskBus(config.memory.db_path)


def _open_gateway(console: Console):
    """Build the MCP gateway, or report why not and carry on.

    `genesis daemon` needs one for the same reason `genesis voice` does: the
    agents read their bars through it. A daemon with no gateway is still a
    useful daemon -- the calendar and the bus are the spine -- so this never
    raises.
    """
    try:
        from genesis.mcp.build import build_gateway

        build = build_gateway()
        console.info(f"Tools ready · {build.summary()}")
        return build.gateway
    except Exception as exc:  # noqa: BLE001 - the spine runs without tools
        console.warn(f"MCP gateway did not build ({exc}) — running without tools")
        return None


def _build_daemon(config: Config, console: Console, bus, gateway=None):  # noqa: ANN001
    """Assemble the daemon and register whatever fleet can be built.

    With a gateway, the Charting Family is registered: it is the first fleet
    that exists, and it needs the gateway because bars come through it. Without
    one the daemon still runs -- the calendar advances, the bus recovers, claims
    expire and are retried -- and a dispatched chart task fails honestly with
    *"no agent registered as ..."* rather than sitting silently in a queue.

    Charting agents are registered rather than optional-if-convenient because
    the Level Watcher is a cadence agent: it must be supervised and ticked, not
    invoked. Nothing else in the system polls levels.
    """
    from genesis.daemon.calendar import MarketCalendar
    from genesis.daemon.daemon import Daemon

    daemon = Daemon(bus, calendar=MarketCalendar(), console=console)

    # The Journal family first, and unconditionally: it needs no gateway, and
    # the charting family deposits its level outcomes into the journal store, so
    # the sink has to exist before the producer. Registering it even with no
    # tools is deliberate — the Watchdog is the only thing that notices a silent
    # failure, and the observation store is what makes the system accumulate.
    journal = None
    registered = 0
    try:
        journal_fleet = _build_journal_fleet(config, console, gateway, daemon=daemon)
        journal = journal_fleet.store
        for agent in journal_fleet.all():
            daemon.register(agent)
        registered += len(journal_fleet.all())
    except Exception as exc:  # noqa: BLE001 - a fleet that will not build must not stop the spine
        console.warn(f"Journal family did not build ({exc}).")

    # Charting needs the gateway: its bars come through it.
    if gateway is None:
        console.warn(
            "No MCP gateway — the charting family is not registered; "
            "chart tasks will fail honestly."
        )
    else:
        try:
            fleet = _build_charting_fleet(
                config, console, gateway, publish=daemon.publish, journal=journal
            )
            for agent in fleet.all():
                daemon.register(agent)
            registered += len(fleet.all())
        except Exception as exc:  # noqa: BLE001
            console.warn(f"Charting family did not build ({exc}).")

    # The Research family. Built after the journal (it reads `lessons`) and
    # independently of charting, because two of its three agents need nothing
    # charting needs: the topic researcher wants the gateway's web tools, and
    # the idea synthesizer wants only what is already in the research
    # directory. What each one cannot have, it is not registered for.
    research = None
    try:
        research = _build_research_fleet(config, console, gateway, journal=journal)
        for agent in research.all():
            daemon.register(agent)
        registered += len(research.all())
    except Exception as exc:  # noqa: BLE001
        console.warn(f"Research family did not build ({exc}).")

    # Workflows last: a `run` step dispatches to agents, and the families above
    # are what it may dispatch to. Same register call, same scheduler.
    try:
        from genesis.automation import attach, open_store
        from genesis.automation.runner import register_all

        registered += register_all(daemon, open_store(config), gateway)
        attach(daemon, gateway)
    except Exception as exc:  # noqa: BLE001
        console.warn(f"Workflows did not load ({exc}).")

    console.info(f"Fleet registered · {registered} agents")
    daemon.research_fleet = research
    return daemon


def _warm_fleet(config: Config, console: Console):  # noqa: ANN001
    """Start the fleet behind the UI, in the background, and wire it to typing.

    The port binds immediately and the fleet arrives a few seconds later, which
    is the right order: spawning seventeen MCP servers before the socket opens
    makes `genesis serve` look broken for half a minute, and the first thing a
    person does is load a page, not ask a question.

    Until :meth:`Analyst.attach` runs, a typed sentence still answers -- from
    the reasoner, without the fleet. That is a *quieter* Genesis for a few
    seconds, never a broken one, and it is the same degradation the voice path
    already has when no daemon is running.

    Returns a callable that shuts the daemon down.
    """
    from genesis.server.analyst import ANALYST
    from genesis.server.fleet import FLEET_STATE

    bus = _open_bus(config)
    daemon = None
    gateway = None
    stopping = threading.Event()

    def warm() -> None:
        nonlocal daemon, gateway
        try:
            # The process-wide holder, not `_open_gateway`: the ladder and the
            # tool panels read GATEWAY, so a private build here meant the first
            # typed question spawned every MCP server a second time.
            from genesis.server.tool_routes import GATEWAY

            gateway, error = GATEWAY.get()
            if error:
                console.warn(f"MCP gateway did not build ({error}) — running without tools")
            daemon = _build_daemon(config, console, bus, gateway=gateway)
            registry = _registry_for(daemon, gateway)
            # Attach before the daemon runs: the bus is durable, so a plan
            # dispatched in the gap between these two lines is picked up on the
            # first tick rather than lost.
            ANALYST.attach(
                bus=bus,
                registry=registry,
                supervisor=daemon.supervisor,
                scheduler=daemon.scheduler,
            )
            console.info(
                f"Typed commands can reach {len(registry)} agent(s)."
                if registry else
                "No agents registered — typed commands answer from the reasoner."
            )
            # Build the ladder now, so the first question does not pay for it.
            ANALYST.ladder()
            FLEET_STATE.set("up", agents=len(registry))
            if not stopping.is_set():
                daemon.run_forever()
        except Exception as exc:  # noqa: BLE001 - the UI must outlive its fleet
            # Recorded, not only logged. This exact line printed once per boot
            # for two days while `./genesis status` said `healthy` -- a
            # capability summary 28 characters over its limit had taken down
            # every cron, every workflow and every agent, and nothing that a
            # person looks at said so. The UI outliving its fleet is correct;
            # the UI *claiming to be well* while it does is the bug.
            FLEET_STATE.set("failed", detail=str(exc))
            console.warn(f"The fleet did not start ({exc}). The UI is still up.")

    thread = threading.Thread(target=warm, name="genesis-serve-fleet", daemon=True)
    thread.start()

    def stop() -> None:
        stopping.set()
        if daemon is not None:
            daemon.shutdown()
        # The fleet thread may be mid-tick on the bus; closing the SQLite
        # connection under it segfaults the interpreter. If it will not finish,
        # leave the bus for process exit rather than race it.
        thread.join(timeout=10.0)
        if not thread.is_alive():
            bus.close()
        # Explicitly, not only via atexit: by then the thread pools the MCP SDK
        # terminates processes through are already shut down.
        if gateway is not None:
            gateway.runtime.stop()

    return stop


def _registry_for(daemon, gateway):  # noqa: ANN001
    """What the planner may plan for: only agents this daemon will actually run.

    Shared by `voice` and `serve` so the two front doors advertise the same
    fleet. A capability reachable by speaking and not by typing is the parity
    failure Operating Model §2 is written against, and two copies of this
    function is how that failure comes back.
    """
    from genesis.agents.charting.fleet import register as register_charting
    from genesis.agents.journal.fleet import register as register_journal
    from genesis.agents.research.fleet import register as register_research
    from genesis.orchestrator.registry import CapabilityRegistry

    registry = CapabilityRegistry()
    if gateway is not None:
        register_charting(registry)
    register_journal(registry)
    # Only the research agents that actually built. `register` takes the fleet
    # rather than a flag so the catalogue cannot advertise a regime read on a
    # machine with no market data.
    register_research(registry, fleet=getattr(daemon, "research_fleet", None))
    return registry


def _build_research_fleet(config: Config, console: Console, gateway, journal=None):  # noqa: ANN001
    """Construct the Research Family.

    The bar source is the ``research`` consumer chain if the config declares
    one and the default otherwise -- resolved through ``build_source`` rather
    than here, so the chain stays in one place (Market Data Plane).

    A source that will not build is a note, not a raise: the market analyst is
    then not registered, and the other two agents work exactly as before.
    """
    from genesis.agents.research.fleet import build_fleet
    from genesis.marketdata.build import build_source

    source = None
    try:
        built = build_source(config, "research")
        source = built.source
        for name, why in built.skipped:
            console.warn(f"market data adapter {name} unavailable: {why}")
    except Exception as exc:  # noqa: BLE001
        console.warn(f"No bar source for the market analyst ({exc}).")

    return build_fleet(
        gateway=gateway,
        source=source,
        journal=journal,
        backend=_tier_backend(config, console, "large"),
        planner_backend=_tier_backend(config, console, "small"),
        vault=str(config.memory.vault_path),
        db_path=str(config.memory.db_path.parent / "research.db"),
        plan_inputs=_plan_inputs(config),
        console=console,
    )


def _plan_inputs(config: Config):  # noqa: ANN202
    from genesis.agents.research.session_plan import default_inputs

    return default_inputs(config)


def _build_journal_fleet(config: Config, console: Console, gateway, daemon=None):  # noqa: ANN001
    """Construct the Journal Family.

    Registered even with no gateway and no fills, because two of its six agents
    are useful from the first boot: the Watchdog is the only thing that notices
    a silent failure, and the store is where every other family deposits the
    observations that later become lessons. The four trade-dependent agents run
    and honestly report that there is nothing yet.
    """
    from genesis.agents.journal.fleet import build_fleet
    from genesis.news.store import NewsStore
    from genesis.research.store import ResearchStore

    memory = config.memory.db_path.parent
    # With the daemon, the Watchdog can see the fleet and the queue, and the
    # Digest can compress the episodic log. Without one they are blind to both.
    return build_fleet(
        db_path=str(memory / "journal.db"),
        backend=_tier_backend(config, console, "large"),
        small_backend=_tier_backend(config, console, "small"),
        gateway=gateway,
        supervisor=getattr(daemon, "supervisor", None),
        bus=getattr(daemon, "bus", None),
        episodic=getattr(getattr(daemon, "bus", None), "log", None),
        # Read-only here: the morning brief quotes what research already wrote.
        research=ResearchStore(path=memory / "research.db", vault=None),
        news=NewsStore(memory / "news.db"),
        # 21:00 is the whole nightly memory pass. Built here rather than inside
        # the fleet so `genesis memory consolidate` and the cron run the same
        # object graph -- one builder, two doors (Operating Model §1).
        consolidator=_consolidator(config),
        console=console,
    )


def _tier_backend(config: Config, console: Console, tier_name: str):  # noqa: ANN001
    """One model tier for the fleets, or None with a warning on the console.

    The construction itself lives in :func:`genesis.llm.tiers.build_tier`,
    shared with the orchestrator's ladder -- see that function for why there is
    exactly one copy of it.
    """
    from genesis.llm.tiers import build_tier

    built = build_tier(config, tier_name)
    if built.note:
        (console.error if built.refused else console.warn)(built.note)
    return built.backend


def _build_charting_fleet(config: Config, console: Console, gateway, publish=None, journal=None):  # noqa: ANN001
    """Construct the Charting Family against the live gateway and model tiers.

    A tier that will not construct is a note, never a raise. Without the large
    tier chart markup is deterministic and still correct; without the vision
    tier pattern recognition runs rules-only. Both are the documented degraded
    modes, and both are far better than a fleet that refuses to start.
    """
    from genesis.agents.charting.fleet import build_fleet

    return build_fleet(
        gateway=gateway,
        backend=_tier_backend(config, console, "large"),
        vision_backend=_tier_backend(config, console, "vision"),
        chart_dir=str(config.memory.vault_path / "20-Charts"),
        db_path=str(config.memory.db_path.parent / "charting.db"),
        publish=publish,
        console=console,
    )



def _cmd_daemon(config: Config, console: Console, *, tick: float | None, once: bool) -> int:
    from genesis.daemon.daemon import TICK_SEC

    bus = _open_bus(config)
    daemon = _build_daemon(config, console, bus, gateway=_open_gateway(console))
    try:
        if once:
            daemon.boot()
            report = daemon.tick()
            with console.nest():
                console.line("\u2705", f"ran {len(report.ran)} task(s), dispatched {len(report.dispatched)}")
            daemon.shutdown()
            return EXIT_OK
        daemon.run_forever(tick_sec=tick if tick is not None else TICK_SEC)
    except KeyboardInterrupt:
        console.info("Stopping.")
    finally:
        bus.close()
    return EXIT_OK


def _cmd_voice(
    config: Config,
    console: Console,
    *,
    silent: bool,
    wake_model: str,
    say: str | None,
    no_daemon: bool = False,
    no_tools: bool = False,
) -> int:
    """Run the voice loop, or speak one line and exit.

    ``--say`` exists because the first question about a voice stack is always
    "does it make sound", and answering it should not require a microphone, a
    wake word, or a quiet room.
    """
    from genesis.orchestrator.build import build_voice_loop

    if say is not None:
        from genesis.voice.player import Player
        from genesis.voice.speaker import Speaker, default_backends
        from genesis.voice.speech import speakable

        backends = default_backends(config.identity.voice_id or "")
        if not backends:
            console.error("No TTS backend. Is ELEVENLABS_API_KEY set?")
            return EXIT_CONFIG_ERROR
        console.info(f"Speaking: {speakable(say)}")
        with Player(sample_rate=24_000) as player:
            result = Speaker(backends, player).say(say)
        console.info(f"Outcome: {result.outcome.value}")
        if result.detail:
            console.warn(result.detail)
        return EXIT_OK if result.ok else EXIT_CONFIG_ERROR

    # The bus the planner dispatches onto, and -- unless told otherwise -- a
    # daemon in this process to drain it. Without one, a dispatched plan is
    # durably queued and never runs, which looks exactly like a hang.
    bus = _open_bus(config)

    # The tool surface, built before the mic opens *and before the daemon*.
    # Spawning fifteen servers takes tens of seconds, and LLM Model Tiers is
    # explicit that cold starts destroy the voice budget -- the first thing you
    # ask must not be the request that pays for it. It also has to exist before
    # the fleet, because the agents fetch their bars through it. A gateway that
    # fails to build is a Genesis that answers without tools, never one that
    # refuses to listen.
    gateway = None
    if not no_tools:
        console.info("Connecting to MCP servers...")
        try:
            from genesis.mcp.build import build_gateway

            build = build_gateway()
            gateway = build.gateway
            console.info(f"Tools ready · {build.summary()}")
            for server, why in build.failed.items():
                console.warn(f"{server} unavailable: {why}")
        except Exception as exc:  # noqa: BLE001 - voice is a surface, not the spine
            console.warn(f"MCP gateway did not build ({exc}) - answering without tools")

    daemon = None
    daemon_thread = None
    if not no_daemon:
        # `run_forever` boots on entry, so nothing boots it here -- booting
        # twice would re-announce the fleet and re-run recovery.
        daemon = _build_daemon(config, console, bus, gateway=gateway)
        daemon_thread = threading.Thread(
            target=daemon.run_forever, name="genesis-daemon", daemon=True
        )

    # What the planner is allowed to plan for. Registered only when a daemon in
    # this process can actually run it: a catalogue advertising agents nothing
    # will drain turns "I can chart that" into a task that queues forever, and
    # a planner that declines is more honest than one that promises.
    registry = _registry_for(daemon, gateway) if daemon is not None else None

    console.info("Loading the local wake model...")
    stack = build_voice_loop(
        config,
        silent=silent,
        wake_model=wake_model,
        on_turn=_print_turn(console),
        bus=bus,
        gateway=gateway,
        registry=registry,
    )
    for note in stack.notes:
        console.warn(note)

    if daemon_thread is not None:
        daemon_thread.start()
        console.info("Daemon running in this process — dispatched plans will execute.")
    else:
        console.warn("No daemon here — plans queue until `genesis daemon` runs.")

    console.info(f"Listening. Say \"{config.identity.wake_word}\" to wake me. Ctrl-C to stop.")
    try:
        stack.loop.start()
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        console.info("Stopping.")
    finally:
        stack.close()
        if daemon is not None:
            daemon.shutdown()
        if daemon_thread is not None:
            # Let the tick in flight finish before the bus closes underneath it.
            daemon_thread.join(timeout=5.0)
        bus.close()
    return EXIT_OK


def _print_turn(console: Console):
    def show(turn) -> None:  # noqa: ANN001
        if turn.intent in ("ambient", "echo"):
            return  # the room talking, or us. Never noise on the console.
        console.info(f'heard: "{turn.heard.strip()}"  [{turn.intent}/{turn.path}]')
        if turn.spoken:
            with console.nest():
                console.info(f'said:  "{turn.spoken}"  ({turn.total_ms:.0f} ms)')
    return show


def _cmd_company(
    console: Console,
    *,
    symbol: str,
    refresh: bool,
    use_edgar: bool,
    as_json: bool,
    one_field: str | None,
) -> int:
    """Everything known about a company. Spec: Company Data Model.md.

    No model anywhere in this path. It is a data assembly and a print, which is
    why it works with no API key and returns the same answer twice.
    """
    import json as _json

    from genesis.company.profile import resolve, summarise
    from genesis.errors import GenesisError

    try:
        result = resolve(symbol, refresh=refresh, use_edgar=use_edgar)
    except GenesisError as exc:
        console.error(exc.reason)
        return EXIT_RUNTIME_ERROR

    profile = result.profile

    if one_field:
        entry = profile.sourced(one_field)
        if entry is None:
            console.error(
                f"{profile.symbol} has no field {one_field!r}. "
                f"`--json` lists the summary; {len(profile)} fields are held."
            )
            return EXIT_RUNTIME_ERROR
        # Provenance always travels with a spoken number. Safety Invariants §10.
        print(f"{entry.value}  [{entry.label()}, {_ago(entry.age)}]")
        return EXIT_OK

    summary = summarise(profile)
    if as_json:
        print(_json.dumps(summary, indent=2, default=str))
        return EXIT_OK

    console.line("🏢", f"{summary.get('name') or profile.symbol} · {profile.symbol}")
    with console.nest():
        bits = [
            b for b in (summary.get("exchange"), summary.get("sector"),
                        summary.get("industry")) if b
        ]
        if bits:
            console.line("🏷️", " · ".join(str(b) for b in bits))

        cap, price = summary.get("market_cap"), summary.get("price")
        if cap or price:
            parts = []
            if price:
                parts.append(f"{price} {summary.get('currency') or ''}".strip())
            if cap:
                parts.append(f"cap {_big(cap)}")
            for key, label in (("pe_trailing", "PE"), ("pe_forward", "fwd PE")):
                if summary.get(key):
                    parts.append(f"{label} {float(summary[key]):.1f}")
            console.line("💰", " · ".join(parts))

        if summary.get("revenue_fy"):
            filed = summary.get("revenue_filed")
            console.line(
                "📊",
                f"FY{summary['revenue_fy_end']} revenue {_big(summary['revenue_fy'])}"
                + (
                    f" · net {_big(summary['net_income_fy'])}"
                    if summary.get("net_income_fy") else ""
                )
                # The filed date is printed because it is the difference
                # between a fact and a lookahead bug. See Company Data Model
                # hazard 2.
                + (f" · filed {filed}" if filed else " · filed date UNKNOWN"),
            )

        for key, label in (("margin_gross", "gross"), ("margin_profit", "net")):
            pass
        margins = [
            f"{label} {float(summary[key]):.1%}"
            for key, label in (("margin_gross", "gross"), ("margin_profit", "net"))
            if summary.get(key) is not None
        ]
        if summary.get("growth_revenue") is not None:
            margins.append(f"rev growth {float(summary['growth_revenue']):.1%}")
        if margins:
            console.line("📈", " · ".join(margins))

        if summary.get("target_mean"):
            console.line(
                "🎯",
                f"{summary.get('analyst_count') or '?'} analysts · mean target "
                f"{float(summary['target_mean']):.2f}"
                + (f" · {summary['recommendation']}" if summary.get("recommendation") else ""),
            )

        held = summary.get("held_institutions")
        short = summary.get("short_percent_float")
        if held is not None or short is not None:
            owned = []
            if held is not None:
                owned.append(f"{float(held):.0%} institutional")
            if short is not None:
                owned.append(f"{float(short):.1%} short")
            console.line("🏦", " · ".join(owned))

        # Provenance, always, and never optional. An unlabelled stale number is
        # a confabulation under Safety Invariants §10 whether it is a price or
        # a margin.
        console.line(
            "🔎",
            f"{'store' if result.from_cache else ' + '.join(result.providers_used)}"
            f" · tier {summary['_tier']} · {len(profile)} fields"
            + (" · cached" if result.from_cache else f" · {result.network_calls} calls"),
        )
        if profile.has_untrusted:
            console.line("📰", f"{len(profile.get('news') or [])} headlines — tier 4, untrusted")
        if summary["_currency_mismatch"]:
            console.warn(
                f"prices in {profile.currency}, books in "
                f"{profile.financial_currency} — cross-currency ratios refused"
            )
        for conflict in summary["_conflicts"]:
            console.warn(conflict)
        for name, why in profile.missing:
            console.warn(f"{name} unavailable — {why}")
    return EXIT_OK


def _big(value: object) -> str:
    """A large number as a person says it. 5562502742016 -> 5.56T."""
    try:
        amount = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)
    for cut, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(amount) >= cut:
            return f"{amount / cut:.2f}{suffix}"
    return f"{amount:.2f}"


def _ago(delta: object) -> str:
    seconds = getattr(delta, "total_seconds", lambda: 0.0)()
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{int(seconds / 60)}m ago"
    if seconds < 172800:
        return f"{int(seconds / 3600)}h ago"
    return f"{int(seconds / 86400)}d ago"


def _cmd_killswitch(config: Config, console: Console, args) -> int:  # noqa: ANN001
    """Serve the kill switch, or fire it. Firing falls back to raising the halt
    flag directly when the process is not answering -- the flag alone still
    stops every new order."""
    import json
    import urllib.request

    if args.killswitch_command == "serve":
        from genesis.execution.killswitch import main

        main()
        return EXIT_OK
    level = "flatten" if args.flatten else "halt"
    url = f"http://127.0.0.1:{config.execution.killswitch_port}/{level}"
    req = urllib.request.Request(url, data=json.dumps({"reason": args.reason}).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 — loopback only
            out = json.loads(r.read())
    except Exception as exc:  # noqa: BLE001
        from genesis.execution import halt

        doc = halt.engage(halt.path_for(config.execution.state_dir), level=level, trigger=args.reason)
        console.error(f"kill switch process unreachable ({exc}); halt flag raised directly ({doc['id']}). "
                      f"Broker state NOT verified — cancel at IBKR if the daemon is down.")
        return EXIT_OK if level == "halt" else 1
    console.line("🛑", f"{level}: {out.get('detail') or out}")
    return EXIT_OK if out.get("ok") else 1


def _cmd_ibkr(config: Config, console: Console, args) -> int:  # noqa: ANN001
    """IBKR health and the tier-1 promotion gate. Spec: Market Data Sources.md."""
    if args.ibkr_command == "check":
        return _cmd_ibkr_check(config, console)
    return _cmd_ibkr_reconcile(
        config, console,
        symbol=args.symbol, timeframe=args.timeframe, days=args.days,
    )


def _cmd_ibkr_check(config: Config, console: Console) -> int:
    """Say what actually works, and never more than was verified.

    Deliberately layered — library, then socket, then a real API round trip —
    because each layer fails differently and "IBKR is down" is four different
    problems with four different fixes. A check that collapsed them into one
    boolean would be the kind of proprioception that is worse than none.
    """
    from genesis.errors import GenesisError
    from genesis.marketdata.adapters.ibkr import IbkrAdapter, IbkrConnection

    spec = config.marketdata.adapters.get("ibkr")
    console.line("🔌", "IB Gateway")
    with console.nest():
        if spec is None:
            console.error("no `ibkr` entry under marketdata.adapters")
            return EXIT_CONFIG_ERROR
        console.line(
            "⚙️",
            f"{spec.host}:{spec.port} · client {spec.client_id} · "
            f"{spec.market_data_type} · tier {spec.tier}"
            + ("" if spec.enabled else " · DISABLED in config"),
        )
        if spec.tier == 1:
            console.warn(
                "tier 1 — confirm `genesis ibkr reconcile` was run and its "
                "tolerance is recorded in Market Data Sources.md"
            )

        connection = IbkrConnection(
            host=spec.host or "127.0.0.1",
            port=spec.port or 4002,
            client_id=spec.client_id if spec.client_id is not None else 17,
            market_data_type=spec.market_data_type or "delayed",
            use_watchdog=spec.use_watchdog,
        )
        if not connection.available:
            console.error("`ib_async` is not installed — `uv pip install ib_async`")
            return EXIT_RUNTIME_ERROR

        try:
            ib = connection.connect()
        except GenesisError as exc:
            console.error(exc.reason)
            return EXIT_RUNTIME_ERROR

        try:
            console.line("✅", f"connected · server time {ib.reqCurrentTime()}")
            # Read-only is the invariant worth confirming out loud, because it
            # is the one that makes this connection structurally incapable of
            # placing an order.
            console.line(
                "🔒",
                "client connected read-only; gateway READ_ONLY_API is the "
                "enforcing side (deploy/ib-gateway/README.md)",
            )

            adapter = IbkrAdapter(connection=connection, tier=spec.tier)
            probe = _ibkr_probe_symbol(config)
            console.line("🧪", f"probe: {probe}")
            with console.nest():
                from genesis.marketdata.interface import BarRequest

                end = datetime.now(UTC)
                bars = adapter.fetch(
                    BarRequest(probe, "1H", end - timedelta(days=2), end)
                )
                if not bars:
                    console.warn(
                        "connected, but the probe returned no bars — market "
                        "closed, or no data permission for this contract"
                    )
                    return EXIT_RUNTIME_ERROR
                console.line(
                    "🕯️",
                    f"{len(bars)} bars · last {bars[-1].close} @ "
                    f"{bars[-1].ts:%Y-%m-%d %H:%M} UTC · tier {bars[-1].tier}",
                )
        except GenesisError as exc:
            console.error(exc.reason)
            return EXIT_RUNTIME_ERROR
        finally:
            connection.disconnect()
    return EXIT_OK


def _ibkr_probe_symbol(config: Config) -> str:
    """A contract to test with. Config first, then a sane CME default."""
    configured = config.agents.get("marketdata", {}).get("ibkr_probe")
    if configured:
        return str(configured)
    # Front-quarter ES. Chosen because it is the most liquid CME contract and
    # because delayed data for it is free, so the probe works on an unfunded
    # paper account.
    #
    # The mid-month roll is the part worth stating. A quarterly contract stops
    # trading in the third week of its expiry month, so from roughly the 15th
    # onward "this quarter's contract" is a contract whose data has already
    # ended -- and a probe against it reports the gateway as broken when it is
    # fine. Same failure that made `genesis chart ESZ5` return nothing today.
    now = datetime.now(UTC)
    month = ((now.month - 1) // 3 + 1) * 3
    if now.month == month and now.day >= 15:
        month += 3
    year = now.year + (month > 12)
    if month > 12:
        month -= 12
    return f"FUT:CME:ES:{year}-{month:02d}"


def _cmd_ibkr_reconcile(
    config: Config, console: Console, *, symbol: str, timeframe: str, days: int
) -> int:
    """Diff IBKR against Databento. The gate for tier 1.

    Prints the measured difference and stops. It deliberately does NOT promote
    anything: the tolerance is a judgement about how much disagreement is
    acceptable before a number sizes a position, and that judgement belongs to
    a person who then writes it into the note.
    """
    from genesis.errors import GenesisError
    from genesis.marketdata.build import build_adapters
    from genesis.marketdata.reconcile import reconcile_adapters
    from genesis.marketdata.source import resolve_symbol

    try:
        symbol_id = resolve_symbol(symbol)
    except GenesisError as exc:
        console.error(exc.reason)
        return EXIT_CONFIG_ERROR

    adapters, skipped = build_adapters(config.marketdata, ["ibkr", "databento"])
    for name, why in skipped:
        console.error(f"{name} unavailable — {why}")
    if len(adapters) < 2:
        console.error(
            "reconciliation needs BOTH sources. Comparing one feed against "
            "itself proves nothing, so this refuses rather than half-running."
        )
        return EXIT_RUNTIME_ERROR

    end = datetime.now(UTC)
    console.line("⚖️", f"reconciling {symbol_id} {timeframe} over {days}d")
    try:
        result = reconcile_adapters(
            adapters[0], adapters[1], symbol_id, timeframe,
            start=end - timedelta(days=days), end=end,
        )
    except GenesisError as exc:
        console.error(exc.reason)
        return EXIT_RUNTIME_ERROR

    for line in result.report().splitlines():
        print(line)

    with console.nest():
        console.line(
            "📋",
            "Write the worst absolute difference into Market Data Sources.md "
            "(§'Promotion to tier 1'), make it a test, THEN set "
            "marketdata.adapters.ibkr.tier to 1.",
        )
        if result.only_a or result.only_b:
            console.warn(
                "the two feeds disagree about which bars exist. Understand "
                "that before setting any tolerance — it is usually a session "
                "boundary convention, and it is more informative than the "
                "price deltas."
            )
    return EXIT_OK


def _cmd_canvas(config: Config, console: Console, args) -> int:  # noqa: ANN001
    """The research canvas by hand — parity with the Research page.

    No gateway and no models: the canvas is a view of what has already been
    learned, so every operation here is a read of the graph plus a row in the
    canvas store. It is the cheapest command in the system, and that is the
    point — looking at what you know should not cost anything.
    """
    from genesis.memory.graph import KnowledgeGraph
    from genesis.research.canvas import CanvasStore
    from genesis.research.store import ResearchStore

    memory = config.memory.db_path.parent
    graph = KnowledgeGraph(path=memory / "graph.db")
    store = CanvasStore(path=memory / "canvas.db", graph=graph)

    if args.backfill:
        research = ResearchStore(path=memory / "research.db", vault=None, graph=graph)
        console.line("🕸️", f"projected {research.backfill()} note(s) into the graph")
        args.graph = True

    if args.graph:
        counts = graph.counts()
        edges = counts.pop("_edges", 0)
        if not counts:
            console.info("The knowledge graph is empty. Research something first.")
            return EXIT_OK
        console.line("🕸️", f"{sum(counts.values())} entities · {edges} edges")
        with console.nest():
            for type_, n in sorted(counts.items()):
                console.line("•", f"{type_:<10} {n}")
        return EXIT_OK

    if args.link or args.unlink:
        src, kind, dst = args.link or args.unlink
        if args.link:
            store.assert_edge(src, kind, dst, by="operator")
            console.line("🔗", f"{src} —{kind}→ {dst}")
        else:
            store.retract_edge(src, kind, dst, by="operator")
            console.line("✂️", f"retracted {src} —{kind}→ {dst}")
        return EXIT_OK

    if args.list:
        rows = store.list()
        if not rows:
            console.info("No canvases yet.")
            return EXIT_OK
        console.line("🗂️", f"{len(rows)} canvas(es)")
        with console.nest():
            for row in rows:
                console.line("🕸️", f"{row['id']}  {row['nodes']:>3} nodes  {row['title']}")
        return EXIT_OK

    canvas_id = args.show
    if not canvas_id:
        query = " ".join(args.query).strip()
        if not query:
            console.warn(
                "Nothing to open. Give a query, or use --list, --show, --graph "
                "or --backfill."
            )
            return EXIT_CONFIG_ERROR
        canvas_id = store.open_for(
            query, created_by="operator", depth=max(0, args.depth)
        )

    view = store.view(canvas_id).to_dict()
    console.line("🕸️", f"{view['title']} — {len(view['nodes'])} nodes, {len(view['edges'])} edges")
    if not view["nodes"]:
        with console.nest():
            console.warn(
                "Nothing in the knowledge graph matched. The canvas exists and "
                "is empty, which is a different thing from a failed search."
            )
        return EXIT_OK
    with console.nest():
        for node in view["nodes"]:
            ref = f"  → {node['ref']}" if node["ref"] else ""
            console.line("•", f"[{node['type']}] {node['label'][:60]}{ref}")
        for edge in view["edges"]:
            console.line("↳", f"{edge['source']} —{edge['kind']}→ {edge['target']}")
    return EXIT_OK


def _cmd_research(config: Config, console: Console, args) -> int:  # noqa: ANN001
    """Run the research family by hand — the parity half of the Research page.

    Same agents, same directory, same audit line as a dispatched task. The only
    difference is that nobody had to guess what the operator meant, which is
    why this path is also the one to reach for when the router picks wrong.
    """
    from genesis.agents.research.fleet import build_fleet

    store_path = str(config.memory.db_path.parent / "research.db")

    # -- reading the directory. No gateway, no models, no cost. ------------
    if args.list or args.show:
        from genesis.research.store import ResearchStore

        store = ResearchStore(path=store_path, vault=None)
        if args.show:
            note = store.note(args.show)
            if note is None:
                console.warn(f"No research note {args.show!r}.")
                return EXIT_RUNTIME_ERROR
            print(note.markdown())
            return EXIT_OK
        notes = store.notes(limit=200)
        if not notes:
            console.info("The research directory is empty.")
            return EXIT_OK
        console.line("🗂️", f"{len(notes)} note(s)")
        with console.nest():
            for note in notes:
                marks = "".join(
                    [" ⚠️" if note.degraded else "", " ⏳" if note.stale() else ""]
                )
                console.line("📄", f"{note.id}  {note.kind:<7} {note.title}{marks}")
        return EXIT_OK

    subject = " ".join(args.subject).strip()
    if not subject and not (args.regime or args.ideas):
        console.warn(
            "Nothing to research. Give a subject, or use --regime, --ideas, "
            "--list or --show."
        )
        return EXIT_CONFIG_ERROR

    # A synopsis reads the directory and nothing else, so it needs no gateway
    # and must not pay to open one -- connecting every MCP server to summarise
    # six rows already on disk is the cost this task type exists to avoid.
    gateway = None if (args.no_tools or args.summarise) else _open_gateway(console)
    fleet = _build_research_fleet(config, console, gateway)

    if args.summarise:
        agent = fleet.topic_researcher
        task_args = {"subject": subject}
        kind = "research.summarise"
    elif args.regime:
        agent, task_args = fleet.market_analyst, {}
        kind = "research.regime"
    elif args.ideas:
        agent, task_args = fleet.idea_synthesizer, {}
        kind = "research.ideas"
    else:
        agent = fleet.topic_researcher
        task_args = {"subject": subject, "depth": "quick" if args.quick else "deep"}
        kind = "research.topic"

    if agent is None:
        console.warn(
            f"{kind} is unavailable here — see the warnings above for what is "
            "missing. Nothing was written."
        )
        return EXIT_RUNTIME_ERROR

    agent.start()
    try:
        result = agent.run_task(_HandTask(kind, task_args))
    finally:
        agent.stop()

    if result.status == "failed":
        console.warn(f"{agent.id}: {result.reason}")
        return EXIT_RUNTIME_ERROR

    console.line("🔍", result.spoken_summary or f"{agent.id} finished.")
    with console.nest():
        for wrote in result.wrote:
            console.line("💾", f"{wrote.get('layer')}: {wrote.get('path') or wrote.get('note')}")
        if result.degraded:
            # "Read the caveats on the note" is wrong advice when there is no
            # note — a run can be degraded precisely because it wrote nothing.
            console.warn(
                "Marked degraded — read the caveats on the note."
                if result.wrote
                else "Degraded, and nothing was written. The reason is above."
            )
    return EXIT_OK


@dataclass(frozen=True)
class _HandTask:
    """A task the human made, shaped exactly like one the bus would deliver.

    The agents take a task, not a pile of keyword arguments, so the hand-driven
    path and the dispatched path go through the identical code. Two entry
    points into one agent is how they drift.
    """

    type: str
    args: dict
    id: str = "hand"
    trace_id: str | None = None


def _cmd_chart(
    config: Config,
    console: Console,
    *,
    symbol: str,
    timeframe: str,
    bars: int,
    out: Path | None,
    consumer: str,
    no_fetch: bool,
) -> int:
    """Draw a marked-up chart from the store. Spec: Market Data Plane.md.

    The whole afferent path in one command: resolve the symbol, read the store,
    fill from the chain only if the store cannot answer, compute levels, compose
    a model-free spec, render. No LLM anywhere in it -- the default composition
    is deterministic, which is why this works with no API key and why the same
    bars always produce the same chart.
    """
    from genesis.charting.compose import compose_default
    from genesis.charting.levels import compute_levels
    from genesis.charting.render import render
    from genesis.charting.structure import read_structure
    from genesis.errors import GenesisError
    from genesis.marketdata.build import build_source
    from genesis.marketdata.source import resolve_symbol

    try:
        symbol_id = resolve_symbol(symbol)
    except GenesisError as exc:
        console.error(exc.reason)
        return EXIT_CONFIG_ERROR

    built = build_source(config, consumer, allow_fetch=not no_fetch)
    console.line("📈", f"{symbol_id} · {timeframe}")
    with console.nest():
        if built.used:
            console.line("🔌", f"chain: {' → '.join(built.used)}")
        for name, why in built.skipped:
            console.warn(f"{name} unavailable — {why}")
        if not built.used and not no_fetch:
            console.warn("no adapters available; answering from the store only")

    try:
        frame = built.source.fetch(symbol_id, timeframe, bars=bars)
    except GenesisError as exc:
        console.error(exc.reason)
        return EXIT_RUNTIME_ERROR
    finally:
        built.store.close()
        built.budget.close()

    computation = compute_levels(frame)
    read = read_structure(frame)
    spec = compose_default(frame, computation, read, created_by="cli")

    path = out or (
        Path(config.memory.vault_path).expanduser()
        / "20-Charts"
        / f"{symbol_id.replace(':', '_')}_{timeframe}.png"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    result = render(frame, spec, path=path)

    freshness = built.source.last_freshness
    with console.nest():
        console.line(
            "🕯️",
            f"{len(frame)} bars · {frame.first_time:%Y-%m-%d} → "
            f"{frame.last_time:%Y-%m-%d} · last {frame.last:,.2f}",
        )
        # Provenance and age, always. Safety Invariants §10 -- an unlabelled
        # stale price is a confabulation, and that applies to a chart exactly
        # as it applies to a spoken answer.
        console.line(
            "🔎",
            f"source {frame.source} · tier {frame.tier}"
            + (f" · {freshness.label}, {freshness.spoken('data')}" if freshness else ""),
        )
        console.line("📐", f"{len(spec.levels())} levels · {read.trend}")
        console.line("🖼️", str(path))
    return EXIT_OK


def _cmd_config_check(config: Config, console: Console) -> int:
    console.line("🧾", f"Config valid · {config.brokers.primary.kind} "
                       f"({config.brokers.primary.mode})")
    with console.nest():
        console.line("🛡️ ", f"Approval mode: {config.approval.mode}")
        console.line(
            "📉",
            f"Risk: max position {config.risk.max_position_pct}% · "
            f"heat {config.risk.max_portfolio_heat_pct}% · "
            f"daily loss {config.risk.max_daily_loss_pct}%",
        )
        console.line("🎯", f"Allowlist: {', '.join(config.risk.symbol_allowlist)}")
        console.line("🧠", f"Vault: {config.memory.vault_path}")

        secrets = load_secrets(Path("~/.genesis/.env"))
        present = secrets.present()
        if present:
            console.line("🔑", f"Secrets present: {', '.join(present)}")
        else:
            console.line("🔑", "Secrets present: none (see .env.example)")

        _probe_brain(config, secrets, console)

        # Two independent actions to go live -- never one flag.
        if config.is_live and "ALPACA_API_KEY" not in secrets:
            console.warn("broker mode is live but no broker key is present")
    return EXIT_OK


def _probe_brain(config: Config, secrets: Any, console: Console) -> None:
    """Ask each hosted tier for one token, because a tier that is configured is
    not a tier that works.

    Listing a key as present while every completion 400s is proprioceptive
    drift -- the check asserting an organ the system does not have, which is
    the failure Biological Design ranks with reconciliation. A key can be
    unfunded, unscoped, revoked, or pointed at a model the provider retired,
    and none of that is visible from the fact that a string is set.

    Built through :func:`_tier_backend` rather than against one provider, so
    this reports the truth about whichever profile is loaded -- and so a dev
    profile is checked by the same command as production.
    """
    for tier_name in ("small", "large"):
        tier = getattr(config.llm, tier_name)
        if tier.backend in ("none", "onnx-local") or not tier.model:
            console.line("\N{STETHOSCOPE}", f"{tier_name}: {tier.backend}, nothing to probe")
            continue

        backend = _tier_backend(config, console, tier_name)
        if backend is None:
            console.degraded(f"{tier_name} tier ({tier.backend}) would not build")
            continue
        try:
            # Short timeout: this is a health check, not a workload, and a hung
            # probe is a worse answer than a slow one.
            reply = backend.complete("Reply: ok", max_tokens=8)
        except (DegradedError, FatalError) as exc:
            console.degraded(f"{tier_name} offline ({tier.model}): {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - a probe never fails the command
            console.degraded(f"{tier_name} unreachable ({tier.model}): {exc}")
            continue
        console.line(
            "\N{STETHOSCOPE}",
            f"{tier_name} live: {tier.backend}/{reply.model} in {reply.latency_ms:.0f} ms"
            f" ({reply.total_tokens} tokens)",
        )


def _cmd_mcp(console: Console, subcommand: str, agent: str | None) -> int:
    """Connect to every enabled server and say what actually happened.

    This is the proprioception for the tool layer: a system that can call tools
    but cannot report which ones it has is the configuration Biological Design
    warns about, and "why did that not work" should be answerable in one
    command rather than by reading a log.
    """
    from genesis.mcp.build import build_gateway

    build = build_gateway()
    try:
        registry = build.gateway.registry

        if subcommand == "tools":
            if agent:
                granted = build.gateway.tools_for(agent)
                console.line("🔌", f"{agent} may reach {len(granted)} tools")
                with console.nest():
                    for tool_id in granted:
                        console.line("·", registry.get(tool_id).catalogue_line())
                if not granted:
                    console.warn(f"{agent} has no allow-list, or none of it registered")
                return EXIT_OK
            console.line("🔌", f"{len(registry)} tools registered")
            with console.nest():
                for line in registry.surface():
                    console.line("·", line)
            return EXIT_OK

        console.line("🔌", f"MCP gateway · {build.summary()}")
        with console.nest():
            for server in build.connected:
                tools = registry.by_server(server)
                console.line("✅", f"{server} — {len(tools)} tools")
            for server in build.empty:
                console.warn(
                    f"{server} — connected but registered 0 tools. Its tool "
                    f"names or package name are probably wrong; read its live "
                    f"tool list and fix default_servers.yaml"
                )
            for server, reason in build.failed.items():
                # A failure with an empty message is a real case — a server
                # that dies on start-up says nothing at all — and the report
                # that exists to explain failures must not be the thing that
                # crashes on one.
                first = next(iter(reason.splitlines()), "") or repr(reason)
                console.warn(f"{server} — {first}")
            if build.skipped:
                console.line("⏸️ ", f"disabled: {', '.join(build.skipped)}")

            # Rejections are the interesting half. A tool that is absent
            # because a rule refused it is a rule working, and the operator
            # should be able to see that rather than wonder.
            if registry.rejected:
                console.line("🚫", f"{len(registry.rejected)} tools refused")
                with console.nest():
                    for rejection in registry.rejected[:10]:
                        console.line("·", str(rejection))

            for agent_id in sorted(build.gateway._allow):
                console.line(
                    "🔑",
                    f"{agent_id}: {len(build.gateway.tools_for(agent_id))} tools",
                )
        return EXIT_OK
    finally:
        build.gateway.runtime.stop()


def _cmd_config_set_tier(console: Console, tier: str, backend: str, model: str) -> int:
    """The typed half of the settings panel's model picker (parity rule)."""
    try:
        change = set_tier(tier, backend, model)
    except ConfigError as exc:
        console.error(str(exc))
        return EXIT_CONFIG_ERROR
    if not change.changed:
        console.line("\N{ELECTRIC PLUG}", f"{tier} was already {backend}/{model}")
        return EXIT_OK
    console.ok(
        f"{tier}: {change.previous_backend}/{change.previous_model} -> "
        f"{change.backend}/{change.model}"
    )
    with console.nest():
        console.line("\N{MEMO}", f"written to {change.path}")
        # Never imply a running daemon picked this up. The fleets bound their
        # backends at construction.
        console.warn("takes effect when the daemon restarts")
    return EXIT_OK


def _cmd_config_usage(config: Config, console: Console) -> int:
    """What the tiers actually cost. The sense behind daily_token_budget."""
    from genesis.llm.usage import UsageLog

    log = UsageLog(config.memory.db_path)
    rows = log.by_tier()
    if not rows:
        console.line("\N{BAR CHART}", "no model calls recorded today")
        log.close()
        return EXIT_OK

    total = sum(r.total_tokens for r in rows)
    budget = config.llm.daily_token_budget
    console.line(
        "\N{BAR CHART}",
        f"{total:,} tokens today · {total / budget:.1%} of the {budget:,} budget",
    )
    with console.nest():
        for row in rows:
            cost = f"${row.cost_usd:.4f}" if row.cost_usd is not None else "local"
            failed = f" · {row.failures} failed" if row.failures else ""
            console.line(
                "\N{BULLET}",
                f"{row.tier:9} {row.backend}/{row.model} — {row.calls} calls, "
                f"{row.total_tokens:,} tokens, p50 {row.p50_latency_ms:.0f} ms, "
                f"{cost}{failed}",
            )
    log.close()
    return EXIT_OK


def _cmd_biology(console: Console) -> int:
    """The BIO module's parity twin: the same `organs()` the route serves."""
    from genesis.biology import organs

    mark = {"built": "●", "building": "◐", "spec": "○", "missing": "✕", "n/a": "·"}
    console.line("🧬", "Genesis — organ map, from Biological Design")
    with console.nest():
        for o in organs():
            console.line(mark[o["status"]], f"{o['organ']} — {o['genesis']}")
            with console.nest():
                if o["summary"]:
                    console.line("📝", o["summary"])
                for p in o["parts"]:
                    console.line(mark[p["status"]], f"{p['name']} ({p['status']})")
    return 0


def _cmd_universe(config: Config, console: Console, command: str | None) -> int:
    """What this desk may trade, and the one command that changes it.

    The allow-list is a safety control. Widening it is a decision, so it is a
    typed command with a visible result rather than a background refresh —
    and `show` reports the snapshot's age, because an index membership from
    three weeks ago permits companies that have since left it.
    """
    from genesis.marketdata import universe as uni

    if command == "refresh":
        try:
            resolved = uni.refresh(config)
        except Exception as exc:  # noqa: BLE001 - a vendor being down is not a crash
            console.error(f"could not refresh the universe: {exc}")
            console.info("the futures roots and the core ETFs still trade", "·")
            return 1
        console.ok(f"universe refreshed — {len(resolved.symbols)} symbols, as of {resolved.as_of}")
        return 0

    resolved = uni.load(config)
    console.line("🎯", f"Tradeable universe — {len(resolved.symbols)} symbols")
    with console.nest():
        console.line("·", f"futures roots: {', '.join(resolved.futures)}")
        console.line("·", f"ETFs: {len(resolved.etfs)}")
        console.line("·", f"equities: {len(resolved.equities)} (S&P 500)")
        if resolved.as_of:
            age = resolved.age_days
            console.line(
                "⚠️" if resolved.stale else "·",
                f"membership as of {resolved.as_of}"
                + (f" — {age:.0f} days old" if age is not None else "")
                + (", refresh it" if resolved.stale else ""),
            )
        if resolved.degraded:
            console.warn(resolved.degraded)
        if not config.risk.equity_universe:
            console.info("equity_universe is off — only the futures roots trade", "·")
    return 0


def _cmd_dna(console: Console, args: Any) -> int:
    """The `DNA` module's parity twin: one reading of the genome, five views.

    Operating Model §1: anything Genesis can do, a person can do by hand,
    through the same door. Every number here comes from `genesis.dna`, which is
    what the route serves the panel — so the panel cannot show a healthy body
    map while the terminal shows a drifting one.
    """
    from genesis import dna

    command = getattr(args, "dna_command", None) or "status"
    mark = {"built": "●", "building": "◐", "spec": "○", "": "·"}

    if command == "map":
        count, collisions = dna.write()
        console.ok(f"wrote the vault map — {count} notes")
        for name, notes in collisions.items():
            console.warn(f"`{name}` resolves two ways: " + ", ".join(n.rel for n in notes))
        return 1 if collisions else 0

    if command == "prompts":
        found = dna.inventory()
        console.line("🧬", "Genesis — the prompt half of the genome")
        with console.nest():
            for prompt in found:
                console.line("·", f"{prompt.est_tokens:>5} tok  {prompt.name}  {prompt.file}:{prompt.line}")
                with console.nest():
                    console.line(" ", prompt.opening)
            console.line("Σ", f"{sum(p.est_tokens for p in found)} tokens across {len(found)} prompts (estimated)")
        return 0

    genome = dna.load()

    if command == "show":
        note = genome.resolve(args.note)
        if note is None:
            console.error(f"no note named {args.note!r} — try `genesis dna status` for the sections")
            return 1
        console.line("🧬", f"{note.name} — {note.rel}")
        with console.nest():
            console.line(mark.get(note.status, "·"), f"status: {note.status or 'none (not a component)'}")
            for path in note.implemented_by:
                console.line("→", f"implemented_by: {path}")
            for path in genome.pointing_at(note):
                console.line("←", f"spec pointer in: {path}")
            if note.links:
                console.line("·", "links: " + ", ".join(note.links[:12]))
        return 0

    if command == "check":
        if args.fix:
            for rel in dna.repair(genome):
                console.ok(f"repaired {rel}")
            genome = dna.load()
        findings = dna.check(genome)
        if not findings:
            console.ok(f"the body map is honest — {len(genome.pointers)} notes have code pointing at them")
            return 0
        console.line("🧬", f"{len(findings)} note(s) drifting — the map may not lie")
        with console.nest():
            for finding in findings:
                console.line(finding.glyph, f"{finding.note} — {finding.detail}")
                with console.nest():
                    for path in finding.files:
                        console.line("+", path)
        return 1

    counts = genome.counts()
    findings = dna.check(genome)
    console.line("🧬", "Genesis — the genome: this vault and the prompts")
    with console.nest():
        console.line("●", f"{counts['built']} built")
        console.line("◐", f"{counts['building']} building")
        console.line("○", f"{counts['spec']} spec")
        console.line("·", f"{counts['none']} notes with no status (principles, indexes, prose)")
        prompts = dna.inventory()
        console.line("🧬", f"{len(prompts)} prompts, ~{sum(p.est_tokens for p in prompts)} tokens")
        if findings:
            console.warn(f"{len(findings)} drift finding(s) — run `genesis dna check`")
        else:
            console.ok("the body map is honest")
        for name, notes in genome.collisions().items():
            console.warn(f"`{name}` resolves two ways: " + ", ".join(n.rel for n in notes))
    return 0


def _cmd_account(config: Config, console: Console, *, reconcile: bool, as_json: bool) -> int:
    """The accountant, through the same door the dashboard uses.

    Operating Model §1: a capability reachable only from a React panel is not
    shipped. This opens the ledger read-only and talks to no broker unless one
    is already up, so it is safe to run while the daemon trades.
    """
    import json

    from genesis.agents.execution.accountant import Accountant
    from genesis.execution import order_manager
    from genesis.memory.ledger import TradeLedger

    manager = order_manager.current()
    if manager is not None and manager.accountant is not None:
        accountant = manager.accountant
        call = manager.call
    else:
        ledger_path = Path(config.execution.state_dir).expanduser() / "ledger.db"
        if not ledger_path.exists():
            console.warn(f"no ledger at {ledger_path} — nothing has traded yet")
            return EXIT_OK
        # No broker: equity, marks and reconciliation are unavailable and the
        # snapshot says so rather than inventing them.
        accountant = Accountant(ledger=TradeLedger(ledger_path))
        call = lambda fn, *a: fn(*a)  # noqa: E731

    if reconcile:
        result = call(accountant.reconcile)
        if as_json:
            print(json.dumps(result, indent=2))
        elif result["matched"] is True:
            console.ok(result["detail"])
        elif result["matched"] is None:
            console.warn(result["detail"])
        else:
            console.error(f"RECONCILIATION MISMATCH — {result['detail']}")
        return EXIT_OK if result["matched"] is not False else EXIT_CONFIG_ERROR

    try:
        snap = call(accountant.snapshot)
    except ValueError as exc:  # several accounts in the ledger: surfaced, never picked
        console.error(str(exc))
        return EXIT_CONFIG_ERROR
    if as_json:
        print(json.dumps(snap.to_dict(), indent=2))
        return EXIT_OK

    equity = f"${snap.equity:,.2f}" if snap.equity is not None else "unknown (no broker)"
    console.line("\N{RECEIPT}", f"{snap.account} — equity {equity} · as of {snap.as_of}")
    with console.nest():
        if snap.portfolio_heat_pct is not None:
            console.line("\N{FIRE}", f"portfolio heat {snap.portfolio_heat_pct:.2f}% of equity")
        realized = f"{snap.realized_today:,.2f}"
        unreal = "unknown" if snap.unrealized is None else f"{snap.unrealized:,.2f}"
        console.line("\N{MONEY BAG}", f"today: realised {realized} · unrealised {unreal} "
                                       f"· fees {snap.fees_today:,.2f}")
        for pos in snap.positions:
            stop = f"stop {pos.stop}" if pos.stop is not None else "NO STOP"
            mark = "no mark" if pos.mark is None else f"mark {pos.mark}"
            console.line("\N{BULLET}", f"{pos.symbol} {pos.qty:+d} @ {pos.avg_entry} — {mark}, "
                                        f"{stop}, risk {pos.risk_open:,.2f}")
        if not snap.positions:
            console.line("\N{BULLET}", "flat")
        if snap.degraded:
            console.warn("degraded: " + "; ".join(snap.degraded_reasons))
        for problem in snap.problems:
            console.warn(problem)
        if snap.reconciled is False:
            console.error("the ledger and the broker do not agree")
    return EXIT_OK


def _cmd_idea(config: Config, console: Console, args: Any) -> int:
    """Your ideas, through the same function the agent and the route call."""
    from genesis.agents.research.session_plan import live_ideas, record_idea
    from genesis.errors import GenesisError
    from genesis.research.store import ResearchStore

    store = ResearchStore(path=config.memory.db_path.parent / "research.db",
                          vault=str(config.memory.vault_path))
    if args.idea_command == "list":
        rows = live_ideas(store)
        if not rows:
            console.line("\N{ELECTRIC LIGHT BULB}", "no live ideas on the desk")
            return EXIT_OK
        console.line("\N{ELECTRIC LIGHT BULB}", f"{len(rows)} live idea(s)")
        with console.nest():
            for _, i in rows:
                zone = f" {i.entry_zone[0]:g}–{i.entry_zone[1]:g}" if i.entry_zone else ""
                stop = f" wrong {i.stop_price:g}" if i.stop_price is not None else " NO STOP PRICE"
                who = "yours" if i.author == "human" else i.author
                console.line("\N{BULLET}", f"{i.direction} {i.symbol}{zone}{stop} · {who}")
        return EXIT_OK

    payload: dict[str, Any] = {
        "symbol": args.symbol, "direction": args.direction, "thesis": args.thesis,
        "stop_price": args.stop, "targets": args.target, "setup": args.setup,
        "timeframe": args.timeframe, "horizon_days": args.horizon, "confidence": args.confidence,
    }
    if args.entry:
        payload["entry_zone"] = args.entry
    if args.wrong_if:
        payload["invalidation"] = args.wrong_if
    if args.why:
        payload["invalidation_reason"] = args.why
    try:
        note = record_idea(store, payload)
    except GenesisError as exc:
        console.error(exc.reason)
        return EXIT_CONFIG_ERROR
    console.ok(f"Recorded: {note.summary}")
    if args.stop is None:
        console.warn("no --stop price: the plan will list this idea but cannot size it")
    return EXIT_OK


def _cmd_plan(config: Config, console: Console, *, save: bool, as_json: bool, port: int,
              config_path: Path | None = None) -> int:
    """The plan, through the running server when there is one.

    Only the server process holds the order manager, and the order manager is
    what sizes -- so a plan built in this process could not size anything.
    The same route the UI calls is the door; building locally is the fallback,
    and it says why its sizes are missing rather than showing none.
    """
    import json

    import httpx

    url = f"http://127.0.0.1:{port}/v1/plan"
    body: dict[str, Any] | None = None
    try:
        r = (httpx.post(url, json={}, timeout=60) if save else httpx.get(url, timeout=60))
        r.raise_for_status()
        body = r.json()
    except httpx.HTTPError:
        body = None

    if body is None:
        from genesis.agents.research.session_plan import SessionPlanAgent, default_inputs
        from genesis.research.store import ResearchStore

        inputs = default_inputs(config, config_path=config_path)
        inputs.size = lambda: None
        inputs.account = lambda: None
        inputs.size_off = (f"the server is not running on :{port}, so the gate could not "
                           f"size anything — `./genesis up`, then run this again")
        agent = SessionPlanAgent(
            ResearchStore(path=config.memory.db_path.parent / "research.db",
                          vault=str(config.memory.vault_path)),
            inputs=inputs,
        )
        plan, note = agent.build(save=save)
        body = {**plan.to_dict(), "brief": plan.brief(), "spoken": plan.spoken(),
                "vault_path": note.vault_path() if note else None}

    if as_json:
        print(json.dumps(body, indent=2, default=str))
        return EXIT_OK
    print(body["brief"])
    if body.get("vault_path"):
        console.ok(f"saved to {body['vault_path']}")
    return EXIT_OK


def _cmd_memory(config: Config, console: Console, args: Any) -> int:
    """The memory fabric by hand: stats, recall, consolidation, model install."""
    from genesis.memory.vectors import VectorStore, embedder_for

    def vectors() -> Any:
        return VectorStore(
            Path(config.memory.db_path).expanduser().parent / "vectors.db",
            embedder_for(config),
        )

    if args.memory_command == "install-embedder":
        return _install_embedder(config, console)

    if args.memory_command == "search":
        from genesis.errors import GenesisError

        namespaces = args.namespace or ["vault", "ideas", "lessons", "research"]
        store = vectors()
        try:
            hits = store.search(args.query, namespaces=namespaces, limit=args.limit)
        except GenesisError as exc:
            console.warn(exc.reason)
            return EXIT_CONFIG_ERROR
        if not hits:
            # Three different emptinesses, and "no results" for all three is a
            # lie by omission: an empty store and a missing model both look
            # like "nothing is similar to your query".
            empty = store.counts()["chunks"] == 0
            if empty and not embedder_for(config).available():
                console.warn("nothing is embedded and the model is not installed — "
                             "run `genesis memory install-embedder`, then "
                             "`genesis memory consolidate`")
                return EXIT_CONFIG_ERROR
            if empty:
                console.warn("the vector store is empty — run `genesis memory consolidate` "
                             "to embed the vault")
                return EXIT_OK
            console.line("\N{LEFT-POINTING MAGNIFYING GLASS}",
                         f"nothing like that in {', '.join(namespaces)}")
            return EXIT_OK
        console.line("\N{LEFT-POINTING MAGNIFYING GLASS}",
                     f"{len(hits)} result(s) in {', '.join(namespaces)}")
        with console.nest():
            for hit in hits:
                head = hit.text.replace("\n", " ")[:110]
                console.line("\N{BULLET}", f"{hit.score:.3f} [{hit.kind}] {hit.ref or ''} — {head}")
        return EXIT_OK

    if args.memory_command == "consolidate":
        report = _consolidator(config).run()
        icon = "\N{SLEEPING SYMBOL}" if report.ok else "\N{WARNING SIGN}"
        console.line(icon, f"consolidation {'complete' if report.ok else 'finished with skips'}")
        with console.nest():
            for result in report.passes:
                console.line("\N{BULLET}" if result.ok else "\N{CROSS MARK}",
                             f"{result.name}: {result.detail}")
        return EXIT_OK if report.ok else EXIT_CONFIG_ERROR

    if args.memory_command == "stats":
        from genesis.memory.episodic import EpisodicLog
        from genesis.memory.graph import KnowledgeGraph

        db = Path(config.memory.db_path).expanduser()
        console.line("\N{BRAIN}", f"memory fabric at {db.parent}")
        with console.nest():
            log = EpisodicLog(db)
            console.line("\N{BULLET}", f"episodic: {log.count():,} entries")
            log.close()
            graph = KnowledgeGraph(path=db.parent / "graph.db")
            console.line("\N{BULLET}", f"graph: {graph.counts()}")
            graph.close()
            try:
                console.line("\N{BULLET}", f"vectors: {vectors().counts()}")
            except Exception as exc:  # noqa: BLE001
                console.line("\N{BULLET}", f"vectors: unavailable — {exc}")
        return EXIT_OK

    return EXIT_OK


def _consolidator(config: Config) -> Any:
    """Build the nightly consolidator with whatever this machine has.

    One builder, shared by the CLI and the daemon, so "run it by hand" and
    "run it at 21:00" cannot drift into two different jobs.
    """
    from genesis.memory.consolidate import Consolidator
    from genesis.memory.episodic import EpisodicLog
    from genesis.memory.graph import KnowledgeGraph
    from genesis.memory.ledger import TradeLedger
    from genesis.memory.vectors import VectorStore, embedder_for

    db = Path(config.memory.db_path).expanduser()
    ledger_path = Path(config.execution.state_dir).expanduser() / "ledger.db"
    try:
        store = VectorStore(db.parent / "vectors.db", embedder_for(config))
    except Exception:  # noqa: BLE001 - no embedder is a skipped pass, not a failure
        store = None
    return Consolidator(
        episodic=EpisodicLog(db),
        graph=KnowledgeGraph(path=db.parent / "graph.db"),
        ledger=TradeLedger(ledger_path) if ledger_path.exists() else None,
        vectors=store,
        vault_path=Path(config.memory.vault_path).expanduser(),
    )


#: The embedding tier's model, from the source the note names. Pinned by repo
#: and filename rather than "latest": a different checkpoint under the same
#: name would silently invalidate every vector in the store.
EMBEDDER_FILES = {
    "bge-small-en-v1.5": {
        "model.onnx": "https://huggingface.co/BAAI/bge-small-en-v1.5/resolve/main/onnx/model.onnx",
        "tokenizer.json": "https://huggingface.co/BAAI/bge-small-en-v1.5/resolve/main/tokenizer.json",
    },
}


def _install_embedder(config: Config, console: Console) -> int:
    """Fetch the local embedding model. Once, deliberately, never on demand.

    Not downloaded lazily on first use: a 130 MB fetch triggered by a search
    is a search that appears to hang, and a daemon that reaches for the
    network at 04:00 because a consolidation pass wanted a vector is worse.
    """
    import httpx

    from genesis.memory.vectors import embedder_for

    embedder = embedder_for(config)
    files = EMBEDDER_FILES.get(embedder.model)
    if files is None:
        console.error(f"no download is recorded for embedding model {embedder.model!r} — "
                      f"known: {', '.join(EMBEDDER_FILES)}")
        return EXIT_CONFIG_ERROR
    if embedder.available():
        console.ok(f"{embedder.model} is already installed at {embedder.dir}")
        return EXIT_OK

    embedder.dir.mkdir(parents=True, exist_ok=True)
    console.line("\N{INBOX TRAY}", f"fetching {embedder.model} into {embedder.dir}")
    with console.nest():
        for name, url in files.items():
            target = embedder.dir / name
            if target.exists():
                console.line("\N{BULLET}", f"{name} already there")
                continue
            # A partial file that looks installed is worse than none: the ONNX
            # session would fail with a protobuf error nobody can read.
            part = target.with_suffix(target.suffix + ".part")
            try:
                with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
                    r.raise_for_status()
                    with part.open("wb") as fh:
                        for block in r.iter_bytes(1 << 16):
                            fh.write(block)
            except Exception as exc:  # noqa: BLE001
                part.unlink(missing_ok=True)
                console.error(f"{name} failed: {exc}")
                return EXIT_CONFIG_ERROR
            part.rename(target)
            console.line("\N{BULLET}", f"{name} — {target.stat().st_size / 1e6:.1f} MB")
    console.ok(f"{embedder.model} installed. `genesis memory search \"...\"` works now.")
    return EXIT_OK


def _cmd_config_show(config: Config, console: Console) -> int:
    import json

    from genesis.observability import _json_default

    print(json.dumps(config.model_dump(mode="python"), indent=2, default=_json_default))
    return EXIT_OK


def _cmd_config_init(path: Path, force: bool, console: Console) -> int:
    target = path.expanduser()
    if target.exists() and not force:
        console.warn(f"{target} already exists — pass --force to overwrite")
        return EXIT_CONFIG_ERROR
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(default_config_text(), encoding="utf-8")
    console.ok(f"Wrote default config to {target}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    console = Console()

    if args.command is None:
        parser.print_help()
        return EXIT_OK

    if args.command == "config" and args.config_command == "init":
        return _cmd_config_init(args.config, args.force, console)

    # Everything else needs a valid config. Fail closed and name the key.
    try:
        config = load_config(args.config)
        # Secrets into the environment, once, before any command runs.
        #
        # Providers read os.environ directly (DATABENTO_API_KEY,
        # SEC_EDGAR_USER_AGENT), so without this they report themselves
        # unavailable while the key sits in ~/.genesis/.env -- a failure that
        # looks exactly like a missing key and is not one. Only names in
        # SECRET_ENV_VARS are read, and the real environment still wins.
        load_secrets(Path("~/.genesis/.env"))
    except ConfigError as exc:
        console.error("Refusing to start — configuration is invalid.")
        with console.nest():
            for line in str(exc).splitlines():
                print(f"  {line}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    if args.command == "daemon":
        return _cmd_daemon(config, console, tick=args.tick, once=args.once)

    if args.command == "mcp":
        return _cmd_mcp(console, args.mcp_command, getattr(args, "agent", None))

    if args.command == "serve":
        from genesis.server.app import serve

        from genesis.server.fleet import FLEET_STATE

        console.line("🌐", f"Genesis UI server on http://{args.host}:{args.port}")
        with console.nest():
            console.line("🔌", "ws /v1/events · post /v1/command · post /v1/voice/utterance")
            # This line used to read "idle until asked — no autonomous loop"
            # unconditionally, which was false in the default case and is how a
            # dead fleet reads as normal operation to anyone scanning the log.
            console.line(
                "😴" if args.no_daemon else "🫀",
                "idle until asked — no autonomous loop" if args.no_daemon
                else "the fleet and its cadences are starting behind this server",
            )
        if args.no_daemon:
            FLEET_STATE.set("disabled", detail="started with --no-daemon")
        stop = None if args.no_daemon else _warm_fleet(config, console)
        if args.no_daemon:
            console.warn(
                "No daemon here — typed commands answer from the reasoner only, "
                "and planned tasks queue until `genesis daemon` runs."
            )
        try:
            serve(host=args.host, port=args.port)
        finally:
            if stop is not None:
                stop()
        return EXIT_OK

    if args.command == "killswitch":
        return _cmd_killswitch(config, console, args)

    if args.command == "company":
        return _cmd_company(
            console,
            symbol=args.symbol,
            refresh=args.refresh,
            use_edgar=not args.no_edgar,
            as_json=args.json,
            one_field=args.field,
        )

    if args.command == "ibkr":
        return _cmd_ibkr(config, console, args)

    if args.command == "chart":
        return _cmd_chart(
            config,
            console,
            symbol=args.symbol,
            timeframe=args.timeframe,
            bars=args.bars,
            out=args.out,
            consumer=args.consumer,
            no_fetch=args.no_fetch,
        )

    if args.command == "research":
        return _cmd_research(config, console, args)

    if args.command == "canvas":
        return _cmd_canvas(config, console, args)

    if args.command == "voice":
        return _cmd_voice(
            config,
            console,
            silent=args.silent,
            wake_model=args.wake_model,
            say=args.say,
            no_daemon=args.no_daemon,
            no_tools=args.no_tools,
        )

    if args.command == "account":
        return _cmd_account(config, console, reconcile=args.reconcile, as_json=args.json)

    if args.command == "biology":
        return _cmd_biology(console)

    if args.command == "dna":
        return _cmd_dna(console, args)

    if args.command == "universe":
        return _cmd_universe(config, console, getattr(args, "universe_command", None))

    if args.command == "memory":
        return _cmd_memory(config, console, args)

    if args.command == "idea":
        return _cmd_idea(config, console, args)

    if args.command == "plan":
        return _cmd_plan(config, console, save=not args.no_save, as_json=args.json, port=args.port,
                         config_path=args.config)

    if args.command == "config":
        if args.config_command == "check":
            return _cmd_config_check(config, console)
        if args.config_command == "set-tier":
            return _cmd_config_set_tier(console, args.tier, args.backend, args.model)
        if args.config_command == "usage":
            return _cmd_config_usage(config, console)
        if args.config_command == "show":
            return _cmd_config_show(config, console)

    parser.print_help()
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
