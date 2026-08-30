# Spec: Genesis Markdown/40-Memory/Episodic Log.md
"""The Episodic Log: append-only, everything that happened, forever.

This is how *"why did it do that?"* gets answered three weeks later, and in a
system that trades money that question will be asked. Two properties carry the
whole design:

**Append-only, enforced at the database level.** Not by convention -- by
``BEFORE UPDATE`` and ``BEFORE DELETE`` triggers that ``RAISE(ABORT)``. A
convention holds until someone writes ``UPDATE`` at 2am; a trigger holds
always. A correction is a new row that supersedes the old one via
``supersedes``, never an edit.

**Tracing.** ``trace_id`` links everything descending from one utterance or
event; ``parent_id`` gives the tree within it. One query reconstructs the causal
chain from the words spoken to the fill.

Rows stay small so the log scans fast when it holds millions of them. A large
payload goes to the blob store and the row keeps a ``payload_ref``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genesis.ids import new_id
from genesis.memory.db import connect, transaction

__all__ = ["Entry", "EpisodicLog", "SCHEMA"]

# Kinds are open-ended by design -- new components add their own -- but these
# are the ones Phase 1 writes.
SCHEMA = """
CREATE TABLE IF NOT EXISTS episodic (
    id          TEXT PRIMARY KEY,          -- ULID: sorts in creation order
    ts          TEXT NOT NULL,             -- ISO-8601 UTC, millisecond precision
    trace_id    TEXT NOT NULL,
    parent_id   TEXT,
    actor       TEXT NOT NULL,             -- agent id, 'daemon', 'bus', 'user'
    kind        TEXT NOT NULL,             -- noun.verb, e.g. task.claimed
    summary     TEXT,
    payload     TEXT,                      -- small JSON, inline
    payload_ref TEXT,                      -- blob id, for large payloads
    cost        TEXT,                      -- JSON: llm_tokens, tool_calls, wall_ms
    degraded    INTEGER NOT NULL DEFAULT 0,
    supersedes  TEXT REFERENCES episodic(id)
);

-- The queries the note names: by trace, by time, by actor, by kind.
CREATE INDEX IF NOT EXISTS episodic_trace  ON episodic(trace_id);
CREATE INDEX IF NOT EXISTS episodic_ts     ON episodic(ts);
CREATE INDEX IF NOT EXISTS episodic_actor  ON episodic(actor, ts);
CREATE INDEX IF NOT EXISTS episodic_kind   ON episodic(kind, ts);

