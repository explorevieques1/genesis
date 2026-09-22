# Spec: Genesis Markdown/20-Agents/Research/Agent — Session Plan.md §Doors
"""Your ideas and the plan of action, over HTTP.

The same three functions the agent and ``genesis idea`` / ``genesis plan``
call -- :func:`record_idea`, :func:`live_ideas` and
:meth:`SessionPlanAgent.build` -- so the button, the command line and the
spoken sentence are one door (Operating Model §1).

Afferent first: listing ideas and *looking* at a plan write nothing. Then two
writes: recording an idea, and saving a plan's brief to the vault.

**No order path.** Every size in a plan is the gate's dry run, which mints no
approval, and a plan item's ticket is only a ticket -- acting on it is still
``/v1/exec/propose`` then ``/v1/exec/place``.
"""

from __future__ import annotations

import logging
from typing import Any

from genesis.errors import GenesisError

__all__ = ["plan_routes"]

log = logging.getLogger(__name__)


def plan_routes() -> list[Any]:
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    def open_agent() -> Any:
        from genesis.agents.research.session_plan import SessionPlanAgent, default_inputs
        from genesis.config import load_config
        from genesis.research.store import ResearchStore

        config = load_config()
        store = ResearchStore(
            path=config.memory.db_path.parent / "research.db",
            vault=str(config.memory.vault_path),
        )
        return SessionPlanAgent(store, inputs=default_inputs(config))

    def _guard(fn):  # noqa: ANN001, ANN202
        async def wrapped(request: Request) -> Any:
            try:
                return JSONResponse(await fn(request))
            except GenesisError as exc:
                return JSONResponse({"ok": False, "reason": exc.reason}, status_code=400)
            except Exception as exc:  # noqa: BLE001
                log.exception("plan route failed: %s", fn.__name__)
                return JSONResponse({"ok": False, "reason": f"{type(exc).__name__}: {exc}"},
                                    status_code=500)

        wrapped.__name__ = fn.__name__
        return wrapped

    async def body(request: Request) -> dict[str, Any]:
        # A JSON content type forces a CORS preflight, so another tab cannot
        # post an idea to this loopback server with a plain form.
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise GenesisError("content-type must be application/json")
        data = await request.json() if await request.body() else {}
        if not isinstance(data, dict):
            raise GenesisError("expected a JSON object")
        return data

    # -- afferent ---------------------------------------------------------

    @_guard
    async def ideas(request: Request) -> dict[str, Any]:
        from genesis.agents.research.session_plan import live_ideas

        agent = open_agent()
        rows = await run_in_threadpool(live_ideas, agent.store)
        return {"ok": True, "ideas": [
            {"id": note_id, **idea.model_dump(mode="json"), "rr": idea.rr} for note_id, idea in rows
        ]}

    @_guard
    async def trade_ideas(request: Request) -> dict[str, Any]:
        """Everything `TI` shows: ranked ideas with the gate's size, and what is watched.

        One route rather than three, because the merge is the interesting part
        and it belongs where the data is. The ideas come from the plan, which
        means the size beside each one is the **risk gate's own dry run** of
        that ticket -- not a second sizing implementation that agrees with the
        gate until the day it does not.

        Afferent, all of it. A dry run mints no approval and records nothing;
        acting on an idea is still `/v1/exec/propose` then `/v1/exec/place`.
        """
        from genesis.news.ideas import NEWS_AUTHOR

        agent = open_agent()
        plan, _ = await run_in_threadpool(lambda: agent.build(save=False))
        extra = await run_in_threadpool(_idea_extras, agent.store)

        items = []
        for item in plan.to_dict()["items"]:
            items.append({**item, **extra.get(item["idea_id"], {})})
        return {
            # `available`, not `ok`. Every read route in this server is
            # discriminated by it, and `useRead` treats a body without it as
            # *absent* — data `null`, which is how the panel crashed reading
            # `.actionable` off nothing. `ok` is the write routes' shape and is
            # kept only so the CLI's existing callers still read it.
            "available": True,
            "ok": True,
            "as_of": plan.as_of,
            "ideas": items,
            "watching": await run_in_threadpool(_watching, agent.store),
            "desk": list(plan.desk),
            "degraded": list(plan.degraded),
            "actionable": len(plan.actionable),
            "news_author": NEWS_AUTHOR,
        }

    @_guard
    async def look(request: Request) -> dict[str, Any]:
        """Build a plan and show it. Saves nothing -- looking is not writing."""
        agent = open_agent()
        plan, _ = await run_in_threadpool(lambda: agent.build(save=False))
        return {"ok": True, **plan.to_dict(), "brief": plan.brief(), "spoken": plan.spoken()}

    # -- efferent -------------------------------------------------------

    @_guard
    async def add_idea(request: Request) -> dict[str, Any]:
        from genesis.agents.research.session_plan import record_idea

        data = await body(request)
        agent = open_agent()
        note = await run_in_threadpool(record_idea, agent.store, data)
        return {"ok": True, "note_id": note.id, "summary": note.summary,
                "vault_path": note.vault_path(), "idea": note.data}

    @_guard
    async def save(request: Request) -> dict[str, Any]:
        """Build a plan and write its brief to the vault."""
        await body(request)
        agent = open_agent()
        plan, note = await run_in_threadpool(lambda: agent.build(save=True))
        return {"ok": True, **plan.to_dict(), "brief": plan.brief(), "spoken": plan.spoken(),
                "note_id": note.id if note else None,
                "vault_path": note.vault_path() if note else None}

    return [
        Route("/v1/trade-ideas", trade_ideas),
        Route("/v1/ideas", ideas),
        Route("/v1/ideas", add_idea, methods=["POST"]),
        Route("/v1/plan", look),
        Route("/v1/plan", save, methods=["POST"]),
    ]


