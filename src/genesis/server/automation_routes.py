# Spec: Genesis Markdown/60-UI/Automation.md
"""The workflow builder's surface: afferent reads, then the writes that act.

Every write appends a version (Automation.md Q1) and then asks the daemon in
this process, if there is one, to bring its roster in line on its own thread.
With no daemon here the save still stands and the reply says ``scheduled:
false`` -- a separate ``genesis daemon`` picks it up at its next boot.

No order path: this module imports no execution code, and the only thing a
workflow can call is what :mod:`genesis.automation.grant` permits.

Enabling is an operator act (Safety Invariants #9). A draft Genesis writes is
saved disabled, and ``/enable`` refuses any author but the operator.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from genesis.errors import DegradedError, GenesisError

__all__ = ["automation_routes"]

log = logging.getLogger(__name__)

AUTHORS = ("operator", "orchestrator")


def _schedule(workflow_id: str) -> bool:
    """Queue a roster sync on the daemon's thread. Returns whether one is attached."""
    from genesis.automation import attached, open_store
    from genesis.automation.runner import sync

    daemon, gateway = attached()
    if daemon is None:
        return False

    def apply() -> None:
        store = open_store()
        sync(daemon, store, workflow_id, gateway)

    daemon.call_soon(apply)
    return True


def _catalog() -> dict[str, Any]:
    """What the palette and inspector may offer. Built from code, not a list in the UI."""
    from genesis.automation import attached, open_store
    from genesis.automation.catalog import nodes
    from genesis.automation.grant import WORKFLOW_GRANT
    from genesis.automation.workflow import OPS, PREDICATES, REFRESH_TARGETS
    from genesis.server.fleet import discover_agents

    agents = [
        {"id": a["id"], "name": a.get("name"), "family": a.get("family")}
        for a in discover_agents()
        if a.get("built") and a.get("family") != "execution" and not a.get("workflow")
    ]
    # Which tools are live, when this process holds the gateway. Unknown is
    # reported as unknown (None), never as "all available".
    _daemon, gateway = attached()
    connected = set(gateway.registry.capabilities) if gateway is not None else None
    store = open_store()
    try:
        processes = [
            {"id": v.workflow_id, "name": (v.body or {}).get("name", v.workflow_id)}
            for v in store.list()
            if (v.body or {}).get("trigger", {}).get("type") == "on-demand"
        ]
    finally:
        store.close()
    return {
        "triggers": ["cron", "market-open", "market-closed", "event", "on-demand"],
        "steps": ["gather", "check", "refresh", "run", "action"],
        "grant": list(WORKFLOW_GRANT),
        "predicates": list(PREDICATES),
        "ops": list(OPS),
        "refresh_targets": list(REFRESH_TARGETS),
        "agents": agents,
        **nodes(connected=connected, processes=processes),
    }