-- Append-only, enforced by the database rather than by convention.
CREATE TRIGGER IF NOT EXISTS episodic_no_update
BEFORE UPDATE ON episodic
BEGIN
    SELECT RAISE(ABORT, 'episodic log is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS episodic_no_delete
BEFORE DELETE ON episodic
BEGIN
    SELECT RAISE(ABORT, 'episodic log is append-only: DELETE forbidden');
END;
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Entry:
    """One row of the log."""

    id: str
    ts: str
    trace_id: str
    actor: str
    kind: str
    parent_id: str | None = None
    summary: str | None = None
    payload: dict[str, Any] | None = None
    payload_ref: str | None = None
    cost: dict[str, Any] | None = None
    degraded: bool = False
    supersedes: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Entry:
        return cls(
            id=row["id"],
            ts=row["ts"],
            trace_id=row["trace_id"],
            actor=row["actor"],
            kind=row["kind"],
            parent_id=row["parent_id"],
            summary=row["summary"],
            payload=json.loads(row["payload"]) if row["payload"] else None,
            payload_ref=row["payload_ref"],
            cost=json.loads(row["cost"]) if row["cost"] else None,
            degraded=bool(row["degraded"]),
            supersedes=row["supersedes"],
        )


class EpisodicLog:
    """Append and query. There is deliberately no update or delete method.

    ``scrub`` is the secret redactor from :mod:`genesis.observability`; payloads
    pass through it before they are persisted, because the log is forever and a
    key written into it is a key that cannot be removed.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        conn: sqlite3.Connection | None = None,
        scrub: Any = None,
    ) -> None:
        self.path = path
        self._conn = conn if conn is not None else connect(path)
        self._scrub = scrub or (lambda value: value)
        # executescript() issues its own COMMIT before running, so it cannot sit
        # inside an explicit transaction. The DDL is all IF NOT EXISTS, so it is
        # idempotent and safe to run unwrapped on every open.
        self._conn.executescript(SCHEMA)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    # -- write -------------------------------------------------------------

    def append(
        self,
        *,
        actor: str,
        kind: str,
        trace_id: str,
        parent_id: str | None = None,
        summary: str | None = None,
        payload: dict[str, Any] | None = None,
        payload_ref: str | None = None,
        cost: dict[str, Any] | None = None,
        degraded: bool = False,
        supersedes: str | None = None,
    ) -> str:
        """Append one entry and return its id.

        ``actor``, ``kind`` and ``trace_id`` are required with no defaults, for
        the same reason the structured log requires them: a row missing any of
        the three cannot be placed in the causal chain, and a chain with a hole
        in it is not an audit trail.
        """
        entry_id = new_id("ep")
        with transaction(self._conn) as tx:
            tx.execute(
                """
                INSERT INTO episodic
                    (id, ts, trace_id, parent_id, actor, kind, summary,
                     payload, payload_ref, cost, degraded, supersedes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    _now(),
                    trace_id,
                    parent_id,
                    actor,
                    kind,
                    summary,
                    json.dumps(self._scrub(payload)) if payload else None,
                    payload_ref,
                    json.dumps(cost) if cost else None,
                    int(degraded),
                    supersedes,
                ),
            )
        return entry_id

    def append_in(
        self,
        tx: sqlite3.Connection,
        *,
        actor: str,
        kind: str,
        trace_id: str,
        parent_id: str | None = None,
        summary: str | None = None,
        payload: dict[str, Any] | None = None,
        degraded: bool = False,
    ) -> str:
        """Append inside a caller's open transaction.

        This is what makes "every state transition is in the log" true rather
        than aspirational: the Task Bus writes the state change and its log
        entry in **one** transaction, so a crash between them is impossible.
        A separate ``append`` call would leave a window where the task moved and
        the log does not say so.
        """
        entry_id = new_id("ep")
        tx.execute(
            """
            INSERT INTO episodic
                (id, ts, trace_id, parent_id, actor, kind, summary, payload, degraded)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                _now(),
                trace_id,
                parent_id,
                actor,
                kind,
                summary,
                json.dumps(self._scrub(payload)) if payload else None,
                int(degraded),
            ),
        )
        return entry_id

    # -- read --------------------------------------------------------------

    def get(self, entry_id: str) -> Entry | None:
        row = self._conn.execute(
            "SELECT * FROM episodic WHERE id = ?", (entry_id,)
        ).fetchone()
        return Entry.from_row(row) if row else None

    def by_trace(self, trace_id: str) -> list[Entry]:
        """Everything that happened because of one utterance or event.

        Ordered by ``rowid`` -- SQLite's monotonic insertion counter -- not by
        ``id`` or ``ts``. Both of those have millisecond resolution, and two
        entries written in the same millisecond would then be ordered by the
        ULID's random bits, which can put an effect before its cause. For a log
        whose entire job is causal reconstruction, "usually chronological" is
        not good enough.
        """
        rows = self._conn.execute(
            "SELECT * FROM episodic WHERE trace_id = ? ORDER BY rowid", (trace_id,)
        ).fetchall()
        return [Entry.from_row(r) for r in rows]

    def by_actor(self, actor: str, *, limit: int = 100) -> list[Entry]:
        rows = self._conn.execute(
            "SELECT * FROM episodic WHERE actor = ? ORDER BY ts DESC LIMIT ?",
            (actor, limit),
        ).fetchall()
        return [Entry.from_row(r) for r in rows]

    def by_kind(self, kind: str, *, limit: int = 100) -> list[Entry]:
        rows = self._conn.execute(
            "SELECT * FROM episodic WHERE kind = ? ORDER BY ts DESC LIMIT ?",
            (kind, limit),
        ).fetchall()
        return [Entry.from_row(r) for r in rows]

    def between(self, start: str, end: str) -> list[Entry]:
        rows = self._conn.execute(
            "SELECT * FROM episodic WHERE ts >= ? AND ts < ? ORDER BY rowid",
            (start, end),
        ).fetchall()
        return [Entry.from_row(r) for r in rows]

    def trace_tree(self, trace_id: str) -> dict[str | None, list[Entry]]:
        """Entries of a trace grouped by ``parent_id``, for rendering the tree."""
        tree: dict[str | None, list[Entry]] = {}
        for entry in self.by_trace(trace_id):
            tree.setdefault(entry.parent_id, []).append(entry)
        return tree

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM episodic").fetchone()[0])

    def __iter__(self) -> Iterator[Entry]:
        for row in self._conn.execute("SELECT * FROM episodic ORDER BY rowid"):
            yield Entry.from_row(row)
