# Spec: Genesis Markdown/70-Schemas/Watchlist Store.md
"""The trader's own symbol lists.

Not a source of record. Losing this database costs the trader their lists and
nothing else -- every symbol in it is a pointer at market data that lives
elsewhere. Same lifecycle as the Ask Genesis conversation store, and built the
same way: local SQLite under the memory dir, opened per request, ``ON DELETE
CASCADE`` from a list to its members.

A list has named sections (``grp``); a member carries its own ``sort`` so the
trader's arrangement survives a reload. Symbols are canonicalised through
``company.symbols.normalise`` -- rejected, never repaired -- but not checked
against a vendor here: a watchlist is tier-3 research scaffolding, and a typo
shows up as "no quote" in the panel rather than blocking the add.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genesis.company.symbols import normalise
from genesis.ids import new_id
from genesis.memory.db import connect, transaction

__all__ = ["WatchlistStore", "SCHEMA"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlists (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    created TEXT NOT NULL,
    sort    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS watchlist_members (
    id       TEXT PRIMARY KEY,
    list_id  TEXT NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    symbol   TEXT NOT NULL,
    grp      TEXT NOT NULL DEFAULT '',
    sort     INTEGER NOT NULL DEFAULT 0,
    added    TEXT NOT NULL,
    UNIQUE (list_id, symbol)
);

CREATE INDEX IF NOT EXISTS members_list ON watchlist_members(list_id, sort, id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class WatchlistStore:
    """Open per request, like every other read store -- see ``reads`` docstring."""

    def __init__(self, path: Path | str, *, conn: sqlite3.Connection | None = None) -> None:
        self.path = path
        self._conn = conn if conn is not None else connect(path)
        self._conn.executescript(SCHEMA)

    # -- writes --------------------------------------------------------------

    def create(self, name: str) -> str:
        name = (name or "").strip() or "Untitled"
        wid = new_id("wl")
        with transaction(self._conn) as tx:
            nxt = tx.execute("SELECT COALESCE(MAX(sort), -1) + 1 FROM watchlists").fetchone()[0]
            tx.execute(
                "INSERT INTO watchlists (id, name, created, sort) VALUES (?, ?, ?, ?)",
                (wid, name, _now(), nxt),
            )
        return wid

    def rename(self, list_id: str, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        with transaction(self._conn) as tx:
            cur = tx.execute("UPDATE watchlists SET name = ? WHERE id = ?", (name, list_id))
        return cur.rowcount > 0

    def delete(self, list_id: str) -> bool:
        with transaction(self._conn) as tx:
            cur = tx.execute("DELETE FROM watchlists WHERE id = ?", (list_id,))
        return cur.rowcount > 0

    def add(self, list_id: str, symbol: str, group: str = "") -> str:
        """Canonicalise and insert. Raises ``UnknownSymbol`` on an unusable ticker.

        Idempotent on ``(list_id, symbol)``: adding a symbol already on the list
        moves it into ``group`` rather than erroring.
        """
        sym = normalise(symbol)
        group = (group or "").strip()
        with transaction(self._conn) as tx:
            if tx.execute("SELECT 1 FROM watchlists WHERE id = ?", (list_id,)).fetchone() is None:
                raise KeyError(f"no watchlist {list_id}")
            nxt = tx.execute(
                "SELECT COALESCE(MAX(sort), -1) + 1 FROM watchlist_members WHERE list_id = ?",
                (list_id,),
            ).fetchone()[0]
            tx.execute(
                "INSERT INTO watchlist_members (id, list_id, symbol, grp, sort, added) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (list_id, symbol) DO UPDATE SET grp = excluded.grp",
                (new_id("wm"), list_id, sym, group, nxt, _now()),
            )
        return sym

    def remove(self, list_id: str, symbol: str) -> bool:
        with transaction(self._conn) as tx:
            cur = tx.execute(
                "DELETE FROM watchlist_members WHERE list_id = ? AND symbol = ?",
                (list_id, normalise(symbol)),
            )
        return cur.rowcount > 0

    def set_group(self, list_id: str, symbol: str, group: str) -> bool:
        with transaction(self._conn) as tx:
            cur = tx.execute(
                "UPDATE watchlist_members SET grp = ? WHERE list_id = ? AND symbol = ?",
                ((group or "").strip(), list_id, normalise(symbol)),
            )
        return cur.rowcount > 0

    # -- reads --------------------------------------------------------------

    def lists(self) -> list[dict[str, Any]]:
        """Every list, each with its members, ordered as the trader arranged them."""
        heads = self._conn.execute(
            "SELECT id, name, created FROM watchlists ORDER BY sort, id"
        ).fetchall()
        members = self._conn.execute(
            "SELECT list_id, symbol, grp, added FROM watchlist_members "
            "ORDER BY list_id, sort, id"
        ).fetchall()
        by_list: dict[str, list[dict[str, Any]]] = {}
        for m in members:
            by_list.setdefault(m["list_id"], []).append(
                {"symbol": m["symbol"], "group": m["grp"], "added": m["added"]}
            )
        return [
            {
                "id": h["id"],
                "name": h["name"],
                "created": h["created"],
                "members": by_list.get(h["id"], []),
            }
            for h in heads
        ]


if __name__ == "__main__":  # pragma: no cover - smoke check
    s = WatchlistStore(":memory:")
    a = s.create("Semis")
    s.add(a, "nvda")
    s.add(a, "AMD", group="laggards")
    s.add(a, "nvda", group="leaders")  # idempotent -> regroup
    assert [m["symbol"] for m in s.lists()[0]["members"]] == ["NVDA", "AMD"]
    assert s.lists()[0]["members"][0]["group"] == "leaders"
    assert s.remove(a, "amd") is True
    assert s.set_group(a, "nvda", "core") is True
    assert s.lists()[0]["members"][0]["group"] == "core"
    b = s.create("Energy")
    assert len(s.lists()) == 2
    assert s.delete(a) is True
    assert [x["name"] for x in s.lists()] == ["Energy"]
    try:
        s.add(b, "not a ticker!!")
    except Exception as exc:  # noqa: BLE001
        assert "ticker" in str(exc).lower()
    else:
        raise AssertionError("bad ticker was accepted")
    print("ok")
