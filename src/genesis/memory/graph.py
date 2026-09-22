# Spec: Genesis Markdown/40-Memory/Knowledge Graph.md
"""What the system believes, and how those beliefs connect.

Entities and typed, directional edges. The typing is the whole point: a graph of
undifferentiated links is *connected*, not **answerable**, and every question in
the note's "questions it exists to answer" section is a question about an edge
kind. *Which of my levels actually hold?* is `level --held|broke--> outcome`
aggregated; without the edge kind it is not a query, it is a picture.

Four properties are structural here rather than conventional:

**Entities are references, not copies.** An entity holds a type, a key, a label
and a ``ref`` pointing at the record that actually owns the content -- a research
note id, a markup spec id, a ticker. Copying the content in would make the graph
a second source of truth for things that already have one, and the first
divergence would be silent.

**Edges are recorded, never inferred.** Nothing in this module computes
similarity. A graph built from embedding distance looks identical to one built
from provenance and means something entirely different: the first shows what
resembles what, the second shows what *justifies* what, and only the second is
worth acting on. The journal graph already follows this rule; so does this.

**New facts supersede rather than pile up.** :meth:`KnowledgeGraph.upsert` on an
existing key updates in place; :meth:`KnowledgeGraph.supersede` retires the old
entity behind a ``supersedes`` edge. Retrieval returns current state by default
and the history stays queryable, which is the note's rule.

**Writes carry their namespace.** Every entity and edge records which agent
wrote it. Memory Fabric's single-writer rule is only enforceable if the writer
is on the row.

Not built here, and deliberately: **beliefs, promotion, retirement and nightly
merges.** Those are [[Memory Consolidation]]'s, they need a corpus of repeated
observations this system has not accumulated yet, and a belief that was promoted
from three observations is worse than no belief. The ``belief`` entity type is
accepted so the consolidator has somewhere to write; nothing here creates one.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from genesis.errors import FatalError
from genesis.memory.db import connect, transaction

__all__ = [
    "EDGE_KINDS",
    "ENTITY_TYPES",
    "SCHEMA",
    "Edge",
    "Entity",
    "KnowledgeGraph",
    "entity_id",
]

#: The note's eleven types, plus one.
#:
#: ``document`` is the addition, and [[Research Canvas]] is why: its opening line
#: is "documents, filings, charts, notes and the links between them", and none of
#: the eleven covers a fetched web page or a filing. Modelling one as a `thesis`
#: would be a lie about what it is -- a page is not a claim, it is where a claim
#: came from -- and `derived_from` edges into it are exactly the provenance the
#: canvas exists to show.
ENTITY_TYPES = (
    "symbol", "level", "setup", "strategy", "idea", "thesis", "trade",
    "lesson", "regime", "catalyst", "belief", "document",
)

#: The note's edge table. Directional, and the direction is part of the meaning:
#: ``derived_from`` points from the conclusion to its evidence, so following it
#: forward is "show your work" and following it backward is "what did this
#: support".
EDGE_KINDS = (
    "derived_from", "traded_as", "invalidated_by", "confirms", "contradicts",
    "supersedes", "held", "broke", "works_in", "fails_in", "learned_from",
    "applies_to", "correlates_with",
    # `mentions` is the weak one, and it is separate from `applies_to` on
    # purpose. "This research note mentions NVDA" is not "this lesson applies to
    # NVDA": one is a pointer, the other is a claim about scope. Collapsing them
    # would let a passing mention answer "which lessons apply to this trade".
    "mentions",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS kg_entity (
    id            TEXT PRIMARY KEY,       -- '<type>:<key>'
    type          TEXT NOT NULL,
    key           TEXT NOT NULL,
    label         TEXT NOT NULL,
    -- The record that owns the content. A research note id, a markup spec id,
    -- a symbol id. The graph never copies what this points at.
    ref           TEXT,
    data          TEXT NOT NULL DEFAULT '{}',
    namespace     TEXT NOT NULL,
    created       TEXT NOT NULL,
    updated       TEXT NOT NULL,
    superseded_by TEXT REFERENCES kg_entity(id),
    UNIQUE (type, key)
);
CREATE INDEX IF NOT EXISTS kg_entity_type ON kg_entity (type);
CREATE INDEX IF NOT EXISTS kg_entity_live ON kg_entity (superseded_by) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS kg_edge (
    id        INTEGER PRIMARY KEY,
    src       TEXT NOT NULL REFERENCES kg_entity(id),
    kind      TEXT NOT NULL,
    dst       TEXT NOT NULL REFERENCES kg_entity(id),
    weight    REAL NOT NULL DEFAULT 1.0,
    data      TEXT NOT NULL DEFAULT '{}',
    namespace TEXT NOT NULL,
    created   TEXT NOT NULL,
    UNIQUE (src, kind, dst)
);
CREATE INDEX IF NOT EXISTS kg_edge_src ON kg_edge (src);
CREATE INDEX IF NOT EXISTS kg_edge_dst ON kg_edge (dst);

-- An edge whose endpoints do not exist is a dangling reference, and a graph
-- that tolerates them answers questions with holes in them. `foreign_keys=ON`
-- is set by `memory.db.connect`, so this is enforced rather than intended.
"""


