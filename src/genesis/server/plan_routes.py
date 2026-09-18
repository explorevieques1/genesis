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
        Route("/v1/ideas", ideas),
        Route("/v1/ideas", add_idea, methods=["POST"]),
        Route("/v1/plan", look),
        Route("/v1/plan", save, methods=["POST"]),
    ]
