# Spec: Genesis Markdown/10-Architecture/Markup Spec.md
"""Where specs live: immutable, lineage-linked, queryable.

Markup Spec.md's five capabilities -- re-render, diff, watch, query, audit --
are all statements about *storage*, not about drawing. An image on disk supports
none of them; a spec in a table supports all five, and this module is the table.

Immutability is enforced the way the Episodic Log enforces append-only: with
``BEFORE UPDATE`` and ``BEFORE DELETE`` triggers that ``RAISE(ABORT)``, not with
a convention. A re-mark is a new row whose ``parent`` points at the old one, so
the chain of how a read of a symbol evolved is preserved by the database rather
than by everyone remembering to preserve it.

Three queries the rest of the system actually runs:

``active``
    Every spec whose timeframe relevance window has not expired. This is
    Agent — Level Watcher's watch list, and it is a query rather than a
    subscription so the watcher can rebuild it from cold after a crash.
``lineage``
    Walk ``parent`` backwards. *"How has my read of NVDA evolved?"*
``latest``
    The current spec for a symbol and timeframe -- the parent of the next
    re-mark.

SQLite rather than the market data store's DuckDB, deliberately: a spec is a
*belief*, it belongs with the Memory Fabric, and Market Data Plane.md draws that
line explicitly -- the fabric holds what the system believes, the market store
holds what the world did.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from genesis.charting.spec import MarkupSpec
from genesis.charting.timeframes import resolve
from genesis.memory.db import connect, transaction

__all__ = ["SCHEMA", "SpecStore"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS markup_spec (
    id          TEXT PRIMARY KEY,
    created     TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    trace_id    TEXT,
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    parent      TEXT REFERENCES markup_spec(id),
    degraded    INTEGER NOT NULL DEFAULT 0,
    expires_at  TEXT NOT NULL,             -- derived from the timeframe's window
    render_path TEXT,
    render_hash TEXT,
    body        TEXT NOT NULL              -- the whole spec as JSON
);

CREATE INDEX IF NOT EXISTS markup_symbol ON markup_spec(symbol, timeframe, as_of);
CREATE INDEX IF NOT EXISTS markup_parent ON markup_spec(parent);
CREATE INDEX IF NOT EXISTS markup_expiry ON markup_spec(expires_at);

-- Immutable, enforced by the database. A spec that can be edited breaks
-- diff_spec, breaks the vision cache keyed on its id, and breaks the audit
-- claim that the chart in a journal entry is the one the agent reasoned about.
CREATE TRIGGER IF NOT EXISTS markup_no_update
BEFORE UPDATE OF id, symbol, timeframe, as_of, parent, body ON markup_spec
BEGIN
    SELECT RAISE(ABORT, 'markup specs are immutable: re-mark instead of editing');
END;

CREATE TRIGGER IF NOT EXISTS markup_no_delete
BEFORE DELETE ON markup_spec
BEGIN
    SELECT RAISE(ABORT, 'markup specs are immutable: DELETE forbidden');
END;

-- The vision interpretation cache. Keyed on the spec id because that is what
-- Agent — Pattern Recognition's cost control requires: "the same spec never
-- gets read twice". A row here is a vision call that does not happen.
CREATE TABLE IF NOT EXISTS vision_read (
    spec_id     TEXT PRIMARY KEY REFERENCES markup_spec(id),
    render_hash TEXT NOT NULL,
    created     TEXT NOT NULL,
    body        TEXT NOT NULL
);
"""