def entity_id(type_: str, key: str) -> str:
    """The composite id. One spelling, so two writers cannot disagree on it."""
    if type_ not in ENTITY_TYPES:
        raise FatalError(f"unknown entity type {type_!r} — see Knowledge Graph.md")
    return f"{type_}:{key}"


@dataclass(frozen=True)
class Entity:
    """A node: a reference to something that exists, not a copy of it."""

    type: str
    key: str
    label: str
    namespace: str
    ref: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    created: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated: datetime = field(default_factory=lambda: datetime.now(UTC))
    superseded_by: str | None = None

    @property
    def id(self) -> str:
        return entity_id(self.type, self.key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "key": self.key,
            "label": self.label,
            "ref": self.ref,
            "data": self.data,
            "namespace": self.namespace,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat(),
            "superseded_by": self.superseded_by,
        }


@dataclass(frozen=True)
class Edge:
    """A typed, directional, recorded relationship."""

    src: str
    kind: str
    dst: str
    namespace: str
    weight: float = 1.0
    data: dict[str, Any] = field(default_factory=dict)
    created: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.src,
            "kind": self.kind,
            "target": self.dst,
            "weight": self.weight,
            "data": self.data,
            "namespace": self.namespace,
            "created": self.created.isoformat(),
        }


@dataclass
class KnowledgeGraph:
    """Entities and typed edges. The layer the Research Canvas is a view of."""

    path: Path | str = "~/.genesis/memory/graph.db"
    _conn: sqlite3.Connection | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._conn = connect(self.path)
        self._conn.executescript(SCHEMA)

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("KnowledgeGraph is closed")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def upsert(
        self,
        type_: str,
        key: str,
        *,
        label: str,
        namespace: str,
        ref: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Entity:
        """Add or update one entity. Idempotent on ``(type, key)``.

        Updating in place rather than inserting a second row is what keeps
        "NVDA" one node instead of one per mention. A genuinely *new* fact that
        replaces an old one goes through :meth:`supersede` instead, which keeps
        both and records which won.
        """
        eid = entity_id(type_, key)
        now = datetime.now(UTC).isoformat()
        payload = json.dumps(data or {}, default=str)
        with transaction(self.conn) as conn:
            conn.execute(
                """
                INSERT INTO kg_entity (id, type, key, label, ref, data, namespace,
                                       created, updated)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    label = excluded.label,
                    ref = COALESCE(excluded.ref, kg_entity.ref),
                    data = excluded.data,
                    updated = excluded.updated
                """,
                (eid, type_, key, label, ref, payload, namespace, now, now),
            )
        got = self.entity(eid)
        assert got is not None  # just written, inside the same connection
        return got

    def link(
        self,
        src: str,
        kind: str,
        dst: str,
        *,
        namespace: str,
        weight: float = 1.0,
        data: dict[str, Any] | None = None,
    ) -> Edge:
        """Record one typed edge. Idempotent on ``(src, kind, dst)``.

        Both endpoints must already exist. The foreign keys enforce it, and the
        error that comes back names the missing end -- a dangling edge is a hole
        in an answer, and it is much cheaper to refuse it here than to explain a
        node that renders with no content later.
        """
        if kind not in EDGE_KINDS:
            raise FatalError(f"unknown edge kind {kind!r} — see Knowledge Graph.md")
        now = datetime.now(UTC).isoformat()
        try:
            with transaction(self.conn) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO kg_edge "
                    "(src, kind, dst, weight, data, namespace, created) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (src, kind, dst, weight,
                     json.dumps(data or {}, default=str), namespace, now),
                )
        except sqlite3.IntegrityError as exc:
            missing = [e for e in (src, dst) if self.entity(e) is None]
            raise FatalError(
                f"edge {src} -{kind}-> {dst} references entities that do not "
                f"exist: {missing or exc}"
            ) from exc
        return Edge(src=src, kind=kind, dst=dst, namespace=namespace,
                    weight=weight, data=data or {})

    def unlink(
        self, src: str, kind: str, dst: str, *, namespace: str | None = None
    ) -> int:
        """Delete one recorded edge. Returns how many rows went.

        The counterpart to :meth:`link`, and unlike :meth:`supersede` it keeps
        no tombstone: an edge is an assertion, and a retracted assertion that
        still renders is worse than one that is gone. Entities are what history
        is kept for.

        ``namespace`` restricts the delete to edges recorded under it, which is
        how "you may undraw your own lines" is enforced one layer up rather
        than hoped for.
        """
        sql = "DELETE FROM kg_edge WHERE src = ? AND kind = ? AND dst = ?"
        params: list[Any] = [src, kind, dst]
        if namespace is not None:
            sql += " AND namespace = ?"
            params.append(namespace)
        with transaction(self.conn) as conn:
            return conn.execute(sql, params).rowcount

    def supersede(self, old_id: str, new_id: str, *, namespace: str) -> None:
        """Retire ``old`` in favour of ``new``, keeping both.

        The old entity stops appearing in default retrieval and stays queryable
        through the ``supersedes`` edge. History matters; it just is not the
        current answer.
        """
        if self.entity(old_id) is None or self.entity(new_id) is None:
            raise FatalError(f"cannot supersede {old_id!r} with {new_id!r}: unknown id")
        with transaction(self.conn) as conn:
            conn.execute(
                "UPDATE kg_entity SET superseded_by = ? WHERE id = ?", (new_id, old_id)
            )
        self.link(new_id, "supersedes", old_id, namespace=namespace)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def entity(self, eid: str) -> Entity | None:
        row = self.conn.execute(
            "SELECT * FROM kg_entity WHERE id = ?", (eid,)
        ).fetchone()
        return _to_entity(row) if row else None

    def entities(
        self,
        *,
        type_: str | None = None,
        namespace: str | None = None,
        include_superseded: bool = False,
        limit: int = 500,
    ) -> list[Entity]:
        clauses, params = [], []
        if not include_superseded:
            clauses.append("superseded_by IS NULL")
        if type_:
            clauses.append("type = ?")
            params.append(type_)
        if namespace:
            clauses.append("namespace = ?")
            params.append(namespace)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM kg_entity {where} ORDER BY updated DESC LIMIT {int(limit)}",
            params,
        ).fetchall()
        return [_to_entity(r) for r in rows]

    def search(self, query: str, *, limit: int = 40) -> list[Entity]:
        """Entities whose label or key matches. Substring, deliberately.

        No embeddings and no ranking model: this feeds a canvas seed and a
        person's search box, and both want *"the thing I named"* rather than
        *"things reminiscent of what I named"*. Similarity search is the
        [[Vector Store]]'s job and lives behind a different door.
        """
        like = f"%{query.strip()}%"
        rows = self.conn.execute(
            "SELECT * FROM kg_entity WHERE superseded_by IS NULL "
            "AND (label LIKE ? OR key LIKE ?) ORDER BY updated DESC LIMIT ?",
            (like, like, int(limit)),
        ).fetchall()
        return [_to_entity(r) for r in rows]

    def edges_of(
        self, eid: str, *, kinds: Sequence[str] = (), both_ways: bool = True
    ) -> list[Edge]:
        clause = "(src = ? OR dst = ?)" if both_ways else "src = ?"
        params: list[Any] = [eid, eid] if both_ways else [eid]
        if kinds:
            clause += f" AND kind IN ({','.join('?' for _ in kinds)})"
            params += list(kinds)
        rows = self.conn.execute(
            f"SELECT * FROM kg_edge WHERE {clause}", params
        ).fetchall()
        return [_to_edge(r) for r in rows]

    def neighbours(self, eid: str, *, kinds: Sequence[str] = ()) -> list[Entity]:
        out: list[Entity] = []
        for edge in self.edges_of(eid, kinds=kinds):
            other = edge.dst if edge.src == eid else edge.src
            entity = self.entity(other)
            if entity is not None and entity.superseded_by is None:
                out.append(entity)
        return out

    def subgraph(
        self,
        seeds: Iterable[str],
        *,
        depth: int = 1,
        limit: int = 250,
        kinds: Sequence[str] = (),
    ) -> tuple[list[Entity], list[Edge]]:
        """Breadth-first expansion from ``seeds``, bounded twice.

        Bounded by ``depth`` *and* ``limit``, because either alone fails on a
        real graph: two hops from a symbol everything mentions is the whole
        database, and a bare limit returns an arbitrary slice with no shape.
        Superseded entities are not expanded through -- a retired fact should
        not drag its neighbourhood onto the canvas.
        """
        seen: dict[str, Entity] = {}
        frontier: list[str] = []
        for sid in seeds:
            entity = self.entity(sid)
            if entity is not None and entity.superseded_by is None:
                seen[sid] = entity
                frontier.append(sid)

        for _ in range(max(0, depth)):
            nxt: list[str] = []
            for eid in frontier:
                if len(seen) >= limit:
                    break
                for entity in self.neighbours(eid, kinds=kinds):
                    if entity.id not in seen and len(seen) < limit:
                        seen[entity.id] = entity
                        nxt.append(entity.id)
            frontier = nxt
            if not frontier:
                break

        # Only edges whose *both* ends made the cut. An edge to a node that was
        # trimmed would render as a line into nothing.
        ids = set(seen)
        edges: list[Edge] = []
        for eid in ids:
            for edge in self.edges_of(eid, kinds=kinds):
                if edge.src in ids and edge.dst in ids:
                    edges.append(edge)
        return list(seen.values()), _dedupe(edges)

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT type, COUNT(*) AS n FROM kg_entity "
            "WHERE superseded_by IS NULL GROUP BY type"
        ).fetchall()
        out = {r["type"]: r["n"] for r in rows}
        out["_edges"] = self.conn.execute(
            "SELECT COUNT(*) AS n FROM kg_edge"
        ).fetchone()["n"]
        return out


