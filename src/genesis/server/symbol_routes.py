# Spec: Genesis Markdown/10-Architecture/Charting Engine.md §Symbol search · 10-Architecture/Market Data Plane.md
"""The chart's symbol bar: search IBKR's contract directory, then load a series.

  GET  /v1/market/search?q=nvid   ->  IBKR ``reqMatchingSymbols`` (+ dated futures)
  POST /v1/market/load            ->  fill ``{symbol_id, timeframe}`` into the store

Search is afferent and cheap; load is a write to the bar store, so it is a POST
with a JSON content type, like every other write here. The by-hand door for
load is ``genesis chart <symbol> <timeframe>``, which runs the same
``StoreBarSource.fetch``. Streaming a contract live is not here: that is
``/v1/broker/feed``, the one door the IBKR session reads its series from.

**Deterministic, never a model.** "Nvidia" becomes ``EQ:XNAS:NVDA`` because IBKR's
directory said so, and every candidate is returned with its exchange and
description -- ambiguity is shown, not picked.

**All IBKR calls run on one worker thread.** An ``ib_async.IB`` is bound to the
event loop of the thread that connected it, and ``reqMatchingSymbols`` is paced
by IBKR at about one a second -- a single thread serves both constraints.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

#: IBKR secType -> our asset class. Options, warrants, bonds and CFDs have no
#: symbol id yet (Open Questions §13 territory), so they are left out rather
#: than offered and then refused on click.
SEC_TYPES = {"STK": "EQ", "FUT": "FUT", "IND": "IDX", "CASH": "FX", "CRYPTO": "CRYPTO"}

#: IBKR's primary exchange -> the MIC our equity ids use. The adapter maps the
#: other way; anything absent keeps IBKR's code and routes SMART.
_MICS = {"NASDAQ": "XNAS", "NYSE": "XNYS", "ARCA": "ARCA"}

#: Algo-routing destinations IBKR lists beside the real venue -- ESZ6 comes back
#: on CME *and* QBALGO. The same contract twice is noise in a picker.
_ROUTING_VENUES = {"QBALGO"}

#: Dated contracts listed per futures root: the front few are what anyone charts.
FUTURE_MONTHS = 6

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ibkr-search")
_CONN: Any = None
# ponytail: unbounded per-process cache; a day of typing is a few hundred keys.
_CACHE: dict[str, list[dict[str, Any]]] = {}


def symbol_id_for(sec_type: str, symbol: str, exchange: str, *, currency: str = "",
                  contract_month: str = "") -> str | None:
    """One IBKR contract -> a canonical symbol id, or ``None`` if we have none."""
    from genesis.marketdata.normalize import instrument_id

    kind = SEC_TYPES.get(sec_type)
    if kind is None or not symbol:
        return None
    if kind == "FUT":
        month = contract_month[:6]
        if len(month) != 6 or not exchange:
            return None  # a root without a month is a family, not an instrument
        return instrument_id("FUT", exchange, symbol, contract_month=f"{month[:4]}-{month[4:]}")
    if kind == "FX":
        return instrument_id("FX", "IDEALPRO", f"{symbol}{currency}")
    if kind == "CRYPTO":
        return instrument_id("CRYPTO", exchange or "PAXOS", symbol)
    if not exchange:
        return None
    return instrument_id(kind, _MICS.get(exchange, exchange), symbol)


def _ib() -> Any:
    """The search connection, (re)connected on this worker thread."""
    global _CONN
    from genesis.config import load_config
    from genesis.marketdata.adapters.ibkr import IbkrConnection

    spec = load_config().marketdata.adapters.get("ibkr")
    if spec is None or not spec.enabled:
        raise LookupError("the IBKR feed is off — turn it on in CON (Connections)")
    if _CONN is None or (_CONN.host, _CONN.port) != (spec.host or "127.0.0.1", spec.port or 4002):
        if _CONN is not None:
            _CONN.disconnect()
        _CONN = IbkrConnection(
            host=spec.host or "127.0.0.1", port=spec.port or 4002,
            # +3: the adapter holds +0, the live session +1, the check +2.
            client_id=(spec.client_id if spec.client_id is not None else 17) + 3,
            market_data_type=spec.market_data_type or "delayed",
            use_watchdog=False,
        )
    return _CONN.connect()


def search(query: str) -> list[dict[str, Any]]:
    """IBKR's matches for ``query``, each with a symbol id. Runs on the worker."""
    key = query.strip().upper()
    if key in _CACHE:
        return _CACHE[key]
    from ib_async import Future

    ib = _ib()
    out: list[dict[str, Any]] = []
    roots: list[tuple[str, str]] = []
    for desc in ib.reqMatchingSymbols(key) or []:
        c = desc.contract
        derived = list(desc.derivativeSecTypes or [])
        sid = symbol_id_for(c.secType, c.symbol, c.primaryExchange or c.exchange, currency=c.currency)
        if sid:
            out.append(_row(sid, c.symbol, c.secType, c.primaryExchange or c.exchange,
                            c.currency, c.description or "", derived))
        if (c.secType == "FUT" or "FUT" in derived) and (c.symbol, c.currency) not in roots:
            roots.append((c.symbol, c.currency))

    # A futures root is a family; list its dated contracts so there is something
    # to pick. Capped, because each root is a request against IBKR's pacing.
    today = datetime.now(UTC).strftime("%Y%m")
    for root, currency in roots[:3]:
        details = ib.reqContractDetails(Future(symbol=root, currency=currency)) or []
        months = sorted(
            (d for d in details if d.contract.lastTradeDateOrContractMonth[:6] >= today),
            key=lambda d: d.contract.lastTradeDateOrContractMonth,
        )
        seen: set[str] = set()
        for d in months:
            c = d.contract
            if c.exchange in _ROUTING_VENUES:
                continue
            sid = symbol_id_for("FUT", c.symbol, c.exchange,
                                contract_month=d.contractMonth or c.lastTradeDateOrContractMonth)
            if sid and sid not in seen:
                seen.add(sid)
                out.append(_row(sid, c.localSymbol or c.symbol, "FUT", c.exchange, c.currency,
                                d.longName or "", []))
            if len(seen) >= FUTURE_MONTHS:
                break

    if out:
        _CACHE[key] = out
    return out


