# Spec: Genesis Markdown/60-UI/Candle Ranges.md
"""The candle-range surface: capture a window of price, name it, keep it.

Kept out of ``reads.py`` because creating a range **acts** (Biological Design
§2) — it reaches a vendor and writes a database. Reading one does not, and is
served by the ordinary market routes under a ``CR:<id>`` symbol, so a range
draws in `CH` like anything else.

Nothing here touches an order path, and this module imports no execution code.
A range is the trader's own scrapbook — see :mod:`genesis.marketdata.ranges`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from genesis.errors import GenesisError

__all__ = ["range_routes", "range_store"]

log = logging.getLogger(__name__)


def range_store():
    """Path from config, like every other store — see ``reads._memory_db``."""
    from genesis.config import load_config
    from genesis.marketdata.ranges import RangeStore

    memory = Path(load_config().memory.db_path).expanduser().parent
    return RangeStore(path=memory / "ranges.db")


def range_routes() -> list[Any]:
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
            except Exception as exc:  # noqa: BLE001
                log.exception("range route failed: %s", fn.__name__)
                return JSONResponse(
                    {"ok": False, "available": False,
                     "reason": f"{type(exc).__name__}: {exc}"},
                    status_code=500,
                )

        wrapped.__name__ = fn.__name__
        return wrapped

    @_guard
    async def listing(request: Request) -> dict[str, Any]:
        return {"available": True, "ranges": range_store().list()}

    @_guard
    async def create(request: Request) -> dict[str, Any]:
        """Download and save one window. The only slow route here."""
        from genesis.marketdata.ranges import DEFAULT_TZ

        body = await request.json()
        store = range_store()
        rid = store.create(
            name=str(body.get("name") or ""),
            ticker=str(body.get("ticker") or ""),
            timeframe=str(body.get("timeframe") or "5m"),
            start=str(body.get("start") or ""),
            end=str(body.get("end") or ""),
            tz=str(body.get("tz") or DEFAULT_TZ),
        )
        return {"ok": True, "range_id": rid, "ranges": store.list()}

    @_guard
    async def rename(request: Request) -> dict[str, Any]:
        body = await request.json()
        store = range_store()
        store.rename(request.path_params["range_id"], str(body.get("name") or ""))
        return {"ok": True, "ranges": store.list()}

    @_guard
    async def delete(request: Request) -> dict[str, Any]:
        store = range_store()
        store.delete(request.path_params["range_id"])
        return {"ok": True, "ranges": store.list()}

    return [
        Route("/v1/market/ranges", listing),
        Route("/v1/market/ranges/new", create, methods=["POST"]),
        Route("/v1/market/ranges/{range_id}/rename", rename, methods=["POST"]),
        Route("/v1/market/ranges/{range_id}/delete", delete, methods=["POST"]),
    ]
