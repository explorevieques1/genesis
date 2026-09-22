# Spec: Genesis Markdown/40-Memory/Obsidian Vault Schema.md · 20-Agents/Research/Research Family.md
"""The research directory: where what the agents found goes, and stays.

Two writes, one call, deliberately in this order.

**SQLite is the record.** It is what the UI lists, what the Idea Synthesizer
reads back as evidence, and what survives someone reorganising their vault. A
directory of markdown files is a lovely thing to read and a terrible thing to
query, and *"which notes about semis are still inside their half-life"* is a
query.

**The vault is the mirror.** Obsidian Vault Schema puts research under
`50-Research/` and says the human may edit it. So the file is written after the
row commits, and a failed file write degrades the result rather than losing the
research -- the note is still in the store, and the caller is told the mirror
is behind. The reverse order would mean a note on disk with no row, invisible
to everything that reads.

**Subjects supersede; they do not accumulate.** Researching Gann twice deepens
one note. :meth:`put` keeps the prior version in ``research_version`` rather
than overwriting silently, because a research directory where yesterday's read
vanished is one nobody trusts to check their own reasoning against.

**Every note is projected into the [[Knowledge Graph]].** One hook, here, rather
than three agents each remembering to do it -- an agent that forgets writes a
note the [[Research Canvas]] can never show, and the omission is invisible until
someone goes looking for a node that should exist. The projection is references
only: an entity per note, an entity per cited source, and `derived_from` edges
between them. The graph never gets a copy of the prose.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from genesis.errors import FatalError
from genesis.ids import new_id
from genesis.memory.db import connect, transaction
from genesis.memory.graph import KnowledgeGraph
from genesis.research.schema import ResearchNote, Source

__all__ = ["SCHEMA", "ResearchStore", "new_note_id"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_note (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    subject       TEXT NOT NULL,
    title         TEXT NOT NULL,
    created       TEXT NOT NULL,
    created_by    TEXT NOT NULL,
    summary       TEXT NOT NULL DEFAULT '',
    body          TEXT NOT NULL DEFAULT '',
    sources       TEXT NOT NULL DEFAULT '[]',
    tags          TEXT NOT NULL DEFAULT '[]',
    data          TEXT NOT NULL DEFAULT '{}',
    half_life_hours REAL NOT NULL,
    confidence    REAL NOT NULL,
    degraded      INTEGER NOT NULL DEFAULT 0,
    caveats       TEXT NOT NULL DEFAULT '[]',
    trace_id      TEXT,
    vault_path    TEXT NOT NULL,
    -- Set when a newer note took this subject over. The old read stays
    -- readable; it just stops being the current one.
    superseded_by TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS research_current
    ON research_note (kind, subject) WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS research_by_time ON research_note (created DESC);

-- Full-text over the parts a person actually searches. `content=` keeps the
-- text in the base table rather than duplicating it, so the index cannot drift
-- from the note.
CREATE VIRTUAL TABLE IF NOT EXISTS research_fts USING fts5(
    title, subject, summary, body,
    content='research_note', content_rowid='rowid', tokenize='porter'
);
CREATE TRIGGER IF NOT EXISTS research_fts_ins AFTER INSERT ON research_note BEGIN
    INSERT INTO research_fts(rowid, title, subject, summary, body)
    VALUES (new.rowid, new.title, new.subject, new.summary, new.body);
END;
CREATE TRIGGER IF NOT EXISTS research_fts_del AFTER DELETE ON research_note BEGIN
    INSERT INTO research_fts(research_fts, rowid, title, subject, summary, body)
    VALUES ('delete', old.rowid, old.title, old.subject, old.summary, old.body);
END;
"""


def new_note_id() -> str:
    return new_id("res")


