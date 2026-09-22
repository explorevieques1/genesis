# Spec: Genesis Markdown/20-Agents/Journal/Journal Family.md
"""Run a journal agent by hand. Operating Model §1, the parity rule.

The planner can dispatch ``digest.brief`` from a sentence and a workflow can
dispatch it from a node; this is the button. All three submit to the same Task
Bus, so the daemon runs the same fully wired agent and the task lands in the
same audit trail. Nothing is constructed here -- a Watchdog built in a route
would have no supervisor to probe and would report a healthy fleet it cannot see.

The Trade Journal is absent for the reason it is absent from the catalogue:
it records a fill, and a button with no trade behind it has nothing to record.

`/v1/journal/mark` is the one write here, and the one thing in the journal a
person authors: a range of candles they selected on a chart, with what they
were thinking. It lands as an `Observation`, and on a named trade also in that
entry's human half. It never reaches the frozen machine record -- see
`journal/bridge.py:record_mark`.
"""

from __future__ import annotations

from typing import Any

__all__ = ["JOURNAL_RUNNABLE", "journal_routes"]

#: The write is the door. The UI drags a zone and posts it; a person posts the
#: same body by hand and gets the same record and the same audit line
#: (Operating Model §1).

#: agent -> task type. The planner catalogue's types, plus drift.
JOURNAL_RUNNABLE: dict[str, str] = {
    "digest": "digest.brief",
    "performance-analyst": "perf.review",
    "insight-miner": "insight.mine",
    "watchdog": "health.check",
    "drift": "drift.check",
}


def journal_routes() -> list[Any]:
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from genesis.bus.task import Lane
    from genesis.server.analyst import ANALYST

    async def run(request: Request) -> JSONResponse:
        body = await request.json() if await request.body() else {}
        agent = str(body.get("agent") or "")
        if agent not in JOURNAL_RUNNABLE:
            return JSONResponse({"ok": False, "reason": f"not a runnable journal agent: {agent!r}"}, status_code=400)
        bus = ANALYST.bus
        if bus is None:
            return JSONResponse(
                {"ok": False, "reason": "the fleet is not running — start `genesis serve` without --no-daemon"},
                status_code=503,
            )
        args = body.get("args") if isinstance(body.get("args"), dict) else {}
        task = bus.submit(
            type=JOURNAL_RUNNABLE[agent], agent=agent, lane=Lane.RESEARCH, args=args,
            origin={"kind": "operator", "ref": "journal-desk"},
        )
        return JSONResponse({"ok": True, "task": task.id if task else None})

    async def status(request: Request) -> JSONResponse:
        bus = ANALYST.bus
        task = bus.get(request.path_params["task_id"]) if bus is not None else None
        if task is None:
            return JSONResponse({"ok": False, "reason": "no such task"}, status_code=404)
        return JSONResponse({
            "available": True, "state": task.state.value, "result": task.result, "failure": task.failure,
        })

    def _store():
        from genesis.config import load_config
        from genesis.journal.store import JournalStore

        # A write, so this may create the file -- unlike the read routes, where
        # opening a store would make "has this ever run?" unanswerable.
        return JournalStore(path=load_config().memory.db_path.parent / "journal.db")

    async def mark(request: Request) -> JSONResponse:
        """Journal a marked range of candles: an entry, an exit, or an idea."""
        from genesis.errors import GenesisError
        from genesis.journal.bridge import record_mark

        body = await request.json() if await request.body() else {}
        try:
            observation = record_mark(
                _store(),
                kind=str(body.get("kind") or ""),
                symbol=str(body.get("symbol") or ""),
                timeframe=str(body.get("timeframe") or ""),
                start=int(body.get("start") or 0),
                end=int(body.get("end") or 0),
                note=str(body.get("note") or ""),
                series=str(body.get("series") or ""),
                drawing_id=str(body.get("drawing_id") or ""),
                entry_id=str(body.get("entry_id") or ""),
            )
        except (ValueError, TypeError, GenesisError) as exc:
            # A refused mark says why: this is a person typing, not an agent.
            return JSONResponse({"ok": False, "reason": str(exc)}, status_code=400)
        return JSONResponse({"ok": True, "mark": observation.model_dump(mode="json")})

    async def marks(request: Request) -> JSONResponse:
        from genesis.journal.bridge import marks as read_marks

        try:
            found = read_marks(
                _store(),
                symbol=request.query_params.get("symbol", ""),
                limit=min(int(request.query_params.get("limit", 200)), 1000),
            )
        except Exception as exc:  # noqa: BLE001 - an empty journal is an absence
            return JSONResponse({"available": False, "reason": str(exc)})
        return JSONResponse(
            {"available": True, "marks": [o.model_dump(mode="json") for o in found]}
        )

    return [
        Route("/v1/journal/run", run, methods=["POST"]),
        Route("/v1/journal/run/{task_id}", status),
        Route("/v1/journal/mark", mark, methods=["POST"]),
        Route("/v1/journal/marks", marks),
    ]
