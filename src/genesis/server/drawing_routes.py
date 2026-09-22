# Spec: Genesis Markdown/60-UI/Chart Tools.md
"""The chart's own marks: what the trader drew, saved and read back.

Kept out of ``reads.py`` because saving a drawing **acts** (Biological Design
§2). It writes the trader's own file and imports no execution code; a
``trade_plan`` drawing carries no size, no account and no broker, which is the
schema's own guarantee — see :mod:`genesis.charting.drawings`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from genesis.errors import GenesisError

__all__ = ["drawing_routes", "drawing_store"]

log = logging.getLogger(__name__)


def drawing_store():
    """Path from config, like every other store — see ``reads._memory_db``."""
    from genesis.charting.drawings import DrawingStore
    from genesis.config import load_config

    memory = Path(load_config().memory.db_path).expanduser().parent
    return DrawingStore(path=memory / "drawings.db")


def drawing_routes() -> list[Any]:
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
                log.exception("drawing route failed: %s", fn.__name__)
                return JSONResponse(
                    {"ok": False, "available": False,
                     "reason": f"{type(exc).__name__}: {exc}"},
                    status_code=500,
                )

        wrapped.__name__ = fn.__name__
        return wrapped

    @_guard
    async def listing(request: Request) -> dict[str, Any]:
        series = request.query_params.get("series", "")
        return {"available": True, "series": series,
                "drawings": drawing_store().list(series)}

    @_guard
    async def save(request: Request) -> dict[str, Any]:
        body = await request.json()
        store = drawing_store()
        series = str(body.get("series") or "")
        payload = {
            k: v for k, v in body.items()
            if k not in ("series", "kind", "id", "created", "updated")
        }
        did = store.save(
            series, str(body.get("kind") or ""), payload,
            drawing_id=str(body.get("id") or ""),
        )
        return {"ok": True, "id": did, "drawings": store.list(series)}

    @_guard
    async def delete(request: Request) -> dict[str, Any]:
        body = await request.json()
        store = drawing_store()
        store.delete(request.path_params["drawing_id"])
        series = str(body.get("series") or "")
        return {"ok": True, "drawings": store.list(series)}

    @_guard
    async def clear(request: Request) -> dict[str, Any]:
        body = await request.json()
        store = drawing_store()
        series = str(body.get("series") or "")
        removed = store.clear(series)
        return {"ok": True, "removed": removed, "drawings": []}

    return [
        Route("/v1/charting/drawings", listing),
        Route("/v1/charting/drawings/save", save, methods=["POST"]),
        Route("/v1/charting/drawings/clear", clear, methods=["POST"]),
        Route("/v1/charting/drawings/{drawing_id}/delete", delete, methods=["POST"]),
    ]
