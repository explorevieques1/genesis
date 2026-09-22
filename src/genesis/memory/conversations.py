# Spec: Genesis Markdown/70-Schemas/Conversation Store.md
"""Saved conversations for the Ask Genesis surface.

This is **not** the Episodic Log. The log is a forever audit trail and is
append-only by database trigger; a conversation is the trader's own chat
history and they get to delete it. Different lifecycle, so a different store --
the same reasoning that keeps the canvas arrangement out of the knowledge
graph.

What is kept is deliberately thin: the text of each turn plus the fields the
command layer already returns (``command``, ``detail``, ``data``, ``trace``,
``ok``). Nothing here is a source of record -- every answer was already emitted
to the bus and, in Phase 1, the Episodic Log. Losing this database costs the
trader their scrollback and nothing else.

Only turns that arrive with a ``conversation`` id are stored, which in practice
means the Ask Genesis panel. A spoken command or a Cmd-K one belongs to no
conversation and is not written here.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genesis.ids import new_id
from genesis.memory.db import connect, transaction

__all__ = ["ConversationStore", "SCHEMA"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id       TEXT PRIMARY KEY,
    title    TEXT NOT NULL DEFAULT '',
    created  TEXT NOT NULL,
    updated  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    ts           TEXT NOT NULL,
    role         TEXT NOT NULL,           -- 'operator' | 'genesis'
    text         TEXT NOT NULL,
    ok           INTEGER,                 -- genesis turns only
    command      TEXT,
    detail       TEXT,
    data         TEXT,                    -- small JSON, inline
    trace        TEXT
);

CREATE INDEX IF NOT EXISTS turns_conversation ON turns(conversation, id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _title_from(text: str) -> str:
    """First line of the opening message, trimmed. Good enough for a rail label."""
    line = text.strip().splitlines()[0] if text.strip() else "New conversation"
    return line[:80]


class ConversationStore:
    """Open per request, like every other read store -- see ``reads`` docstring."""

    def __init__(self, path: Path | str, *, conn: sqlite3.Connection | None = None) -> None:
        self.path = path
        self._conn = conn if conn is not None else connect(path)
        self._conn.executescript(SCHEMA)

    # -- writes ----------------------------------------------------------

    def append(
        self,
        conversation_id: str | None,
        *,
        operator_text: str,
        reply: dict[str, Any],
    ) -> str:
        """Record one exchange. Creates the conversation if it does not exist.

        ``conversation_id`` of ``None`` mints a fresh one, so the panel can open
        a chat without a round trip just to get an id.
        """
        cid = conversation_id or new_id("cv")
        now = _now()
        with transaction(self._conn) as tx:
            row = tx.execute(
                "SELECT id FROM conversations WHERE id = ?", (cid,)
            ).fetchone()
            if row is None:
                tx.execute(
                    "INSERT INTO conversations (id, title, created, updated) "
                    "VALUES (?, ?, ?, ?)",
                    (cid, _title_from(operator_text), now, now),
                )
            else:
                tx.execute(
                    "UPDATE conversations SET updated = ? WHERE id = ?", (now, cid)
                )
            tx.execute(
                "INSERT INTO turns (conversation, ts, role, text) VALUES (?, ?, 'operator', ?)",
                (cid, now, operator_text),
            )
            tx.execute(
                "INSERT INTO turns "
                "(conversation, ts, role, text, ok, command, detail, data, trace) "
                "VALUES (?, ?, 'genesis', ?, ?, ?, ?, ?, ?)",
                (
                    cid, now,
                    str(reply.get("spoken") or ""),
                    1 if reply.get("ok") else 0,
                    reply.get("command"),
                    reply.get("detail"),
                    json.dumps(reply["data"]) if reply.get("data") else None,
                    reply.get("trace"),
                ),
            )
        return cid

    def delete(self, conversation_id: str) -> bool:
        with transaction(self._conn) as tx:
            cur = tx.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
        return cur.rowcount > 0

    # -- reads ---------------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT c.id, c.title, c.updated, COUNT(t.id) AS turns "
            "FROM conversations c LEFT JOIN turns t ON t.conversation = c.id "
            # `id` breaks ties: it is a ULID, so it sorts in creation order, and
            # two turns appended inside the same millisecond still order
            # sensibly rather than arbitrarily.
            "GROUP BY c.id ORDER BY c.updated DESC, c.id DESC"
        ).fetchall()
        return [
            {"id": r["id"], "title": r["title"], "updated": r["updated"], "turns": r["turns"]}
            for r in rows
        ]

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        head = self._conn.execute(
            "SELECT id, title, created, updated FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if head is None:
            return None
        turns = self._conn.execute(
            "SELECT ts, role, text, ok, command, detail, data, trace "
            "FROM turns WHERE conversation = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
        return {
            "id": head["id"],
            "title": head["title"],
            "created": head["created"],
            "updated": head["updated"],
            "turns": [
                {
                    "ts": t["ts"],
                    "role": t["role"],
                    "text": t["text"],
                    "ok": None if t["ok"] is None else bool(t["ok"]),
                    "command": t["command"],
                    "detail": t["detail"],
                    "data": json.loads(t["data"]) if t["data"] else None,
                    "trace": t["trace"],
                }
                for t in turns
            ],
        }


if __name__ == "__main__":  # pragma: no cover - smoke check
    store = ConversationStore(":memory:")
    cid = store.append(None, operator_text="why is NVDA down",
                       reply={"ok": True, "spoken": "Off 2% with the sector.", "command": "analyst.reasoned"})
    store.append(cid, operator_text="and AMD?", reply={"ok": True, "spoken": "Similar.", "command": "analyst.reasoned"})
    assert [c["turns"] for c in store.list()] == [4]
    got = store.get(cid)
    assert got is not None and len(got["turns"]) == 4
    assert got["turns"][0]["role"] == "operator"
    assert store.delete(cid) is True
    assert store.list() == []
    assert store.get(cid) is None
    print("ok")
