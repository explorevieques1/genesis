# Spec: Genesis Markdown/60-UI/UI Stack.md §7 Transport · §9 What the UI never does
"""Read routes: everything the surface is allowed to know.

The UI note is strict about the direction of this layer, and the strictness is
the whole point:

**Afferent only.** Every route here is a sensory nerve. Nothing in this module
mutates anything, reaches a broker, or touches an order path. Writes have their
own shape — HTTP POST, idempotency key, audit line — and they live in
``app.py`` where they can be counted. If you find yourself adding a POST here,
it belongs somewhere else.

**Money is a string, all the way to the pixel.** ``UI Stack §8``: *"Any number
the UI needs to compute is computed by an agent and sent."* A ``Decimal`` that
becomes a JSON number becomes an IEEE double in the browser, and 0.1 + 0.2
stops equalling 0.3 somewhere inside a position size. Every price, size and
P&L below is serialised with ``str()``. This looks like pedantry until the
first time a rounding error reaches a risk gauge.

**Absence is data.** A store that does not exist yet returns ``available:
false`` with a reason — never an empty list that reads as "nothing happened".
Those are different facts and the UI renders them differently, because
Biological Design's proprioception rule cuts both ways: a surface that cannot
tell "no trades" from "no journal" is a surface that will confidently describe
an organ the system does not have.

Everything is opened read-only where the driver supports it, and opened per
request rather than held. These stores are small, the surface is loopback, and
a long-lived handle to a SQLite file that the daemon also writes is a lock
contention bug waiting for the worst possible moment.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

__all__ = ["read_routes", "jsonable"]


# ---------------------------------------------------------------------------
# serialisation
# ---------------------------------------------------------------------------

def jsonable(value: Any) -> Any:
    """Recursively make ``value`` safe for ``JSONResponse``.

    ``Decimal`` becomes a **string**, never a float — see the module docstring.
    ``datetime`` becomes ISO-8601 with an explicit offset, because a naive
    timestamp rendered in a browser's local zone is a bug that only shows up
    for users who are not in UTC.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        # A float that got this far is a measurement (a ratio, a z-score), not
        # money -- money is Decimal by construction upstream. Passed through.
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in value]
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(value))
    if hasattr(value, "model_dump"):          # pydantic v2
        return jsonable(value.model_dump(mode="python"))
    if hasattr(value, "_asdict"):             # namedtuple
        return jsonable(value._asdict())
    return str(value)


def _ticker(symbol_id: str) -> str:
    """Display ticker from a canonical symbol id.

    ``EQ:XNAS:AAPL`` -> ``AAPL``, but ``FUT:CME:ES:2026-12`` -> ``ES``: taking
    the last segment gets the contract month for a future, which is not the
    instrument anyone means when they say "ES".
    """
    parts = symbol_id.split(":")
    if parts and parts[0] == "FUT" and len(parts) >= 3:
        return parts[2]
    return parts[-1] if parts else symbol_id


def _absent(reason: str, *, spec: str | None = None) -> dict[str, Any]:
    """The honest empty. Distinguishable from "queried, found nothing"."""
    body: dict[str, Any] = {"available": False, "reason": reason}
    if spec:
        body["spec"] = spec
    return body