@dataclass
class SpecStore:
    """Durable home for markup specs and their vision interpretations."""

    path: Path | str = "~/.genesis/memory/charting.db"
    _conn: sqlite3.Connection | None = None

    def __post_init__(self) -> None:
        self._conn = connect(self.path)
        # executescript issues its own COMMIT, so it must not be wrapped in an
        # explicit transaction -- doing so leaves nothing to commit and raises.
        self._conn.executescript(SCHEMA)

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("SpecStore is closed")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- writing -----------------------------------------------------------

    def put(self, spec: MarkupSpec) -> MarkupSpec:
        """Store a spec. Storing the same id twice is a no-op, not an error.

        Idempotent because Agent Contract requires it: *"same task id, same
        result, no duplicated side effects."* A retried task must not fail on
        the primary key of work it already did.
        """
        body = json.dumps(spec.to_dict(), sort_keys=True, separators=(",", ":"))
        with transaction(self.conn) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO markup_spec
                    (id, created, created_by, trace_id, symbol, timeframe, as_of,
                     parent, degraded, expires_at, render_path, render_hash, body)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    spec.id,
                    spec.created.isoformat(),
                    spec.created_by,
                    spec.trace_id,
                    spec.symbol,
                    spec.timeframe,
                    spec.as_of.isoformat(),
                    spec.parent,
                    int(spec.degraded),
                    _expiry(spec).isoformat(),
                    spec.render.output,
                    spec.render.render_hash,
                    body,
                ),
            )
        return spec

    def cache_vision(self, spec_id: str, render_hash: str, body: dict[str, Any]) -> None:
        with transaction(self.conn) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO vision_read "
                "(spec_id, render_hash, created, body) VALUES (?, ?, ?, ?)",
                (
                    spec_id, render_hash, datetime.now(UTC).isoformat(),
                    json.dumps(body, sort_keys=True),
                ),
            )

    def vision(self, spec_id: str, render_hash: str | None = None) -> dict[str, Any] | None:
        """A cached interpretation, but only if the render still matches.

        The hash check is the point. A cache keyed on the spec id alone would
        keep serving a reading of an image that no longer exists -- and a
        nondeterministic renderer would then invalidate the cache silently,
        which is the failure genesis-charting-mcp.md warns about by name.
        """
        row = self.conn.execute(
            "SELECT render_hash, body FROM vision_read WHERE spec_id = ?", (spec_id,)
        ).fetchone()
        if row is None:
            return None
        if render_hash is not None and row["render_hash"] != render_hash:
            return None
        return json.loads(row["body"])

    # -- reading -----------------------------------------------------------

    def get(self, spec_id: str) -> MarkupSpec | None:
        row = self.conn.execute(
            "SELECT body FROM markup_spec WHERE id = ?", (spec_id,)
        ).fetchone()
        return MarkupSpec.model_validate_json(row["body"]) if row else None

    def latest(self, symbol: str, timeframe: str) -> MarkupSpec | None:
        """The current spec: the leaf of the lineage, not merely the newest row.

        Ordering by timestamp alone is not enough, and the failure is subtle. A
        re-mark keeps its parent's ``as_of`` -- it is a new opinion about the
        same bars -- so parent and child tie there, and the tie falls to the id.
        Ids are ULIDs, whose ordering *within one millisecond* is the random
        suffix. Two re-marks in the same millisecond therefore returned the
        parent as "latest" on a coin flip, and the next re-mark would have
        branched the chain instead of extending it.

        So the leaf is selected structurally -- the spec nothing else claims as
        its parent -- with the timestamps only breaking ties between genuinely
        unrelated specs.
        """
        row = self.conn.execute(
            """
            SELECT body FROM markup_spec s
            WHERE s.symbol = ? AND s.timeframe = ?
              AND NOT EXISTS (SELECT 1 FROM markup_spec c WHERE c.parent = s.id)
            ORDER BY s.as_of DESC, s.created DESC, s.id DESC
            LIMIT 1
            """,
            (symbol.upper(), resolve(timeframe).label),
        ).fetchone()
        return MarkupSpec.model_validate_json(row["body"]) if row else None

    def active(self, now: datetime | None = None) -> list[MarkupSpec]:
        """Every unexpired spec — the Level Watcher's watch list.

        Superseded specs are excluded: once a symbol has been re-marked, the
        parent's levels are a previous opinion, and watching both would fire two
        alerts for one price. Expiry is by the timeframe's own relevance window,
        so a monthly spec outlives a 5-minute one by months.
        """
        stamp = (now or datetime.now(UTC)).isoformat()
        rows = self.conn.execute(
            """
            SELECT body FROM markup_spec s
            WHERE s.expires_at > ?
              AND NOT EXISTS (SELECT 1 FROM markup_spec c WHERE c.parent = s.id)
            ORDER BY s.as_of DESC
            """,
            (stamp,),
        ).fetchall()
        return [MarkupSpec.model_validate_json(r["body"]) for r in rows]

    def lineage(self, spec_id: str) -> list[MarkupSpec]:
        """The parent chain, newest first. *"How has my read evolved?"*"""
        out: list[MarkupSpec] = []
        seen: set[str] = set()
        current: str | None = spec_id
        while current and current not in seen:
            seen.add(current)
            spec = self.get(current)
            if spec is None:
                break
            out.append(spec)
            current = spec.parent
        return out

    def history(self, symbol: str, *, limit: int = 20) -> list[MarkupSpec]:
        rows = self.conn.execute(
            "SELECT body FROM markup_spec WHERE symbol = ? "
            "ORDER BY as_of DESC LIMIT ?",
            (symbol.upper(), limit),
        ).fetchall()
        return [MarkupSpec.model_validate_json(r["body"]) for r in rows]

    def __len__(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) c FROM markup_spec").fetchone()["c"])


def _expiry(spec: MarkupSpec) -> datetime:
    """When this spec's levels stop being worth watching.

    ``relevance_bars`` bars past ``as_of``, in that timeframe's own units. A
    5-minute spec is stale in a day; a monthly one is current for years. The
    alternative -- one fixed TTL -- would either retire weekly levels while they
    still matter or leave last Tuesday's 5-minute levels firing alerts forever,
    and the second is how an alerting system gets muted.
    """
    tf = resolve(spec.timeframe)
    return spec.as_of + timedelta(minutes=tf.minutes * tf.relevance_bars)
