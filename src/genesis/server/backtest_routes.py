# Spec: Genesis Markdown/20-Agents/Strategy/Agent — Backtest Runner.md · 60-UI/UI Stack.md §7
"""The backtest surface: run one, list them, open one.

Separate from ``reads.py`` because ``POST /v1/backtest/run`` **acts** — it
consumes CPU, it writes a durable row, and it answers. That is the efferent
shape the UI note describes for commands, and mixing it into the read module
would blur the one distinction that file exists to keep sharp.

It still cannot reach an order path. A backtest is a simulation against stored
bars; there is no broker, no venue but the simulated one, and no code path from
here to `place_approved`. `Safety Invariants` #1 is not weakened by anything in
this file, and the reason it is worth saying is that a "run strategy" button is
exactly the shape that eventually grows one.

**The run is synchronous and bounded.** It executes in a worker thread, because
``BacktestEngine`` is a blocking Rust object and running it on the event loop
would freeze every other client for its duration. It is not a background job
with a polling endpoint: a run over a few thousand bars finishes in tens of
milliseconds, and a job queue would be more machinery than the problem has.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

__all__ = ["backtest_routes"]

#: How many bars one request may simulate. A guard against a request that would
#: hold a worker thread for minutes, not a statement about what the engine can
#: do — Nautilus handles far more, from a job that is not an HTTP request.
MAX_BARS = 50_000


def backtest_routes(bus: Any = None) -> list[Any]:
    """Routes for running and reading backtests.

    ``bus`` is the event bus, so a run narrates itself onto the socket the same
    way a voice command does. A backtest that takes a second should make the
    fleet graph move; silence would read as a hung UI.
    """
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def templates(request: Request) -> JSONResponse:
        """The named strategy shapes a person can ask for by name.

        This is what makes *"create a MACD crossover strategy"* resolvable
        without a model writing code: the phrase maps to a template here, and
        the template produces a validated spec. The UI renders these as the
        strategy picker.
        """
        from genesis.backtest.strategy import TEMPLATES

        return JSONResponse({
            "available": True,
            "templates": [
                {
                    "id": name,
                    "label": _label(name),
                    "params": _params(name),
                }
                for name in sorted(set(TEMPLATES))
            ],
        })

    async def run_backtest(request: Request) -> JSONResponse:
        """Run one strategy over stored bars.

        Accepts either a ``template`` plus parameters, or a complete ``spec``.
        The template path is what voice and the strategy picker use; the spec
        path is what the editor uses once someone has tuned one.
        """
        from genesis.backtest.runner import (
            BacktestUnavailable, InsufficientData, run_spec,
        )
        from genesis.backtest.strategy import TEMPLATES, StrategySpec

        body = await request.json()
        symbol = str(body.get("symbol") or body.get("symbol_id") or "").strip()
        timeframe = str(body.get("timeframe") or "1D")

        # -- build the spec ------------------------------------------------
        try:
            if body.get("spec"):
                spec = StrategySpec.model_validate(body["spec"])
            else:
                template = str(body.get("template") or "").lower()
                if template not in TEMPLATES:
                    return JSONResponse(
                        {"ok": False, "error": f"unknown template {template!r}",
                         "templates": sorted(set(TEMPLATES))},
                        status_code=400,
                    )
                if not symbol:
                    return JSONResponse(
                        {"ok": False, "error": "symbol required"}, status_code=400
                    )
                resolved = await _resolve_symbol(symbol, timeframe)
                if resolved is None:
                    return JSONResponse(
                        {"ok": False,
                         "error": f"no bars held for {symbol} {timeframe}"},
                        status_code=404,
                    )
                params = {k: v for k, v in (body.get("params") or {}).items()}
                spec = TEMPLATES[template](resolved, timeframe=timeframe, **params)
        except Exception as exc:  # noqa: BLE001
            # A rejected spec is a 400 with the validator's own message. The
            # closed vocabulary is only useful if the rejection says which word
            # was not in it.
            return JSONResponse(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, status_code=400
            )

        # -- load bars -----------------------------------------------------
        loop = asyncio.get_running_loop()
        try:
            bars = await loop.run_in_executor(None, _load_bars, spec.symbol_id, spec.timeframe)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"ok": False, "error": f"bar store unavailable: {exc}"}, status_code=503
            )
        if not bars:
            return JSONResponse(
                {"ok": False,
                 "error": f"no bars held for {spec.symbol_id} {spec.timeframe}"},
                status_code=404,
            )
        if len(bars) > MAX_BARS:
            return JSONResponse(
                {"ok": False,
                 "error": f"{len(bars)} bars exceeds the {MAX_BARS} per-request limit"},
                status_code=413,
            )

        trace = None
        if bus is not None:
            trace = bus.emit(
                "backtest.started",
                data={"symbol_id": spec.symbol_id, "strategy": spec.name,
                      "bars": len(bars)},
                priority="normal",
            )["trace_id"]

        # -- run -----------------------------------------------------------
        try:
            run = await loop.run_in_executor(None, run_spec, spec, bars)
        except InsufficientData as exc:
            if bus is not None:
                bus.emit("backtest.rejected", data={"reason": str(exc)},
                         trace=trace, priority="normal")
            # 422, not 500: the request was well-formed and the engine
            # correctly refused it. That distinction is the difference between
            # "you asked for something impossible" and "we are broken".
            return JSONResponse({"ok": False, "error": str(exc),
                                 "kind": "insufficient_data"}, status_code=422)
        except BacktestUnavailable as exc:
            return JSONResponse({"ok": False, "error": str(exc),
                                 "kind": "engine_missing"}, status_code=503)
        except Exception as exc:  # noqa: BLE001
            log.exception("backtest failed")
            return JSONResponse(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, status_code=500
            )

        # -- persist -------------------------------------------------------
        prompt = body.get("prompt")
        try:
            await loop.run_in_executor(None, _store_run, run, prompt)
        except Exception as exc:  # noqa: BLE001
            # A run that cannot be filed is still a valid run. Returned with a
            # warning rather than discarded -- throwing away a completed
            # simulation because the index is unwritable is the wrong trade.
            log.warning("could not store backtest run: %s", exc)
            run.warnings.append(f"this run was not saved: {exc}")

        payload = run.to_dict()
        if bus is not None:
            bus.emit(
                "backtest.completed",
                data={
                    "run_id": run.run_id, "symbol_id": spec.symbol_id,
                    "strategy": spec.name,
                    "positions": payload["meta"].get("total_positions", 0),
                    "wall_ms": payload["meta"].get("wall_ms"),
                },
                trace=trace, priority="normal", speak=True,
            )
        return JSONResponse({"ok": True, **payload})

    async def list_runs(request: Request) -> JSONResponse:
        from genesis.backtest.store import BacktestStore

        try:
            store = BacktestStore()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"available": False, "reason": str(exc)})
        try:
            symbol = request.query_params.get("symbol_id")
            limit = int(request.query_params.get("limit", 50))
            return JSONResponse({
                "available": True,
                "runs": [r.to_dict() for r in store.list(symbol_id=symbol, limit=limit)],
            })
        finally:
            store.close()

    async def get_run(request: Request) -> JSONResponse:
        from genesis.backtest.store import BacktestStore

        try:
            store = BacktestStore()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"available": False, "reason": str(exc)})
        try:
            body = store.get(request.path_params["run_id"])
            if body is None:
                return JSONResponse(
                    {"available": False, "reason": "no such run"}, status_code=404
                )
            return JSONResponse({"available": True, **body})
        finally:
            store.close()

    return [
        Route("/v1/backtest/templates", templates),
        Route("/v1/backtest/run", run_backtest, methods=["POST"]),
        Route("/v1/backtest/runs", list_runs),
        Route("/v1/backtest/runs/{run_id}", get_run),
    ]


# ---------------------------------------------------------------------------
# helpers — all blocking, all called through an executor
# ---------------------------------------------------------------------------

def _load_bars(symbol_id: str, timeframe: str) -> list[Any]:
    from genesis.marketdata.store import BarStore

    store = BarStore(read_only=True)
    try:
        return store.read(symbol_id, timeframe)
    finally:
        store.close()


async def _resolve_symbol(symbol: str, timeframe: str) -> str | None:
    """A bare ticker to a canonical symbol id, against what is actually held.

    Resolved rather than guessed. Constructing ``EQ:XNAS:{ticker}`` would
    produce an id that looks right and matches nothing, and the resulting
    "no bars" error would point at the data rather than at the guess.
    """
    if ":" in symbol:
        return symbol
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, _all_symbols)
    wanted = symbol.upper()
    for symbol_id, held_timeframe, _count in rows:
        parts = symbol_id.split(":")
        ticker = parts[2] if parts[0] == "FUT" and len(parts) >= 3 else parts[-1]
        if ticker.upper() == wanted and held_timeframe == timeframe:
            return symbol_id
    return None


def _all_symbols() -> list[tuple[str, str, int]]:
    from genesis.marketdata.store import BarStore

    store = BarStore(read_only=True)
    try:
        return store.symbols()
    finally:
        store.close()


def _store_run(run: Any, prompt: str | None) -> str:
    from genesis.backtest.store import BacktestStore

    store = BacktestStore()
    try:
        return store.put(run, prompt=prompt)
    finally:
        store.close()


_LABELS = {
    "macd": "MACD crossover",
    "ma": "Moving average crossover",
    "sma": "Moving average crossover",
    "golden-cross": "Golden cross (50/200)",
    "rsi": "RSI mean reversion",
    "breakout": "Donchian breakout",
}

_PARAMS: dict[str, list[dict[str, Any]]] = {
    "macd": [
        {"name": "fast", "type": "int", "default": 12, "min": 2, "max": 200},
        {"name": "slow", "type": "int", "default": 26, "min": 3, "max": 400},
        {"name": "signal", "type": "int", "default": 9, "min": 2, "max": 100},
    ],
    "ma": [
        {"name": "fast", "type": "int", "default": 50, "min": 2, "max": 400},
        {"name": "slow", "type": "int", "default": 200, "min": 3, "max": 800},
    ],
    "rsi": [
        {"name": "period", "type": "int", "default": 14, "min": 2, "max": 100},
        {"name": "oversold", "type": "float", "default": 30, "min": 1, "max": 49},
        {"name": "overbought", "type": "float", "default": 70, "min": 51, "max": 99},
    ],
    "breakout": [
        {"name": "period", "type": "int", "default": 20, "min": 2, "max": 400},
        {"name": "exit_period", "type": "int", "default": 10, "min": 2, "max": 400},
    ],
}


def _label(name: str) -> str:
    return _LABELS.get(name, name)


def _params(name: str) -> list[dict[str, Any]]:
    return _PARAMS.get(name, _PARAMS.get("ma", []))