def automation_routes() -> list[Any]:
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from genesis.automation import open_store
    from genesis.automation.workflow import Workflow

    def _guard(fn):  # noqa: ANN001, ANN202
        async def wrapped(request: Request) -> Any:
            try:
                return JSONResponse(await fn(request))
            except ValidationError as exc:
                # A refused workflow is an answer, not a crash: the canvas marks
                # the node the reason names.
                errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
                return JSONResponse({"ok": False,
                                     "reason": "; ".join(e["msg"] for e in errors),
                                     "errors": errors}, status_code=400)
            except GenesisError as exc:
                return JSONResponse({"ok": False, "reason": exc.reason}, status_code=400)
            except Exception as exc:  # noqa: BLE001
                log.exception("automation route failed: %s", fn.__name__)
                return JSONResponse({"ok": False, "reason": f"{type(exc).__name__}: {exc}"},
                                    status_code=500)

        wrapped.__name__ = fn.__name__
        return wrapped

    def _author(body: dict[str, Any]) -> str:
        author = str(body.get("author") or "operator")
        if author not in AUTHORS:
            raise DegradedError(f"unknown author {author!r}")
        return author

    # -- afferent ----------------------------------------------------------

    @_guard
    async def workflows(request: Request) -> dict[str, Any]:
        store = open_store()
        try:
            return {"available": True, "workflows": [v.to_dict() for v in store.list()]}
        finally:
            store.close()

    @_guard
    async def catalog(request: Request) -> dict[str, Any]:
        return {"available": True, **_catalog()}

    @_guard
    async def templates(request: Request) -> dict[str, Any]:
        """Ready-made workflows. Opening one in WB makes an unsaved, disabled copy."""
        from genesis.automation.templates import TEMPLATES

        return {"available": True, "templates": [t.to_dict() for t in TEMPLATES]}

    @_guard
    async def alerts(request: Request) -> dict[str, Any]:
        store = open_store()
        try:
            limit = min(int(request.query_params.get("limit", 50)), 200)
            return {"available": True, "alerts": store.alerts(
                limit=limit, workflow_id=request.query_params.get("workflow") or None)}
        finally:
            store.close()

    @_guard
    async def feed(request: Request) -> dict[str, Any]:
        """What the automations have produced, newest first. Derived, never stored."""
        from genesis.automation.feed import feed as build_feed

        store = open_store()
        try:
            limit = min(int(request.query_params.get("limit", 50)), 200)
            return {"available": True, **build_feed(store, limit=limit)}
        finally:
            store.close()

    @_guard
    async def workflow(request: Request) -> dict[str, Any]:
        store = open_store()
        try:
            wid = request.path_params["workflow_id"]
            current = store.current(wid)
            if current is None:
                raise DegradedError(f"no workflow {wid!r}")
            return {"available": True, "workflow": current.to_dict(),
                    "runs": store.runs(wid, limit=1)}
        finally:
            store.close()

    @_guard
    async def versions(request: Request) -> dict[str, Any]:
        store = open_store()
        try:
            wid = request.path_params["workflow_id"]
            return {"available": True, "versions": [v.to_dict() for v in store.versions(wid)]}
        finally:
            store.close()

    @_guard
    async def runs(request: Request) -> dict[str, Any]:
        store = open_store()
        try:
            limit = min(int(request.query_params.get("limit", 20)), 100)
            return {"available": True,
                    "runs": store.runs(request.path_params["workflow_id"], limit=limit)}
        finally:
            store.close()

    # -- efferent ----------------------------------------------------------

    @_guard
    async def save(request: Request) -> dict[str, Any]:
        """Append a version. Genesis's drafts are always saved disabled."""
        body = await request.json()
        author = _author(body)
        wf = Workflow.model_validate(body.get("workflow") or {})
        store = open_store()
        try:
            enabled = False if author == "orchestrator" else None
            version = store.save(wf, author=author, enabled=enabled,
                                 note=str(body.get("note") or ""),
                                 base_version=body.get("base_version"))
        finally:
            store.close()
        return {"ok": True, "workflow": version.to_dict(), "scheduled": _schedule(wf.id)}

    @_guard
    async def set_enabled(request: Request) -> dict[str, Any]:
        body = await request.json()
        if _author(body) != "operator":
            raise DegradedError("enabling a workflow is the operator's call — enable it on the canvas")
        wid = request.path_params["workflow_id"]
        store = open_store()
        try:
            version = store.set_enabled(wid, bool(body.get("enabled")), author="operator")
        finally:
            store.close()
        return {"ok": True, "workflow": version.to_dict(), "scheduled": _schedule(wid)}

    @_guard
    async def run_now(request: Request) -> dict[str, Any]:
        """One run, now, through the bus -- the same path a cadence takes."""
        from genesis.automation.workflow import agent_id_for

        daemon, _gateway = attached_daemon()
        if daemon is None:
            raise DegradedError("no daemon in this process — start `genesis serve` to run workflows")
        wid = request.path_params["workflow_id"]
        agent_id = agent_id_for(wid)
        if daemon.supervisor.agent(agent_id) is None:
            raise DegradedError(f"workflow {wid!r} is not enabled")
        from genesis.bus import Lane

        task = daemon.bus.submit(type=f"{agent_id}.run", agent=agent_id, lane=Lane.USER,
                                 args={"reason": "run now"},
                                 origin={"kind": "operator", "ref": wid})
        return {"ok": True, "task": task.id if task else None}

    @_guard
    async def delete(request: Request) -> dict[str, Any]:
        body = await request.json() if await request.body() else {}
        wid = request.path_params["workflow_id"]
        store = open_store()
        try:
            store.delete(wid, author=_author(body))
        finally:
            store.close()
        return {"ok": True, "scheduled": _schedule(wid)}

    def attached_daemon() -> tuple[Any, Any]:
        from genesis.automation import attached
        return attached()

    return [
        Route("/v1/automation/workflows", workflows),
        Route("/v1/automation/catalog", catalog),
        Route("/v1/automation/alerts", alerts),
        Route("/v1/automation/feed", feed),
        Route("/v1/automation/templates", templates),
        Route("/v1/automation/workflows/save", save, methods=["POST"]),
        Route("/v1/automation/workflows/{workflow_id}", workflow),
        Route("/v1/automation/workflows/{workflow_id}/versions", versions),
        Route("/v1/automation/workflows/{workflow_id}/runs", runs),
        Route("/v1/automation/workflows/{workflow_id}/enable", set_enabled, methods=["POST"]),
        Route("/v1/automation/workflows/{workflow_id}/run", run_now, methods=["POST"]),
        Route("/v1/automation/workflows/{workflow_id}/delete", delete, methods=["POST"]),
    ]