def _row(sid: str, symbol: str, sec_type: str, exchange: str, currency: str,
         description: str, derived: list[str]) -> dict[str, Any]:
    return {"symbol_id": sid, "symbol": symbol, "sec_type": sec_type, "exchange": exchange,
            "currency": currency, "description": description, "derivatives": derived}


def load(symbol_id: str, timeframe: str) -> dict[str, Any]:
    """Fill one series into the store through the configured chain. On the worker,
    so it never races the search connection for IBKR's pacing."""
    from genesis.config import load_config
    from genesis.marketdata.build import build_source

    built = build_source(load_config(), "chart_markup")
    try:
        bars = built.source.fetch(symbol_id, timeframe)
        last = built.store.last_bar_time(symbol_id, timeframe)
        # `skipped` names the chain links that were left out and why, so a
        # yfinance answer to an "IBKR" load says why it was not IBKR.
        return {"ok": True, "symbol_id": symbol_id, "timeframe": timeframe, "bars": len(bars),
                "source": bars.source, "tier": bars.tier,
                "last_bar_at": last.isoformat() if last else None,
                "skipped": [{"adapter": n, "reason": r} for n, r in built.skipped]}
    finally:
        for adapter in built.source.adapters:
            if hasattr(adapter, "connection"):
                adapter.connection.disconnect()
        built.budget.close()


def symbol_routes() -> list[Any]:
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from genesis.charting.timeframes import resolve
    from genesis.errors import GenesisError
    from genesis.marketdata.source import resolve_symbol

    async def on_worker(fn: Any, *args: Any) -> Any:
        return await asyncio.get_running_loop().run_in_executor(_POOL, fn, *args)

    async def search_route(request: Request) -> JSONResponse:
        q = request.query_params.get("q", "").strip()
        if not q:
            return JSONResponse({"available": True, "results": []})
        try:
            return JSONResponse({"available": True, "results": await on_worker(search, q)})
        except LookupError as exc:
            return JSONResponse({"available": False, "reason": str(exc)})
        except GenesisError as exc:
            return JSONResponse({"available": False, "reason": exc.reason})
        except Exception as exc:  # noqa: BLE001 — a dead gateway is an answer, not a crash
            log.warning("symbol search %r failed: %s", q, exc)
            return JSONResponse({"available": False, "reason": f"{type(exc).__name__}: {exc}"})

    async def load_route(request: Request) -> JSONResponse:
        if not request.headers.get("content-type", "").startswith("application/json"):
            return JSONResponse({"ok": False, "reason": "content-type must be application/json"}, 415)
        data = await request.json()
        try:
            symbol_id = resolve_symbol(str(data.get("symbol_id", "")))
            timeframe = resolve(str(data.get("timeframe", "1D"))).label
            result = await on_worker(load, symbol_id, timeframe)
        except GenesisError as exc:
            return JSONResponse({"ok": False, "reason": exc.reason}, 400)
        except Exception as exc:  # noqa: BLE001 — a bad symbol is the operator's to fix
            return JSONResponse({"ok": False, "reason": f"{type(exc).__name__}: {exc}"}, 400)
        log.info("operator: loaded %s %s -> %s bars from %s", symbol_id, timeframe,
                 result["bars"], result["source"])
        return JSONResponse(result)

    return [
        Route("/v1/market/search", search_route),
        Route("/v1/market/load", load_route, methods=["POST"]),
    ]
