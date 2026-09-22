# Spec: Genesis Markdown/60-UI/Research Canvas.md
"""The research canvas: a spatial view of the Knowledge Graph.

Obsidian's graph, for market work, **with Genesis able to read and write it** --
and that last clause is the whole reason this module exists in `src/` rather
than in the browser.

Research Canvas.md is blunt about it:

> A canvas could be built entirely in the browser with `localStorage` in an
> afternoon. That is precisely why it has not been. [...] A canvas whose nodes
> exist only in one viewer's browser is invisible to the agent that is supposed
> to use it: it cannot cite a node, add one from a research pass, or notice that
> two threads of enquiry converged.

So what is stored here is **membership and position only**. The nodes themselves
are :mod:`genesis.memory.graph` entities, and those are references to records
that already exist -- a research note, a markup spec, a ticker. Three rules
follow, and each is a thing this module refuses to do:

**It does not hold content.** A canvas row is ``(canvas, entity, x, y)``. To read
a node you follow its entity's ``ref`` to the store that owns it. Copying a
research note onto a canvas would make the canvas a second, staler copy of it.

**It does not invent edges.** Lines between nodes are Knowledge Graph edges,
recorded by whoever asserted them -- an agent in its own namespace, or the
operator by hand through :meth:`Canvas.assert_edge`. Nothing here computes
similarity to make the picture look busier.

**It is not per-viewer.** The note permits layout to live per viewer. It does not
here, because Genesis arranges this canvas too: an agent that adds a node during
an overnight pass has to put it somewhere, and a position only one browser can
see is a position the agent cannot have chosen. One operator, one shared canvas,
and the arrangement is a thing you and Genesis both edit -- which is what makes
it a second brain rather than a drawing.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from genesis.errors import FatalError
from genesis.ids import new_id
from genesis.memory.db import connect, transaction
from genesis.memory.graph import Edge, Entity, KnowledgeGraph

__all__ = ["SCHEMA", "CanvasNode", "CanvasStore", "CanvasView", "OPERATOR"]

#: The namespace a human's own edits are written under. A node the operator
#: placed and a node an agent placed are both real, and telling them apart later
#: is the difference between "I decided this" and "it suggested this".
OPERATOR = "operator"

SCHEMA = """
CREATE TABLE IF NOT EXISTS canvas (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    -- What this canvas was opened for. A question, usually. Kept so a canvas
    -- found three weeks later can say why it exists.
    query      TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created    TEXT NOT NULL,
    updated    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS canvas_node (
    canvas    TEXT NOT NULL REFERENCES canvas(id) ON DELETE CASCADE,
    -- A Knowledge Graph entity id. Not a copy of it.
    entity    TEXT NOT NULL,
    x         REAL NOT NULL DEFAULT 0,
    y         REAL NOT NULL DEFAULT 0,
    -- Pinned nodes survive re-layout. This is how a person's arrangement of the
    -- three nodes they care about is not undone by an agent adding a fourth.
    pinned    INTEGER NOT NULL DEFAULT 0,
    added_by  TEXT NOT NULL,
    added     TEXT NOT NULL,
    PRIMARY KEY (canvas, entity)
);
CREATE INDEX IF NOT EXISTS canvas_node_canvas ON canvas_node (canvas);
"""


@dataclass(frozen=True)
class CanvasNode:
    """One placed node: where an entity sits, and who put it there."""

    entity: str
    x: float
    y: float
    pinned: bool = False
    added_by: str = OPERATOR
    added: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity, "x": self.x, "y": self.y,
            "pinned": self.pinned, "added_by": self.added_by,
            "added": self.added.isoformat(),
        }


@dataclass(frozen=True)
class CanvasView:
    """A canvas, resolved: its placed nodes, their entities, and the edges."""

    id: str
    title: str
    query: str
    created_by: str
    created: datetime
    updated: datetime
    nodes: tuple[CanvasNode, ...] = ()
    entities: tuple[Entity, ...] = ()
    edges: tuple[Edge, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        placed = {n.entity: n for n in self.nodes}
        return {
            "id": self.id,
            "title": self.title,
            "query": self.query,
            "created_by": self.created_by,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat(),
            "nodes": [
                # The entity and its placement, flattened for the renderer --
                # which wants one object per node, not a join it has to do in
                # the browser.
                {**e.to_dict(), **placed[e.id].to_dict()}
                for e in self.entities if e.id in placed
            ],
            # Only edges between nodes that are actually on the canvas. A line
            # to a node you cannot see is a line into nothing.
            "edges": [
                e.to_dict() for e in self.edges
                if e.src in placed and e.dst in placed
            ],
        }


@dataclass
class CanvasStore:
    """Canvases, their membership, and their layout. Nodes live in the graph."""

    path: Path | str = "~/.genesis/memory/canvas.db"
    graph: KnowledgeGraph | None = None
    _conn: sqlite3.Connection | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._conn = connect(self.path)
        self._conn.executescript(SCHEMA)
        if self.graph is None:
            # Same directory as this store by default: the canvas is a view of
            # the graph, and a view whose graph is somewhere else is a view of
            # nothing. Callers that keep them apart must say so explicitly.
            self.graph = KnowledgeGraph(path=Path(self.path).parent / "graph.db")

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("CanvasStore is closed")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Canvases
    # ------------------------------------------------------------------

    def create(self, title: str, *, query: str = "", created_by: str = OPERATOR) -> str:
        cid = new_id("cv")
        now = datetime.now(UTC).isoformat()
        with transaction(self.conn) as conn:
            conn.execute(
                "INSERT INTO canvas (id, title, query, created_by, created, updated) "
                "VALUES (?,?,?,?,?,?)",
                (cid, title, query, created_by, now, now),
            )
        return cid

    def list(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM canvas_node n WHERE n.canvas = c.id) "
            "AS nodes FROM canvas c ORDER BY updated DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, canvas_id: str) -> None:
        """Remove a canvas. The graph is untouched.

        Deliberate: a canvas is an arrangement, and throwing away an arrangement
        must not throw away what the system learned. The entities and edges
        outlive every canvas that ever showed them.
        """
        with transaction(self.conn) as conn:
            conn.execute("DELETE FROM canvas_node WHERE canvas = ?", (canvas_id,))
            conn.execute("DELETE FROM canvas WHERE id = ?", (canvas_id,))

    def view(self, canvas_id: str, *, expand: int = 0) -> CanvasView:
        """A canvas with its entities and edges resolved.

        ``expand`` pulls in neighbours that are *not* on the canvas -- a preview
        of what adding them would show. They come back as entities without a
        placement, so the renderer can offer them without them being members.
        """
        row = self.conn.execute(
            "SELECT * FROM canvas WHERE id = ?", (canvas_id,)
        ).fetchone()
        if row is None:
            raise FatalError(f"no canvas {canvas_id!r}")
        nodes = self.nodes(canvas_id)
        ids = [n.entity for n in nodes]
        entities, edges = self.graph.subgraph(ids, depth=expand, limit=400)
        # Entities the graph no longer has (deleted upstream) would render as
        # empty boxes. Drop them from the view and leave the membership row --
        # it costs nothing and the node returns if the entity does.
        return CanvasView(
            id=row["id"], title=row["title"], query=row["query"],
            created_by=row["created_by"],
            created=datetime.fromisoformat(row["created"]),
            updated=datetime.fromisoformat(row["updated"]),
            nodes=tuple(nodes), entities=tuple(entities), edges=tuple(edges),
        )

    # ------------------------------------------------------------------
    # Membership and layout
    # ------------------------------------------------------------------

    def nodes(self, canvas_id: str) -> list[CanvasNode]:
        rows = self.conn.execute(
            "SELECT * FROM canvas_node WHERE canvas = ?", (canvas_id,)
        ).fetchall()
        return [
            CanvasNode(
                entity=r["entity"], x=r["x"], y=r["y"], pinned=bool(r["pinned"]),
                added_by=r["added_by"], added=datetime.fromisoformat(r["added"]),
            )
            for r in rows
        ]

    def add(
        self,
        canvas_id: str,
        entity_ids: Iterable[str],
        *,
        by: str = OPERATOR,
        layout: bool = True,
    ) -> int:
        """Place entities on a canvas. Idempotent; existing nodes do not move.

        An entity that is not in the graph is refused rather than placed: a node
        with nothing behind it is exactly the empty box this design is built to
        avoid.
        """
        now = datetime.now(UTC).isoformat()
        wanted = [e for e in entity_ids]
        missing = [e for e in wanted if self.graph.entity(e) is None]
        if missing:
            raise FatalError(f"not in the knowledge graph: {', '.join(missing[:5])}")
        added = 0
        with transaction(self.conn) as conn:
            for eid in wanted:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO canvas_node "
                    "(canvas, entity, x, y, pinned, added_by, added) "
                    "VALUES (?,?,?,?,0,?,?)",
                    (canvas_id, eid, 0.0, 0.0, by, now),
                )
                added += cur.rowcount
            conn.execute("UPDATE canvas SET updated = ? WHERE id = ?", (now, canvas_id))
        if added and layout:
            self.arrange(canvas_id)
        return added

    def remove(self, canvas_id: str, entity_ids: Iterable[str]) -> int:
        removed = 0
        with transaction(self.conn) as conn:
            for eid in entity_ids:
                cur = conn.execute(
                    "DELETE FROM canvas_node WHERE canvas = ? AND entity = ?",
                    (canvas_id, eid),
                )
                removed += cur.rowcount
        return removed

    def move(self, canvas_id: str, entity: str, x: float, y: float, *, pin: bool = True) -> None:
        """Put a node where someone dragged it.

        Pinning by default: a person who moved a node meant it, and the next
        auto-arrange must not undo it.
        """
        with transaction(self.conn) as conn:
            conn.execute(
                "UPDATE canvas_node SET x = ?, y = ?, pinned = ? "
                "WHERE canvas = ? AND entity = ?",
                (x, y, int(pin), canvas_id, entity),
            )
            conn.execute(
                "UPDATE canvas SET updated = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), canvas_id),
            )

    def arrange(self, canvas_id: str, *, radius: float = 260.0) -> None:
        """Lay out the unpinned nodes. Pinned ones are never touched.

        Concentric rings by type, which is a weak layout and an honest one: it
        is deterministic, it never jumps between loads, and it groups nodes by
        what they *are*. A force simulation on the server would be a second
        layout engine competing with the renderer's, and neither would win.
        """
        nodes = self.nodes(canvas_id)
        loose = [n for n in nodes if not n.pinned]
        if not loose:
            return
        entities = {n.entity: self.graph.entity(n.entity) for n in loose}
        # Group by type so the rings mean something.
        by_type: dict[str, list[str]] = {}
        for eid, entity in entities.items():
            by_type.setdefault(entity.type if entity else "unknown", []).append(eid)

        placements: list[tuple[float, float, str]] = []
        for ring, (_, members) in enumerate(sorted(by_type.items())):
            r = radius * (ring + 1) * 0.6
            for i, eid in enumerate(sorted(members)):
                angle = (2 * math.pi * i) / max(1, len(members))
                placements.append((r * math.cos(angle), r * math.sin(angle), eid))

        with transaction(self.conn) as conn:
            for x, y, eid in placements:
                conn.execute(
                    "UPDATE canvas_node SET x = ?, y = ? "
                    "WHERE canvas = ? AND entity = ? AND pinned = 0",
                    (x, y, canvas_id, eid),
                )

    # ------------------------------------------------------------------
    # Drawing a line means asserting something
    # ------------------------------------------------------------------

    def assert_edge(
        self, src: str, kind: str, dst: str, *, by: str = OPERATOR
    ) -> Edge:
        """A line the operator drew, recorded in the graph as a real edge.

        Not stored on the canvas. Dragging a link between two nodes is a claim
        about the world -- *this idea derives from that filing* -- and a claim
        belongs in the graph where every other agent can read it, under the
        namespace of whoever made it. A canvas-local line would be a claim only
        one picture knows about, which is the browser-only failure again in
        miniature.
        """
        return self.graph.link(src, kind, dst, namespace=by)

    def retract_edge(self, src: str, kind: str, dst: str, *, by: str = OPERATOR) -> None:
        """Undraw a line -- but only one whose author you are.

        The symmetry with :meth:`assert_edge` is deliberate and so is the
        asymmetry: drawing a line is a claim, so rubbing one out is a
        retraction, and you may only retract what you asserted. An edge an agent
        recorded is either provenance it observed or a relationship it measured,
        and letting a drag of the mouse delete that would make the graph's
        namespaces decorative. To stop seeing such an edge, remove one of its
        nodes from the canvas -- the graph keeps what it learned, which is the
        same trade `delete` makes for a whole canvas.
        """
        if self.graph.unlink(src, kind, dst, namespace=by):
            return
        others = [
            e for e in self.graph.edges_of(src, kinds=[kind], both_ways=False)
            if e.dst == dst
        ]
        if others:
            raise FatalError(
                f"{others[0].namespace} recorded that link, not you -- remove a "
                f"node to take it off the canvas; the graph keeps what it learned"
            )
        raise FatalError(f"no {kind} link from {src} to {dst}")

    # ------------------------------------------------------------------
    # What Genesis calls
    # ------------------------------------------------------------------

    def open_for(
        self,
        query: str,
        *,
        title: str = "",
        seeds: Sequence[str] = (),
        depth: int = 1,
        limit: int = 60,
        created_by: str = OPERATOR,
    ) -> str:
        """Build a canvas that answers a question, and return its id.

        This is the method behind *"Genesis, show me what you found."* Seeds come
        from an explicit list when the caller has one -- the ids a research pass
        just wrote -- and otherwise from a label search, which is why the search
        is a substring match and not a similarity model: the operator names a
        thing, and the canvas opens on that thing rather than on its vicinity.

        An empty result still creates the canvas. A canvas that says *"nothing
        in the graph matches this"* is a real answer; silently returning nothing
        is indistinguishable from a broken button.
        """
        found = list(seeds) or [e.id for e in self.graph.search(query, limit=limit)]
        cid = self.create(title or query or "Canvas", query=query, created_by=created_by)
        if found:
            entities, _ = self.graph.subgraph(found, depth=depth, limit=limit)
            self.add(cid, [e.id for e in entities], by=created_by)
        return cid


def demo() -> None:
    """Self-check: membership is references, layout is honoured, lines are claims."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        graph = KnowledgeGraph(path=f"{tmp}/graph.db")
        store = CanvasStore(path=f"{tmp}/canvas.db", graph=graph)

        note = graph.upsert("thesis", "wd-gann", label="W.D. Gann",
                            namespace="topic-researcher", ref="res_1")
        page = graph.upsert("document", "https://a.test/g", label="Gann sources",
                            namespace="topic-researcher")
        nvda = graph.upsert("symbol", "NVDA", label="NVDA", namespace="shared")
        graph.link(note.id, "derived_from", page.id, namespace="topic-researcher")

        cid = store.open_for("Gann", created_by="orchestrator")
        view = store.view(cid)
        ids = {n["id"] for n in view.to_dict()["nodes"]}
        assert note.id in ids and page.id in ids, ids
        assert nvda.id not in ids, "an unrelated symbol is not dragged in"
        assert view.to_dict()["edges"], "the recorded edge is on the canvas"

        # The node carries a ref, not the note's content.
        node = next(n for n in view.to_dict()["nodes"] if n["id"] == note.id)
        assert node["ref"] == "res_1" and "body" not in node

        # A dragged node is pinned and survives re-arrangement.
        store.move(cid, note.id, 111.0, 222.0)
        store.add(cid, [nvda.id], by="operator")
        placed = {n.entity: n for n in store.nodes(cid)}
        assert (placed[note.id].x, placed[note.id].y) == (111.0, 222.0)
        assert placed[nvda.id].x != 0 or placed[nvda.id].y != 0, "new nodes get placed"

        # A line drawn by hand is a graph edge under the operator's namespace.
        store.assert_edge(note.id, "mentions", nvda.id, by="operator")
        assert any(
            e.namespace == "operator" for e in graph.edges_of(note.id, kinds=["mentions"])
        )

        # A line you drew, you may undraw. One an agent drew, you may not.
        store.retract_edge(note.id, "mentions", nvda.id, by="operator")
        assert not graph.edges_of(note.id, kinds=["mentions"]), "the claim is gone"
        try:
            store.retract_edge(note.id, "derived_from", page.id, by="operator")
        except FatalError as exc:
            assert "topic-researcher" in str(exc), exc
        else:  # pragma: no cover - the guard is the point
            raise AssertionError("an agent's edge was deleted by hand")

        # Deleting the canvas keeps what was learned.
        store.delete(cid)
        assert store.list() == [] and graph.entity(note.id) is not None

        print("research canvas: ok")


if __name__ == "__main__":
    demo()