@dataclass
class ResearchStore:
    """The queryable half of the research directory."""

    path: Path | str = "~/.genesis/memory/research.db"
    #: Where the markdown mirror is written. The same vault root the Obsidian
    #: MCP server is pointed at in `default_servers.yaml`.
    vault: Path | str | None = "~/GenesisVault"
    _conn: sqlite3.Connection | None = field(default=None, repr=False)
    #: The Knowledge Graph every note is projected into. ``None`` disables the
    #: projection -- used by tests that are about the directory alone, never in
    #: the daemon, where a note that reaches no graph is a note the canvas
    #: cannot show.
    graph: KnowledgeGraph | None = None
    #: Mirror failures, reported to whoever asks rather than raised. A vault on
    #: an unmounted drive must not lose research.
    mirror_notes: list[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._conn = connect(self.path)
        self._conn.executescript(SCHEMA)
        if self.graph is None and str(self.path) != ":memory:":
            self.graph = KnowledgeGraph(
                path=Path(self.path).expanduser().parent / "graph.db"
            )

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("ResearchStore is closed")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def put(self, note: ResearchNote, *, mirror: bool = True) -> ResearchNote:
        """Store a note, superseding any current note on the same subject.

        Idempotent on id, per the Agent Contract: the same task re-run writes
        the same row and does not supersede itself.
        """
        with transaction(self.conn) as conn:
            existing = conn.execute(
                "SELECT id FROM research_note WHERE id = ?", (note.id,)
            ).fetchone()
            if existing:
                return note
            conn.execute(
                "UPDATE research_note SET superseded_by = ? "
                "WHERE kind = ? AND subject = ? AND superseded_by IS NULL",
                (note.id, note.kind, note.subject),
            )
            conn.execute(
                """
                INSERT INTO research_note (
                    id, kind, subject, title, created, created_by, summary, body,
                    sources, tags, data, half_life_hours, confidence, degraded,
                    caveats, trace_id, vault_path
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    note.id, note.kind, note.subject, note.title,
                    note.created.isoformat(), note.created_by, note.summary,
                    note.body,
                    json.dumps([s.model_dump(mode="json") for s in note.sources]),
                    json.dumps(list(note.tags)),
                    json.dumps(note.data, default=str),
                    note.half_life_hours, note.confidence, int(note.degraded),
                    json.dumps(list(note.caveats)), note.trace_id,
                    note.vault_path(),
                ),
            )
        if mirror:
            self.mirror(note)
        self.project(note)
        return note

    #: How a note's kind becomes a Knowledge Graph entity type. A topic note is
    #: a `thesis` because that is what a body of research *is* in the graph's
    #: vocabulary -- a claim, with evidence pointing at it.
    _ENTITY_TYPE = {
        "topic": "thesis", "idea": "idea", "regime": "regime", "symbol": "symbol",
        "finding": "thesis",
    }

    def project(self, note: ResearchNote) -> None:
        """Record the note, its sources and their links in the graph.

        Never raises. The note is already committed, and a graph that will not
        open must not turn a successful research pass into a failed one -- the
        failure is collected alongside the vault mirror's, where the caller
        already looks for degradations.
        """
        if self.graph is None:
            return
        try:
            self._project(note)
        except Exception as exc:  # noqa: BLE001
            self.mirror_notes.append(
                f"knowledge graph write failed for {note.id}: {exc}"
            )

    def _project(self, note: ResearchNote) -> None:
        graph = self.graph
        assert graph is not None
        who = note.created_by
        subject = graph.upsert(
            self._ENTITY_TYPE.get(note.kind, "thesis"),
            note.subject,
            label=note.title,
            namespace=who,
            # The reference, not the content. Following this reaches the note.
            ref=note.id,
            data={"kind": note.kind, "degraded": note.degraded,
                  "confidence": note.confidence, "summary": note.summary[:280]},
        )

        for source in note.sources:
            document = graph.upsert(
                "document", source.url,
                label=source.title or source.url,
                namespace=who,
                ref=source.url,
                data={"publisher": source.publisher, "flags": list(source.flags)},
            )
            graph.link(subject.id, "derived_from", document.id, namespace=who)

        # An idea points at the symbol it is about and at the notes it was built
        # from. Both are claims the synthesizer already made and cited -- this
        # copies them into the graph, it does not infer them. A finding does the
        # same: the company it resolved to, and the note its agent wrote.
        if note.kind in ("idea", "finding"):
            symbol = str(note.data.get("symbol") or "").upper()
            if symbol:
                node = graph.upsert("symbol", symbol, label=symbol, namespace="shared")
                graph.link(subject.id, "applies_to", node.id, namespace=who)
            for cited in note.data.get("evidence", []) or []:
                other = self.note(str(cited))
                if other is None:
                    continue
                target = graph.entity(
                    f"{self._ENTITY_TYPE.get(other.kind, 'thesis')}:{other.subject}"
                )
                if target is not None:
                    graph.link(subject.id, "derived_from", target.id, namespace=who)

    def backfill(self) -> int:
        """Project every note already in the directory. Idempotent.

        For notes written before the graph existed. Running it twice is free:
        every write in :meth:`_project` upserts on a stable key.
        """
        notes = self.notes(limit=1000)
        for note in notes:
            self.project(note)
        return len(notes)

    def mirror(self, note: ResearchNote) -> str | None:
        """Write the markdown file. Returns the path, or None if it failed.

        Never raises. The row is already committed; a vault that is not there
        is a degraded mirror, not lost research.
        """
        if self.vault is None:
            return None
        try:
            target = Path(self.vault).expanduser() / note.vault_path()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(note.markdown(), encoding="utf-8")
            return str(target)
        except OSError as exc:
            self.mirror_notes.append(f"vault mirror failed for {note.id}: {exc}")
            return None

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def note(self, note_id: str) -> ResearchNote | None:
        row = self.conn.execute(
            "SELECT * FROM research_note WHERE id = ?", (note_id,)
        ).fetchone()
        return _to_note(row) if row else None

    def current(self, kind: str, subject: str) -> ResearchNote | None:
        """The live note on a subject, ignoring superseded versions."""
        row = self.conn.execute(
            "SELECT * FROM research_note WHERE kind = ? AND subject = ? "
            "AND superseded_by IS NULL",
            (kind, subject),
        ).fetchone()
        return _to_note(row) if row else None

    def by_trace(self, trace_id: str) -> list[ResearchNote]:
        """Everything one prompt produced -- the prompt tree's leaves, oldest first."""
        rows = self.conn.execute(
            "SELECT * FROM research_note WHERE trace_id = ? ORDER BY created", (trace_id,)
        ).fetchall()
        return [_to_note(r) for r in rows]

    def findings(self, symbol: str) -> list[ResearchNote]:
        """The live finding per intent for one company -- its dossier."""
        rows = self.conn.execute(
            "SELECT * FROM research_note WHERE kind = 'finding' AND superseded_by IS NULL "
            "AND subject LIKE ? ESCAPE '\\' ORDER BY subject",
            (symbol.upper().replace("%", r"\%").replace("_", r"\_") + ":%",),
        ).fetchall()
        return [_to_note(r) for r in rows]

    def history(self, kind: str, subject: str) -> list[ResearchNote]:
        """Every version of one subject, newest first."""
        rows = self.conn.execute(
            "SELECT * FROM research_note WHERE kind = ? AND subject = ? "
            "ORDER BY created DESC",
            (kind, subject),
        ).fetchall()
        return [_to_note(r) for r in rows]

    def notes(
        self,
        *,
        kind: str | None = None,
        subject: str | None = None,
        query: str | None = None,
        since: datetime | None = None,
        include_superseded: bool = False,
        limit: int = 100,
    ) -> list[ResearchNote]:
        """The directory listing, newest first.

        ``query`` searches the FTS index. A query that SQLite's FTS syntax
        rejects (a bare quote, a stray operator -- the ordinary result of
        typing into a search box) falls back to a LIKE scan rather than
        raising: a search box that errors on an apostrophe is a broken search
        box.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if not include_superseded:
            clauses.append("n.superseded_by IS NULL")
        if kind:
            clauses.append("n.kind = ?")
            params.append(kind)
        if subject:
            clauses.append("n.subject = ?")
            params.append(subject)
        if since:
            clauses.append("n.created >= ?")
            params.append(since.isoformat())

        joined = ""
        if query and query.strip():
            try:
                return self._search(query.strip(), clauses, params, limit)
            except sqlite3.OperationalError:
                clauses.append("(n.title LIKE ? OR n.summary LIKE ? OR n.body LIKE ?)")
                like = f"%{query.strip()}%"
                params += [like, like, like]

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT n.* FROM research_note n {joined} {where} "
            f"ORDER BY n.created DESC LIMIT {int(limit)}",
            params,
        ).fetchall()
        return [_to_note(r) for r in rows]

    def _search(
        self, query: str, clauses: list[str], params: list[Any], limit: int
    ) -> list[ResearchNote]:
        where = " AND ".join(["research_fts MATCH ?", *clauses])
        rows = self.conn.execute(
            "SELECT n.* FROM research_fts f JOIN research_note n ON n.rowid = f.rowid "
            f"WHERE {where} ORDER BY bm25(research_fts) LIMIT {int(limit)}",
            [query, *params],
        ).fetchall()
        return [_to_note(r) for r in rows]

    def evidence(
        self, *, kinds: Sequence[str] = ("regime", "topic", "symbol"), limit: int = 40
    ) -> list[ResearchNote]:
        """Live notes worth reasoning over, heaviest first.

        Sorted by :meth:`ResearchNote.weight` rather than by time, because the
        Idea Synthesizer wants the most load-bearing evidence and a fresh note
        with a two-hour half-life outranks nothing after three hours.
        """
        marks = ",".join("?" for _ in kinds)
        rows = self.conn.execute(
            f"SELECT * FROM research_note WHERE superseded_by IS NULL "
            f"AND kind IN ({marks}) ORDER BY created DESC LIMIT 200",
            list(kinds),
        ).fetchall()
        notes = [_to_note(r) for r in rows]
        notes.sort(key=lambda n: n.weight(), reverse=True)
        return notes[:limit]

    def subjects(self, kind: str | None = None) -> list[dict[str, Any]]:
        """The directory's folders: one row per live subject."""
        where = "WHERE superseded_by IS NULL" + (" AND kind = ?" if kind else "")
        rows = self.conn.execute(
            f"SELECT kind, subject, title, created, confidence, degraded "
            f"FROM research_note {where} ORDER BY created DESC",
            [kind] if kind else [],
        ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT kind, COUNT(*) AS n FROM research_note "
            "WHERE superseded_by IS NULL GROUP BY kind"
        ).fetchall()
        return {r["kind"]: r["n"] for r in rows}


def _to_note(row: sqlite3.Row) -> ResearchNote:
    try:
        return ResearchNote(
            id=row["id"],
            kind=row["kind"],
            title=row["title"],
            subject=row["subject"],
            created=datetime.fromisoformat(row["created"]),
            created_by=row["created_by"],
            summary=row["summary"],
            body=row["body"],
            sources=[Source(**s) for s in json.loads(row["sources"])],
            tags=json.loads(row["tags"]),
            data=json.loads(row["data"]),
            half_life_hours=row["half_life_hours"],
            confidence=row["confidence"],
            degraded=bool(row["degraded"]),
            caveats=json.loads(row["caveats"]),
            trace_id=row["trace_id"],
        )
    except Exception as exc:  # noqa: BLE001
        raise FatalError(f"corrupt research note {row['id']!r}: {exc}") from exc


def demo() -> None:
    """Self-check: supersession, half-life ordering, search, mirror."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        store = ResearchStore(path=f"{tmp}/r.db", vault=f"{tmp}/vault")
        first = ResearchNote(
            id="res_1", kind="topic", title="W.D. Gann", subject="wd-gann",
            created_by="topic-researcher", summary="Time and price.",
            body="Gann worked on square-of-nine geometry.",
            sources=[Source(url="https://example.com/gann", title="Gann")],
        )
        store.put(first)
        assert store.current("topic", "wd-gann").id == "res_1"
        assert (Path(tmp) / "vault/50-Research/themes/wd-gann.md").exists()

        store.put(first)  # idempotent: same id, no supersession
        assert len(store.history("topic", "wd-gann")) == 1

        second = first.model_copy(update={"id": "res_2", "body": "Deeper."})
        store.put(second)
        assert store.current("topic", "wd-gann").id == "res_2"
        assert len(store.notes()) == 1, "superseded notes stay out of the listing"
        assert len(store.history("topic", "wd-gann")) == 2

        assert [n.id for n in store.notes(query="square-of-nine")] == []
        assert [n.id for n in store.notes(query="Deeper")] == ["res_2"]
        # A query FTS cannot parse must not raise.
        assert store.notes(query='gann"') is not None

        # Half-life ordering: a fresh, short-lived note outranks a stale one.
        stale = ResearchNote(
            id="res_3", kind="regime", title="Regime", subject="2020-01-01",
            created_by="market-analyst", created=datetime(2020, 1, 1, tzinfo=UTC),
            confidence=0.9, half_life_hours=24,
        )
        store.put(stale, mirror=False)
        assert store.evidence()[0].id == "res_2"
        assert stale.stale() and stale.weight() < 0.01

        # A degraded note that claims high confidence is refused by the type.
        try:
            ResearchNote(
                id="res_4", kind="regime", title="x", subject="y",
                created_by="market-analyst", degraded=True, confidence=0.9,
                caveats=["breadth missing"],
            )
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("degraded note escaped the confidence cap")

        print("research store: ok")


if __name__ == "__main__":
    demo()
