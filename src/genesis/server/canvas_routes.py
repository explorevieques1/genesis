# Spec: Genesis Markdown/60-UI/Research Canvas.md
"""The canvas surface: afferent reads and the four writes that arrange it.

Kept apart from ``reads.py`` because these **act**. Afferent and efferent are
structurally different paths (Biological Design §2), and a module where a
listing and a mutation sit in the same list is one where the next mutation gets
added without anyone noticing it was a mutation.

What acts here, and nothing else does: create a canvas, place or remove nodes,
move a node, and assert an edge. Every one is idempotent or trivially
reversible, none of them touches an order path, and none can reach the broker --
there is nothing here to route around, because this module imports no execution
code at all.

The writes are deliberately *small*. Arranging a canvas is the one place where a
person and Genesis edit the same object, so each edit is a single fact --
"this node is here now", "these two things are related" -- rather than a
whole-canvas PUT. A whole-canvas write would make the last save win, and the
loser would be whichever of you was not looking.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from genesis.errors import GenesisError

__all__ = ["canvas_routes"]

log = logging.getLogger(__name__)


def _store():
    """The canvas store, over the same graph the agents write.

    Path from config, like every other store -- see ``reads._memory_db``. The
    canvas database is created on demand rather than reported absent, because
    unlike a research note an empty canvas store is not evidence of anything:
    you get one the first time you open a canvas, and that is the normal path.
    """
    from genesis.config import load_config
    from genesis.memory.graph import KnowledgeGraph
    from genesis.research.canvas import CanvasStore

    memory = Path(load_config().memory.db_path).expanduser().parent
    return CanvasStore(
        path=memory / "canvas.db",
        graph=KnowledgeGraph(path=memory / "graph.db"),
    )


def canvas_routes() -> list[Any]:
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    def _guard(fn):  # noqa: ANN001, ANN202
        """A typed failure becomes a reported one. Never a 500, never silence."""
        async def wrapped(request: Request) -> Any:
            try:
                return JSONResponse(await fn(request))
            except GenesisError as exc:
                return JSONResponse({"ok": False, "available": False,
                                     "reason": exc.reason}, status_code=400)
            except Exception as exc:  # noqa: BLE001
                log.exception("canvas route failed: %s", fn.__name__)
                return JSONResponse(
                    {"ok": False, "available": False,
                     "reason": f"{type(exc).__name__}: {exc}"},
                    status_code=500,
                )

        wrapped.__name__ = fn.__name__
        return wrapped

    # -- afferent ----------------------------------------------------------

    @_guard
    async def canvases(request: Request) -> dict[str, Any]:
        store = _store()
        return {
            "available": True,
            "canvases": store.list(),
            # What is *in* the graph, whether or not it is on a canvas. The
            # empty state needs this: "nothing on this canvas" and "nothing in
            # the graph to put on one" are different problems with different
            # fixes, and a canvas that cannot tell them apart sends you looking
            # in the wrong place.
            "graph": store.graph.counts(),
        }

    @_guard
    async def canvas(request: Request) -> dict[str, Any]:
        store = _store()
        expand = min(int(request.query_params.get("expand", 0)), 2)
        return {"available": True, "canvas": store.view(
            request.path_params["canvas_id"], expand=expand
        ).to_dict()}

    @_guard
    async def graph_search(request: Request) -> dict[str, Any]:
        """Entities to drop onto a canvas, by name."""
        store = _store()
        query = request.query_params.get("q", "").strip()
        found = store.graph.search(query) if query else store.graph.entities(limit=60)
        return {"available": True, "entities": [e.to_dict() for e in found]}

    # -- efferent ----------------------------------------------------------

    @_guard
    async def create(request: Request) -> dict[str, Any]:
        """Open a canvas — by question, or empty.

        ``query`` is the interesting form: it seeds from the graph, which is
        what "Genesis, show me what you found on Gann" resolves to.
        """
        body = await request.json()
        store = _store()
        query = str(body.get("query") or "").strip()
        title = str(body.get("title") or "").strip()
        if query:
            cid = store.open_for(
                query, title=title, depth=min(int(body.get("depth", 1)), 2),
                created_by=str(body.get("by") or "operator"),
            )
        else:
            cid = store.create(title or "Canvas", created_by="operator")
        return {"ok": True, "canvas": store.view(cid).to_dict()}

    @_guard
    async def add_nodes(request: Request) -> dict[str, Any]:
        body = await request.json()
        store = _store()
        cid = request.path_params["canvas_id"]
        ids = [str(e) for e in body.get("entities", [])]
        added = store.add(cid, ids, by="operator")
        return {"ok": True, "added": added, "canvas": store.view(cid).to_dict()}

    @_guard
    async def remove_nodes(request: Request) -> dict[str, Any]:
        body = await request.json()
        store = _store()
        cid = request.path_params["canvas_id"]
        removed = store.remove(cid, [str(e) for e in body.get("entities", [])])
        return {"ok": True, "removed": removed, "canvas": store.view(cid).to_dict()}

    @_guard
    async def move_node(request: Request) -> dict[str, Any]:
        """One node, one position. Pinned, because a person meant it."""
        body = await request.json()
        store = _store()
        store.move(
            request.path_params["canvas_id"], str(body["entity"]),
            float(body["x"]), float(body["y"]),
        )
        return {"ok": True}

    @_guard
    async def link(request: Request) -> dict[str, Any]:
        """A line drawn by hand becomes a recorded edge in the graph.

        Under the ``operator`` namespace, so a claim you made is later
        distinguishable from one an agent made — which is the difference
        between "I decided this" and "it suggested this".
        """
        body = await request.json()
        store = _store()
        edge = store.assert_edge(
            str(body["source"]), str(body["kind"]), str(body["target"]), by="operator"
        )
        cid = request.path_params["canvas_id"]
        return {"ok": True, "edge": edge.to_dict(),
                "canvas": store.view(cid).to_dict()}

    @_guard
    async def unlink(request: Request) -> dict[str, Any]:
        """A line rubbed out — a retraction of a claim you made.

        Refused for an edge an agent recorded: that is provenance it observed or
        a relationship it measured, and a drag of the mouse must not be able to
        delete it. `_guard` turns the refusal into an honest error rather than a
        silent no-op, which is the difference between "you may not" and "it did
        not work".
        """
        body = await request.json()
        store = _store()
        store.retract_edge(
            str(body["source"]), str(body["kind"]), str(body["target"]), by="operator"
        )
        cid = request.path_params["canvas_id"]
        return {"ok": True, "canvas": store.view(cid).to_dict()}

    @_guard
    async def delete_canvas(request: Request) -> dict[str, Any]:
        """Throw away the arrangement. The graph keeps what was learned."""
        _store().delete(request.path_params["canvas_id"])
        return {"ok": True}

    return [
        Route("/v1/canvas", canvases),
        Route("/v1/canvas/graph", graph_search),
        Route("/v1/canvas/new", create, methods=["POST"]),
        Route("/v1/canvas/{canvas_id}", canvas),
        Route("/v1/canvas/{canvas_id}/delete", delete_canvas, methods=["POST"]),
        Route("/v1/canvas/{canvas_id}/add", add_nodes, methods=["POST"]),
        Route("/v1/canvas/{canvas_id}/remove", remove_nodes, methods=["POST"]),
        Route("/v1/canvas/{canvas_id}/move", move_node, methods=["POST"]),
        Route("/v1/canvas/{canvas_id}/link", link, methods=["POST"]),
        Route("/v1/canvas/{canvas_id}/unlink", unlink, methods=["POST"]),
    ]
