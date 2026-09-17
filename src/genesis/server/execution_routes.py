# Spec: Genesis Markdown/20-Agents/Execution/Execution Family.md · 60-UI/Dashboard.md §Order ticket
"""The order path over HTTP, for the trade panel. Efferent, and kept in its own
module so the writes stay countable.

There is no route that places an order without an approval. ``/propose``
returns one; ``/place`` spends it. ``/submit`` is the one-click path and does
both -- but only in ``auto-within-limits``, a mode loosened only by ``/mode``,
which only this dashboard surface calls. Voice and the orchestrator have no
route here at all.

Every route runs the order manager's work on its thread and waits; a refusal
comes back as 409 with the reason, because "the kill switch is engaged" is an
answer the trader must see, not a transport error.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

log = logging.getLogger(__name__)

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="exec-route")


def execution_routes() -> list[Any]:
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from genesis.errors import GenesisError
    from genesis.execution import order_manager

    def manager() -> Any:
        m = order_manager.current()
        if m is None:
            raise GenesisError("the order path is off — set `execution.enabled: true` in ~/.genesis/config.yaml "
                               "and restart `genesis serve`")
        return m

    async def run(fn: Any, *args: Any, status: int = 200) -> JSONResponse:
        try:
            result = await asyncio.get_running_loop().run_in_executor(_POOL, fn, *args)
        except GenesisError as exc:
            return JSONResponse({"ok": False, "reason": exc.reason}, 409)
        except TimeoutError:
            return JSONResponse({"ok": False, "reason": "the order manager did not answer in 30s — check state "
                                                        "before retrying; nothing is retried for you"}, 504)
        except Exception as exc:  # noqa: BLE001 — surface it, never swallow a failed order action
            log.exception("execution route failed")
            return JSONResponse({"ok": False, "reason": f"{type(exc).__name__}: {exc}"}, 500)
        return JSONResponse(result, status)

    async def body(request: Request) -> dict[str, Any]:
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise GenesisError("content-type must be application/json")
        data = await request.json()
        if not isinstance(data, dict):
            raise GenesisError("expected a JSON object")
        return data

    def acting(handler: Any) -> Any:
        async def route(request: Request) -> JSONResponse:
            try:
                data = await body(request)
                m = manager()
            except GenesisError as exc:
                return JSONResponse({"ok": False, "reason": exc.reason}, 409)
            return await handler(m, data)
        return route

    async def state(request: Request) -> JSONResponse:
        m = order_manager.current()
        if m is None:
            return JSONResponse({"available": False, "reason": "the order path is off — `execution.enabled: true` "
                                                               "in ~/.genesis/config.yaml, then restart the server"})
        return await run(m.snapshot)

    async def account(request: Request) -> JSONResponse:
        """The accountant's snapshot: positions, heat, P&L, staleness.

        Its own route rather than a key in ``/state`` because ``/state`` is
        polled every second and this rebuilds positions from the whole fill
        log. Afferent, and the only place the UI should read a position from --
        nothing computes its own.
        """
        m = order_manager.current()
        if m is None or m.accountant is None:
            return JSONResponse({"available": False, "reason": "the order path is off"})
        return await run(lambda: m.call(m.accountant.snapshot).to_dict())

    async def reconcile(request: Request) -> JSONResponse:
        """Ledger against broker, on demand. Parity with `genesis account --reconcile`.

        A POST, not a GET, because it records what it found in the ledger's
        reconciliation table -- it reads the world and writes an audit row, so
        it belongs on the efferent side of the door however harmless it looks.

        It compares; it does not halt. The order manager owns the halt flag and
        engages it on its own pass, so a person asking "are we in agreement?"
        cannot stop trading by asking.
        """
        m = order_manager.current()
        if m is None or m.accountant is None:
            return JSONResponse({"available": False, "reason": "the order path is off"})
        return await run(lambda: m.call(m.accountant.reconcile))

    async def quality(request: Request) -> JSONResponse:
        m = order_manager.current()
        if m is None:
            return JSONResponse({"available": False, "reason": "the order path is off"})
        return await run(m.quality_report, request.query_params.get("date"))

    return [
        Route("/v1/exec/state", state),
        Route("/v1/exec/account", account),
        Route("/v1/exec/reconcile", reconcile, methods=["POST"]),
        Route("/v1/exec/quality", quality),
        Route("/v1/exec/propose", acting(lambda m, d: run(m.propose, d)), methods=["POST"]),
        Route("/v1/exec/place", acting(lambda m, d: run(m.place, str(d.get("approval_id", "")),
                                                        d.get("confirmation"))), methods=["POST"]),
        Route("/v1/exec/submit", acting(lambda m, d: run(m.submit, d)), methods=["POST"]),
        Route("/v1/exec/modify", acting(lambda m, d: run(m.modify, str(d.get("ref", "")),
                                                         d.get("changes") or {})), methods=["POST"]),
        Route("/v1/exec/cancel", acting(lambda m, d: run(m.cancel, str(d.get("ref", "")))), methods=["POST"]),
        Route("/v1/exec/flatten", acting(lambda m, d: run(m.flatten, str(d.get("symbol_id", "")),
                                                          d.get("qty"))), methods=["POST"]),
        # The dashboard is the only caller of the three below, and says so.
        Route("/v1/exec/mode", acting(lambda m, d: run(m.set_mode, str(d.get("mode", "")), "dashboard")),
              methods=["POST"]),
        Route("/v1/exec/resume", acting(lambda m, d: run(m.resume, "dashboard", str(d.get("resolution", "")))),
              methods=["POST"]),
        Route("/v1/exec/adopt", acting(lambda m, d: run(m.adopt, "dashboard")), methods=["POST"]),
    ]