def _idea_extras(store: Any) -> dict[str, dict[str, Any]]:
    """Per-idea detail the plan does not carry: where it came from.

    A news idea without its story is an assertion. The `TI` module shows the
    brief behind each one so the trader can read what the model read -- which
    is the difference between advice and an instruction from a stranger.
    """
    out: dict[str, dict[str, Any]] = {}
    for note in store.notes(kind="idea", limit=100):
        data = note.data or {}
        out[note.id] = {
            "created": note.created.isoformat() if hasattr(note.created, "isoformat") else str(note.created),
            "summary": note.summary,
            "brief_id": data.get("brief_id"),
            "brief_title": data.get("brief_title"),
            "symbols": data.get("symbols") or [],
            "conflicts_text": data.get("conflicts") or "",
            "evidence": list(data.get("evidence") or []),
            "stop_price": data.get("stop_price"),
            "entry_zone": data.get("entry_zone"),
            "targets": list(data.get("targets") or []),
            # The whole computation behind the prices: ATR, trend, the levels
            # it chose between and the one it placed the stop beyond. `TI`
            # shows it because an idea that cannot show its work is an
            # assertion, and this one came from a model reading the news.
            "chart_setup": data.get("chart_setup"),
            # How the symbol was found. An idea the brief wrote and one this
            # system extracted from its prose are different claims, and the
            # card must not present them as the same thing.
            "found_by": data.get("found_by"),
            "vault_path": note.vault_path() if hasattr(note, "vault_path") else None,
        }
    return out


def _watching(store: Any) -> list[dict[str, Any]]:
    """The brief's `watch` items: a reason to look, with no side.

    Kept apart from the ideas on purpose. They have no direction, so nothing
    can size one -- and a watch item shown in the same lane as a tradeable idea
    is how "something is happening here" becomes a position.
    """
    out: list[dict[str, Any]] = []
    for note in store.notes(kind="finding", limit=60):
        data = note.data or {}
        if data.get("bias") != "watch" or data.get("status", "active") != "active":
            continue
        out.append({
            "id": note.id,
            "symbol": data.get("symbol") or "",
            "symbols": data.get("symbols") or [],
            "idea": data.get("idea") or note.summary,
            "rationale": data.get("rationale") or "",
            "invalidation": data.get("invalidation") or "",
            "brief_id": data.get("brief_id"),
            "brief_title": data.get("brief_title"),
            "created": note.created.isoformat() if hasattr(note.created, "isoformat") else str(note.created),
        })
    return out