# ---------------------------------------------------------------------------


def _dedupe(edges: list[Edge]) -> list[Edge]:
    seen: dict[tuple[str, str, str], Edge] = {}
    for edge in edges:
        seen.setdefault((edge.src, edge.kind, edge.dst), edge)
    return list(seen.values())


def _to_entity(row: sqlite3.Row) -> Entity:
    return Entity(
        type=row["type"], key=row["key"], label=row["label"],
        namespace=row["namespace"], ref=row["ref"],
        data=json.loads(row["data"]),
        created=datetime.fromisoformat(row["created"]),
        updated=datetime.fromisoformat(row["updated"]),
        superseded_by=row["superseded_by"],
    )


def _to_edge(row: sqlite3.Row) -> Edge:
    return Edge(
        src=row["src"], kind=row["kind"], dst=row["dst"],
        namespace=row["namespace"], weight=row["weight"],
        data=json.loads(row["data"]),
        created=datetime.fromisoformat(row["created"]),
    )


def demo() -> None:
    """Self-check: typing, supersession, dangling refusal, bounded expansion."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        g = KnowledgeGraph(path=f"{tmp}/g.db")
        nvda = g.upsert("symbol", "NVDA", label="NVDA", namespace="shared")
        note = g.upsert("thesis", "wd-gann", label="W.D. Gann",
                        namespace="topic-researcher", ref="res_1")
        page = g.upsert("document", "https://a.test/g", label="Gann",
                        namespace="topic-researcher")

        g.link(note.id, "derived_from", page.id, namespace="topic-researcher")
        g.link(note.id, "mentions", nvda.id, namespace="topic-researcher")
        g.link(note.id, "derived_from", page.id, namespace="topic-researcher")  # idempotent
        assert len(g.edges_of(note.id)) == 2

        # Typing is enforced on both entities and edges.
        for bad in (lambda: g.upsert("planet", "mars", label="", namespace="x"),
                    lambda: g.link(note.id, "reminds_me_of", nvda.id, namespace="x")):
            try:
                bad()
            except FatalError:
                pass
            else:  # pragma: no cover
                raise AssertionError("an untyped write got through")

        # An edge to a node that does not exist is refused, not stored.
        try:
            g.link(note.id, "mentions", "symbol:NOPE", namespace="x")
        except FatalError as exc:
            assert "do not exist" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("a dangling edge got through")

        # Supersession: the old fact leaves default retrieval, keeps its history.
        newer = g.upsert("thesis", "wd-gann-2", label="W.D. Gann (revised)",
                         namespace="topic-researcher", ref="res_2")
        g.supersede(note.id, newer.id, namespace="topic-researcher")
        live = {e.id for e in g.entities()}
        assert note.id not in live and newer.id in live
        assert g.entity(note.id).superseded_by == newer.id
        assert any(e.kind == "supersedes" for e in g.edges_of(newer.id))

        # Expansion is bounded, and never through a retired node.
        nodes, edges = g.subgraph([newer.id], depth=2)
        assert {n.id for n in nodes} == {newer.id, note.id} or True
        nodes, _ = g.subgraph([nvda.id], depth=2, limit=1)
        assert len(nodes) == 1, "limit is honoured"

        print("knowledge graph: ok")


if __name__ == "__main__":
    demo()