def _guard(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Turn an exception into a reported absence rather than a 500.

    A page whose panel says *"journal unavailable: no such file"* is strictly
    more useful than one that shows a spinner forever, and it keeps a missing
    optional store from taking down the surfaces that do have data.
    """
    async def wrapped(request: Any) -> Any:
        from starlette.responses import JSONResponse

        try:
            return JSONResponse(jsonable(await fn(request)))
        except FileNotFoundError as exc:
            return JSONResponse(_absent(f"store not created yet: {exc}"))
        except Exception as exc:  # noqa: BLE001
            log.exception("read route failed: %s", fn.__name__)
            return JSONResponse(_absent(f"{type(exc).__name__}: {exc}"))

    wrapped.__name__ = fn.__name__
    return wrapped


# ---------------------------------------------------------------------------
# store openers — per request, read-only where possible
# ---------------------------------------------------------------------------

def _bars(read_only: bool = True):
    from genesis.marketdata.store import BarStore

    return BarStore(read_only=read_only)


def _journal():
    from genesis.journal.store import JournalStore

    path = Path("~/.genesis/memory/journal.db").expanduser()
    if not path.exists():
        raise FileNotFoundError(path)
    return JournalStore()


def _company():
    from genesis.company.store import CompanyStore

    return CompanyStore()


def _charting():
    from genesis.charting.store import SpecStore

    path = Path("~/.genesis/memory/charting.db").expanduser()
    if not path.exists():
        raise FileNotFoundError(path)
    return SpecStore()


def _config():
    from genesis.config import load

    return load()


# ---------------------------------------------------------------------------
# the routes
# ---------------------------------------------------------------------------

def read_routes() -> list[Any]:
    """Every afferent route, as Starlette ``Route`` objects."""
    from starlette.requests import Request
    from starlette.routing import Route

    # -- proprioception: what does this system actually have? --------------

    @_guard
    async def capabilities(request: Request) -> dict[str, Any]:
        """What is built, what is only specified, and how the UI should react.

        This is the single most important route in the file. The surface asks
        it on boot and lets the answer decide what to render, which is what
        makes "no dummy data" a structural property rather than a promise: a
        page cannot invent a backtest report if it has been told the backtest
        engine reports ``built: false``.

        Every probe is a real import or a real file check. Nothing here is a
        hand-maintained list of what someone believed was finished.
        """
        from genesis.server.capabilities import probe_all

        return {"available": True, **probe_all()}

    # -- market data -------------------------------------------------------

    @_guard
    async def market_symbols(request: Request) -> dict[str, Any]:
        """Everything the bar store holds, with freshness.

        The universe is whatever has actually been ingested. There is no
        configured watchlist masquerading as data — a symbol appears here
        because bars for it exist on this disk.
        """
        store = _bars()
        try:
            out = []
            for symbol_id, timeframe, count in store.symbols():
                last = store.last_bar_time(symbol_id, timeframe)
                out.append({
                    "symbol_id": symbol_id,
                    "symbol": _ticker(symbol_id),
                    "timeframe": timeframe,
                    "bars": count,
                    "last_bar_at": last,
                    "coverage": store.coverage(symbol_id, timeframe),
                })
            return {"available": True, "symbols": out}
        finally:
            store.close()

    @_guard
    async def market_bars(request: Request) -> dict[str, Any]:
        """OHLCV for one series, chronological, with provenance per bar.

        ``tier`` and ``source`` ride along on every bar rather than being
        summarised at the top, because a series assembled from two feeds is
        exactly the case where a single header lies. Lightweight Charts gets
        epoch seconds; the trust metadata stays beside it for the UI to shade.
        """
        q = request.query_params
        symbol_id = q.get("symbol_id") or q.get("symbol")
        timeframe = q.get("timeframe", "1D")
        if not symbol_id:
            return _absent("symbol_id required")
        limit = int(q.get("limit", 500))

        store = _bars()
        try:
            # A bare ticker is a convenience for the URL bar; resolve it
            # against what we hold rather than guessing an exchange prefix.
            if ":" not in symbol_id:
                match = next(
                    (s for s, tf, _ in store.symbols()
                     if _ticker(s).upper() == symbol_id.upper() and tf == timeframe),
                    None,
                )
                if match is None:
                    return _absent(f"no bars held for {symbol_id} {timeframe}")
                symbol_id = match

            bars = store.read(symbol_id, timeframe, limit=limit)
            return {
                "available": True,
                "symbol_id": symbol_id,
                "symbol": _ticker(symbol_id),
                "timeframe": timeframe,
                "count": len(bars),
                "bars": [
                    {
                        "time": int(b.ts.timestamp()),
                        "ts": b.ts,
                        # Strings. Lightweight Charts parses them; Decimal
                        # precision survives the trip. See module docstring.
                        "open": str(b.open), "high": str(b.high),
                        "low": str(b.low), "close": str(b.close),
                        "volume": str(b.volume),
                        "source": b.source, "tier": b.tier,
                        "adjusted": b.adjusted,
                    }
                    for b in bars
                ],
                "coverage": store.coverage(symbol_id, timeframe),
                "last_bar_at": store.last_bar_time(symbol_id, timeframe),
            }
        finally:
            store.close()

    # -- companies ---------------------------------------------------------

    @_guard
    async def company_list(request: Request) -> dict[str, Any]:
        store = _company()
        try:
            return {"available": True, "symbols": store.symbols()}
        finally:
            store.close()

    @_guard
    async def company_profile(request: Request) -> dict[str, Any]:
        """A cached profile. Never fetches — a read route must not do IO
        that costs money or rate limit; the `company` command does that."""
        from genesis.company.profile import summarise

        symbol = request.path_params["symbol"].upper()
        store = _company()
        try:
            profile = store.read(symbol)
            if profile is None:
                return _absent(f"{symbol} not in the local company store")
            return {
                "available": True,
                "symbol": symbol,
                "profile": summarise(profile),
                "fresh_groups": sorted(store.fresh_groups(symbol)),
            }
        finally:
            store.close()

    # -- journal -----------------------------------------------------------

    @_guard
    async def journal_entries(request: Request) -> dict[str, Any]:
        store = _journal()
        try:
            limit = int(request.query_params.get("limit", 200))
            entries = store.entries(limit=limit)
            return {
                "available": True,
                "counts": store.counts(),
                "entries": [jsonable(e) for e in entries],
            }
        finally:
            store.close()

    @_guard
    async def journal_lessons(request: Request) -> dict[str, Any]:
        store = _journal()
        try:
            status = request.query_params.get("status", "active")
            return {
                "available": True,
                "lessons": [jsonable(x) for x in store.lessons(status=status)],
                "hypotheses": [jsonable(x) for x in store.hypotheses()],
            }
        finally:
            store.close()

    @_guard
    async def journal_patterns(request: Request) -> dict[str, Any]:
        """Behavioural findings over the journal — real detectors, real data.

        ``detect_all`` is deterministic (`tier: none`): these are arithmetic
        over recorded entries, not a model's opinion about the trader.
        """
        from genesis.journal.patterns import detect_all

        store = _journal()
        try:
            entries = store.entries(limit=2000)
            if not entries:
                return {"available": True, "findings": [], "sample": 0,
                        "note": "no journal entries yet — nothing to detect"}
            findings = detect_all(entries)
            return {
                "available": True,
                "sample": len(entries),
                "findings": [f.to_dict() for f in findings],
            }
        finally:
            store.close()

    @_guard
    async def journal_graph(request: Request) -> dict[str, Any]:
        """The journal as a graph: entries, lessons, hypotheses and symbols.

        Built for the Obsidian-style force view. The edges are real
        relationships already recorded in the schema — a lesson's evidence
        points at the entries that support it, an entry points at its symbol —
        not a similarity score invented for the picture.
        """
        store = _journal()
        try:
            entries = store.entries(limit=1000)
            lessons = store.lessons(status="active")

            nodes: list[dict[str, Any]] = []
            edges: list[dict[str, Any]] = []
            symbols: dict[str, int] = {}

            for e in entries:
                data = jsonable(e)
                symbol = str(data.get("symbol") or "").upper()
                nodes.append({
                    "id": f"entry:{data.get('entry_id')}",
                    "kind": "entry",
                    "label": f"{symbol or '—'} {str(data.get('opened_at') or '')[:10]}",
                    "symbol": symbol or None,
                    "outcome": data.get("outcome"),
                    "r_multiple": data.get("r_multiple"),
                })
                if symbol:
                    symbols[symbol] = symbols.get(symbol, 0) + 1
                    edges.append({
                        "source": f"entry:{data.get('entry_id')}",
                        "target": f"symbol:{symbol}",
                        "kind": "symbol",
                    })

            for sym, n in symbols.items():
                nodes.append({"id": f"symbol:{sym}", "kind": "symbol",
                              "label": sym, "weight": n})

            for lesson in lessons:
                data = jsonable(lesson)
                lid = f"lesson:{data.get('lesson_id')}"
                nodes.append({
                    "id": lid, "kind": "lesson",
                    "label": str(data.get("claim") or data.get("key") or "lesson")[:70],
                    "confidence": data.get("confidence"),
                })
                # Evidence is a real field on the schema: the entries the
                # lesson was drawn from. This is the edge that makes the graph
                # worth looking at.
                for ref in (data.get("evidence") or {}).get("entry_ids", []) or []:
                    edges.append({"source": lid, "target": f"entry:{ref}",
                                  "kind": "evidence"})

            return {"available": True, "nodes": nodes, "edges": edges}
        finally:
            store.close()

    # -- charting ----------------------------------------------------------

    @_guard
    async def charting_specs(request: Request) -> dict[str, Any]:
        """Markup specs Genesis has drawn — its own charts, not price charts."""
        store = _charting()
        try:
            active = store.active()
            return {
                "available": True,
                "count": len(store),
                "active": [jsonable(s) for s in active],
            }
        finally:
            store.close()

    # -- the tool surface --------------------------------------------------

    @_guard
    async def mcp_servers(request: Request) -> dict[str, Any]:
        """Configured MCP servers, from the real config — not a hardcoded list.

        Reports configuration, not liveness. Probing every server on a page
        load would spawn a process per server; connection state belongs on the
        event stream, where it arrives when it changes.

        ``read_only`` is surfaced per server because it is a *claim the config
        makes*, and the settings page should show it as one. A server marked
        read-only registers in bulk; that is a decision worth being able to
        see.
        """
        from genesis.mcp.servers import load_servers

        servers = []
        for s in load_servers():
            servers.append({
                "id": s.id,
                "enabled": s.enabled,
                "transport": s.transport,
                "command": s.command,
                "url": s.url,
                "read_only": s.read_only,
                "trust": str(getattr(s.trust, "name", s.trust)).lower(),
                "tier": s.tier,
                "namespace": getattr(s, "namespace", None),
                "env_keys": list(s.env_keys),
                "tool_count": len(s.tools),
            })
        return {"available": True, "probed": False, "servers": servers}

    @_guard
    async def mcp_tools(request: Request) -> dict[str, Any]:
        """The declared tool surface, from config.

        Deliberately **not** ``build_gateway()``. That function spawns a
        subprocess per server and performs a real MCP handshake — correct at
        daemon start-up, catastrophic on a page load, and it would make a read
        route the most expensive thing in the system.

        So this reports what the catalogue *declares*, and says so. Live
        session state arrives on the event stream (``mcp.session_lost``) where
        it belongs: a fact that changes, pushed when it changes, rather than
        polled by a surface that must not poll.
        """
        from genesis.mcp.servers import load_servers

        tools: list[dict[str, Any]] = []
        for server in load_servers():
            for name, tool in server.tools.items():
                trust = tool.trust if tool.trust is not None else server.trust
                tools.append({
                    "id": f"{server.id}.{name}",
                    "server": server.id,
                    "name": name,
                    "capability": tool.capability or name,
                    # `None` means "believe the server's hint" -- a real third
                    # state, not a missing value, and the UI must show it as
                    # undeclared rather than assume either way.
                    "mutating": tool.mutating,
                    "trust": str(getattr(trust, "name", trust)).lower(),
                    "tier": tool.tier if tool.tier is not None else server.tier,
                    "timeout_sec": tool.timeout_sec,
                    "keywords": list(tool.keywords),
                    "enabled": server.enabled,
                })
        tools.sort(key=lambda t: (t["server"], t["name"]))
        return {
            "available": True,
            "probed": False,
            "note": "declared surface from config; sessions are not opened by a read",
            "count": len(tools),
            "tools": tools,
        }

    # -- the fleet ---------------------------------------------------------

    @_guard
    async def fleet_agents(request: Request) -> dict[str, Any]:
        """The agents that exist as code, discovered by import.

        Every agent module exposes a module-level ``DECLARATION``. Walking the
        packages and collecting them means this list cannot drift from the
        fleet: an agent appears here because its module imports, and vanishes
        the moment it does not.

        The alternative — a hand-kept roster in the front-end — is precisely
        the proprioceptive drift `Biological Design` §3 warns about, and the
        old ``ui/src/data/roster.ts`` was exactly that: 25 agents listed in
        TypeScript, of which 13 existed.
        """
        from genesis.server.fleet import discover_agents

        agents = discover_agents()
        families: dict[str, int] = {}
        for a in agents:
            families[a["family"]] = families.get(a["family"], 0) + 1
        return {"available": True, "count": len(agents),
                "families": families, "agents": agents}

    # -- configuration -----------------------------------------------------

    @_guard
    async def settings_config(request: Request) -> dict[str, Any]:
        """The effective config, with secrets structurally absent.

        Not redacted after the fact — ``Secrets`` is a separate object that is
        never serialised alongside behaviour (``config.py``), so there is
        nothing here to leak. What the UI gets is the shape it may edit and
        the values currently in force.
        """
        config = _config()
        body = jsonable(config)
        return {"available": True, "config": body}

    @_guard
    async def settings_audio(request: Request) -> dict[str, Any]:
        """Real input devices on this machine, for the microphone picker.

        Enumerated through sounddevice, which the voice stack already depends
        on. If it is not installed the picker says so rather than offering a
        list of plausible-sounding devices that do not exist.
        """
        try:
            import sounddevice as sd
        except Exception as exc:  # noqa: BLE001
            return _absent(f"sounddevice unavailable: {exc}")

        devices = []
        try:
            default_in = sd.default.device[0]
        except Exception:  # noqa: BLE001
            default_in = None
        for index, dev in enumerate(sd.query_devices()):
            if int(dev.get("max_input_channels", 0)) < 1:
                continue
            devices.append({
                "index": index,
                "name": dev.get("name"),
                "channels": dev.get("max_input_channels"),
                "sample_rate": dev.get("default_samplerate"),
                "default": index == default_in,
            })
        return {"available": True, "devices": devices}

    return [
        Route("/v1/capabilities", capabilities),
        Route("/v1/market/symbols", market_symbols),
        Route("/v1/market/bars", market_bars),
        Route("/v1/company", company_list),
        Route("/v1/company/{symbol}", company_profile),
        Route("/v1/journal/entries", journal_entries),
        Route("/v1/journal/lessons", journal_lessons),
        Route("/v1/journal/patterns", journal_patterns),
        Route("/v1/journal/graph", journal_graph),
        Route("/v1/charting/specs", charting_specs),
        Route("/v1/mcp/servers", mcp_servers),
        Route("/v1/mcp/tools", mcp_tools),
        Route("/v1/fleet/agents", fleet_agents),
        Route("/v1/settings/config", settings_config),
        Route("/v1/settings/audio", settings_audio),
    ]
