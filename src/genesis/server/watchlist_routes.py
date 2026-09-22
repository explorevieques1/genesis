# Spec: Genesis Markdown/70-Schemas/Watchlist Store.md
"""The watchlist surface: the trader's own symbol lists, plus day-change quotes.

Kept apart from ``reads.py`` because most of this **acts** (Biological Design
§2). What acts here, and nothing else does: create a list, rename it, delete
it, add or remove a symbol, move a symbol between sections. Every one is a
single small fact rather than a whole-list PUT, so a person and Genesis editing
the same list do not clobber each other on save.

None of it touches an order path, and this module imports no execution code --
a watchlist edit follows the conversation-store pattern (the trader's own data,
theirs to change), not the pre-trade gate. See [[Conversation Store]].

``GET /v1/market/quotes`` is the one afferent route here. It lives beside the
writer that needs it because the watchlist is its only caller; it is a public
tier-3 feed and may not be cited as a number Genesis knows.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from genesis.errors import DegradedError, GenesisError

__all__ = ["watchlist_routes"]

log = logging.getLogger(__name__)


def _store():
    """Path from config, like every other store -- see ``reads._memory_db``.

    Created on demand rather than reported absent: an empty watchlist store is
    the normal first-run state, not evidence of a missing subsystem.
    """
    from genesis.config import load_config
    from genesis.watchlist.store import WatchlistStore

    memory = Path(load_config().memory.db_path).expanduser().parent
    return WatchlistStore(path=memory / "watchlists.db")


def watchlist_routes() -> list[Any]:
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    def _guard(fn):  # noqa: ANN001, ANN202
        async def wrapped(request: Request) -> Any:
            try:
                return JSONResponse(await fn(request))
            except GenesisError as exc:
                return JSONResponse(
                    {"ok": False, "available": False, "reason": exc.reason},
                    status_code=400,
                )
            except KeyError as exc:
                return JSONResponse(
                    {"ok": False, "available": False, "reason": str(exc)},
                    status_code=404,
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("watchlist route failed: %s", fn.__name__)
                return JSONResponse(
                    {"ok": False, "available": False,
                     "reason": f"{type(exc).__name__}: {exc}"},
                    status_code=500,
                )

        wrapped.__name__ = fn.__name__
        return wrapped

    # -- afferent ---------------------------------------------------------

    @_guard
    async def watchlists(request: Request) -> dict[str, Any]:
        return {"available": True, "watchlists": _store().lists()}

    @_guard
    async def quotes(request: Request) -> dict[str, Any]:
        """Day change for arbitrary tickers. Tier 3, public feed."""
        from genesis.marketdata.quotes import day_quotes

        raw = request.query_params.get("symbols", "")
        symbols = [s for s in (p.strip() for p in raw.split(",")) if s]
        return {
            "available": True,
            "tier": 3,
            "quotes": day_quotes(symbols) if symbols else {},
        }

    @_guard
    async def heatmap(request: Request) -> dict[str, Any]:
        """The Nasdaq-100 on the day, for the `HM` treemap. Tier 3."""
        from genesis.marketdata.heatmap import nasdaq_100_heatmap

        payload = nasdaq_100_heatmap()
        if "error" in payload:
            raise DegradedError(payload["error"])
        return {"available": True, "tier": 3, **payload}

    @_guard
    async def performance(request: Request) -> dict[str, Any]:
        """Sector or futures performance over four windows, for `PFM`. Tier 3."""
        from genesis.marketdata.performance import performance as compute

        payload = compute(request.query_params.get("asset", "stocks"))
        if "error" in payload:
            raise DegradedError(payload["error"])
        return {"available": True, "tier": 3, **payload}

    @_guard
    async def movers(request: Request) -> dict[str, Any]:
        """One index's members by weight and change, for `MOV`. Tier 3."""
        from genesis.marketdata.index_map import index_map

        payload = index_map(request.query_params.get("index", "SPX"))
        if "error" in payload:
            raise DegradedError(payload["error"])
        return {"available": True, "tier": 3, **payload}

    @_guard
    async def screener(request: Request) -> dict[str, Any]:
        """The current screen and the snapshot under it, for `SCR`. Tier 3.

        Read-only. A scan is run through `POST /v1/command` (`scr ...`) like
        every other door, so the panel and the chat share one path.
        """
        from genesis.screener.scan import STALE_HOURS
        from genesis.screener.snapshot import FIELDS, SECTORS, TEXT_FIELDS, load_current, load_snapshot

        snap = load_snapshot()
        age = snap.age_hours()
        return {
            "available": True,
            "tier": 3,
            "current": load_current(),
            "snapshot": {"as_of": snap.as_of, "rows": len(snap.rows), "failed": snap.failed,
                         "stale": age is None or age > STALE_HOURS},
            "fields": [{"name": n, "unit": u, "meaning": m} for n, (u, m, _) in FIELDS.items()],
            "text_fields": [{"name": n, "unit": "text", "meaning": m} for n, m in TEXT_FIELDS.items()],
            "sectors": list(SECTORS),
        }

    @_guard
    async def history(request: Request) -> dict[str, Any]:
        """Closes for the `CO` thumbnail chart. Tier 3, never the bar store."""
        from genesis.marketdata.quotes import price_history

        params = request.query_params
        payload = price_history(params.get("symbol", ""), params.get("window", "1Y"))
        if "error" in payload:
            raise DegradedError(payload["error"])
        return {"available": True, "tier": 3, **payload}

    # -- efferent -------------------------------------------------------

    @_guard
    async def create(request: Request) -> dict[str, Any]:
        body = await request.json()
        store = _store()
        store.create(str(body.get("name") or ""))
        return {"ok": True, "watchlists": store.lists()}

    @_guard
    async def rename(request: Request) -> dict[str, Any]:
        body = await request.json()
        store = _store()
        store.rename(request.path_params["list_id"], str(body.get("name") or ""))
        return {"ok": True, "watchlists": store.lists()}

    @_guard
    async def delete_list(request: Request) -> dict[str, Any]:
        store = _store()
        store.delete(request.path_params["list_id"])
        return {"ok": True, "watchlists": store.lists()}

    @_guard
    async def add_symbol(request: Request) -> dict[str, Any]:
        body = await request.json()
        store = _store()
        store.add(
            request.path_params["list_id"],
            str(body.get("symbol") or ""),
            str(body.get("group") or ""),
        )
        return {"ok": True, "watchlists": store.lists()}

    @_guard
    async def remove_symbol(request: Request) -> dict[str, Any]:
        body = await request.json()
        store = _store()
        store.remove(request.path_params["list_id"], str(body.get("symbol") or ""))
        return {"ok": True, "watchlists": store.lists()}

    @_guard
    async def group_symbol(request: Request) -> dict[str, Any]:
        body = await request.json()
        store = _store()
        store.set_group(
            request.path_params["list_id"],
            str(body.get("symbol") or ""),
            str(body.get("group") or ""),
        )
        return {"ok": True, "watchlists": store.lists()}

    return [
        Route("/v1/watchlists", watchlists),
        Route("/v1/market/quotes", quotes),
        Route("/v1/market/heatmap", heatmap),
        Route("/v1/market/performance", performance),
        Route("/v1/market/history", history),
        Route("/v1/market/movers", movers),
        Route("/v1/screener", screener),
        Route("/v1/watchlists/new", create, methods=["POST"]),
        Route("/v1/watchlists/{list_id}/rename", rename, methods=["POST"]),
        Route("/v1/watchlists/{list_id}/delete", delete_list, methods=["POST"]),
        Route("/v1/watchlists/{list_id}/add", add_symbol, methods=["POST"]),
        Route("/v1/watchlists/{list_id}/remove", remove_symbol, methods=["POST"]),
        Route("/v1/watchlists/{list_id}/group", group_symbol, methods=["POST"]),
    ]
