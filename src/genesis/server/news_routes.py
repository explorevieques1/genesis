# Spec: Genesis Markdown/60-UI/News.md §Routes
"""The News module's surface: headlines, one article, briefs, collector status.

Afferent first, then three writes. Each write is also a workflow node and an
agent task, calling the same function (``news.collect.collect``,
``news_catalyst.summarise_article`` / ``write_brief``) -- Operating Model §1:
the button and the workflow go through one door.

No order path. This module imports no execution code; ``news.db`` holds text
and a model's reading of it, with no order, size or broker in its schema.
"""

from __future__ import annotations

import logging
from typing import Any

from genesis.errors import GenesisError

__all__ = ["news_routes"]

log = logging.getLogger(__name__)


def _large() -> tuple[Any, Any]:
    """Large and small tiers, built per call so a Settings change applies at once.

    A large tier that will not build says *why* -- "GEMINI_API_KEY is not set"
    is fixable, "no model" is a shrug.
    """
    from genesis.config import load_config
    from genesis.errors import DegradedError
    from genesis.llm.tiers import build_tier

    config = load_config()
    large = build_tier(config, "large")
    if large.backend is None:
        raise DegradedError(large.note or "no large-tier model is configured — set one in Settings → Model tiers")
    return large.backend, build_tier(config, "small").backend


def news_routes() -> list[Any]:
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from genesis.news import open_store

    def _guard(fn):  # noqa: ANN001, ANN202
        async def wrapped(request: Request) -> Any:
            try:
                return JSONResponse(await fn(request))
            except GenesisError as exc:
                return JSONResponse({"ok": False, "available": False, "reason": exc.reason}, status_code=400)
            except KeyError as exc:
                return JSONResponse({"ok": False, "available": False, "reason": str(exc)}, status_code=404)
            except Exception as exc:  # noqa: BLE001
                log.exception("news route failed: %s", fn.__name__)
                return JSONResponse(
                    {"ok": False, "available": False, "reason": f"{type(exc).__name__}: {exc}"}, status_code=500
                )

        wrapped.__name__ = fn.__name__
        return wrapped

    def _csv(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [s.strip() for s in str(value or "").replace(";", ",").split(",") if s.strip()]

    # -- afferent ---------------------------------------------------------

    @_guard
    async def headlines(request: Request) -> dict[str, Any]:
        q = request.query_params
        store = open_store()
        try:
            rows = store.list(
                hours=float(q["hours"]) if q.get("hours") else None,
                symbols=_csv(q.get("symbols")),
                query=q.get("q", ""),
                limit=min(int(q.get("limit", 200)), 500),
            )
        finally:
            store.close()
        return {"available": True, "tier": 4, "articles": rows}

    @_guard
    async def status(request: Request) -> dict[str, Any]:
        store = open_store()
        try:
            return {"available": True, "source": "yfinance", "tier": 4, **store.status()}
        finally:
            store.close()

    @_guard
    async def article(request: Request) -> dict[str, Any]:
        """One story with its text. The first open reads the page; after that it is cached."""
        from genesis.agents.research.news_catalyst import ensure_body

        store = open_store()
        try:
            row = store.get(request.path_params["article_id"])
            if row is None:
                raise KeyError(f"no article {request.path_params['article_id']}")
            if not row.get("body"):
                row["body"] = await run_in_threadpool(ensure_body, store, row)
            return {"available": True, "tier": 4, "article": row}
        finally:
            store.close()

    @_guard
    async def econ(request: Request) -> dict[str, Any]:
        """The red-folder calendar: what has not printed yet, soonest first.

        Tier 3 and it says so on the wire -- a vendor's schedule, not Genesis
        data. Defaults to high impact and the US because that is the desk;
        ``impacts`` and ``countries`` widen it, which is the parity rule (the
        panel's filters and anyone driving the API reach the same rows).
        """
        from genesis.news.econ import upcoming

        q = request.query_params
        store = open_store()
        try:
            events = await run_in_threadpool(
                lambda: upcoming(
                    store,
                    impacts=_csv(q.get("impacts")) or ("High",),
                    countries=_csv(q.get("countries")) or ("USD",),
                    limit=min(int(q.get("limit", 100)), 500),
                )
            )
            return {"available": True, "source": "forexfactory", "tier": 3,
                    "fetched_at": store.events_fetched_at(), "events": events}
        finally:
            store.close()

    @_guard
    async def briefs(request: Request) -> dict[str, Any]:
        store = open_store()
        try:
            return {"available": True, "briefs": store.briefs()}
        finally:
            store.close()

    @_guard
    async def brief(request: Request) -> dict[str, Any]:
        store = open_store()
        try:
            row = store.brief(request.path_params["brief_id"])
        finally:
            store.close()
        if row is None:
            raise KeyError(f"no brief {request.path_params['brief_id']}")
        return {"available": True, "brief": row}

    # -- efferent -------------------------------------------------------

    @_guard
    async def collect_now(request: Request) -> dict[str, Any]:
        from genesis.news.collect import collect

        body = await request.json() if await request.body() else {}
        store = open_store()
        try:
            symbols = _csv(body.get("symbols")) or None
            queries = _csv(body.get("queries")) or None
            return {"ok": True, **await run_in_threadpool(collect, store, symbols, queries)}
        finally:
            store.close()

    @_guard
    async def econ_refresh(request: Request) -> dict[str, Any]:
        """Pull the calendar now. The collector already does this on its own cadence."""
        from genesis.news.econ import refresh

        store = open_store()
        try:
            return {"ok": True, **await run_in_threadpool(refresh, store, force=True)}
        finally:
            store.close()

    @_guard
    async def summarise(request: Request) -> dict[str, Any]:
        from genesis.agents.research.news_catalyst import summarise_article

        large, _ = _large()
        store = open_store()
        try:
            analysis = await run_in_threadpool(
                summarise_article, store, large, request.path_params["article_id"]
            )
            return {"ok": True, "analysis": analysis}
        finally:
            store.close()

    @_guard
    async def brief_now(request: Request) -> dict[str, Any]:
        from genesis.agents.research.news_catalyst import write_brief

        body = await request.json() if await request.body() else {}
        large, small = _large()
        store = open_store()
        try:
            row = await run_in_threadpool(
                lambda: write_brief(
                    store, large, select_backend=small,
                    hours=float(body.get("hours") or 24), symbols=_csv(body.get("symbols")),
                    focus=str(body.get("focus") or ""), max_articles=int(body.get("max_articles") or 8),
                    title=str(body.get("title") or ""), refresh=bool(body.get("refresh", True)),
                )
            )
            return {"ok": True, "brief": row}
        finally:
            store.close()

    return [
        Route("/v1/news", headlines),
        Route("/v1/news/status", status),
        Route("/v1/news/econ", econ),
        Route("/v1/news/econ/refresh", econ_refresh, methods=["POST"]),
        Route("/v1/news/briefs", briefs),
        Route("/v1/news/briefs/{brief_id}", brief),
        Route("/v1/news/article/{article_id}", article),
        Route("/v1/news/collect", collect_now, methods=["POST"]),
        Route("/v1/news/article/{article_id}/summarise", summarise, methods=["POST"]),
        Route("/v1/news/brief", brief_now, methods=["POST"]),
    ]
