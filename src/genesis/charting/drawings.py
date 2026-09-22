# Spec: Genesis Markdown/60-UI/Chart Tools.md
"""What the trader drew on a chart. Their marks, kept.

[[Markup Spec]] is what *Genesis* draws: produced by an agent, scored, every
annotation carrying a ``why``, immutable once written. This is the other half —
what a person drew with their own hand, which is a box round a setup and an
arrow at the entry, saved so it is still there tomorrow.

Same vocabulary deliberately. ``kind`` and the payload field names are
:mod:`genesis.charting.spec`'s: a hand-drawn box is a ``zone``, a trendline is a
``line``, the position tool is a ``trade_plan``. Two vocabularies for the same
eight shapes would guarantee that a person's box and an agent's box could never
be shown on one chart, and the [[Operating Model]] parity rule points the other
way.

What is deliberately *not* enforced here is the ``why``. An agent that draws an
unexplained line is producing noise; a person drawing on their own chart is
thinking, and demanding a justification per stroke would stop them doing it.
That is the difference between the two stores, and it is why this is a separate
table rather than a looser mode of the same one.

**A drawing is not an order and cannot become one.** ``trade_plan`` here is the
schema's ``trade_plan``: entry, stop, targets, no size, no account, no broker.
Safety Invariants §1 keeps the only path to a broker through ``propose_order``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genesis.errors import DegradedError
from genesis.ids import new_id
from genesis.memory.db import connect, transaction

__all__ = ["DrawingStore", "KINDS", "SCHEMA"]

#: The shapes a person can draw, matching `spec.Annotation`'s discriminator.
#: Closed, because an unknown kind is a drawing nothing can render.
KINDS = frozenset({
    "level", "zone", "line", "fib", "trade_plan", "marker", "text",
})

#: A drawing is a handful of numbers and a short label. Anything larger is a
#: bug or an attempt at using the chart as a filesystem.
MAX_PAYLOAD = 8_192

SCHEMA = """
CREATE TABLE IF NOT EXISTS chart_drawings (
    id      TEXT PRIMARY KEY,
    series  TEXT NOT NULL,
    kind    TEXT NOT NULL,
    payload TEXT NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS drawings_series ON chart_drawings(series, created);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class DrawingStore:
    """Opened per request, like every other surface store."""

    def __init__(self, path: Path | str, *, conn: sqlite3.Connection | None = None) -> None:
        self.path = path
        self._conn = conn if conn is not None else connect(path)
        self._conn.executescript(SCHEMA)

    def save(
        self, series: str, kind: str, payload: dict[str, Any], *, drawing_id: str = ""
    ) -> str:
        """Insert or replace one drawing. Returns its id.

        Validated at the boundary rather than trusted: the browser is the only
        caller today, and that is exactly the argument that stops being true.
        """
        series = (series or "").strip()
        if not series or len(series) > 200:
            raise DegradedError("a drawing belongs to a series; none was given")
        if kind not in KINDS:
            raise DegradedError(
                f"{kind!r} is not a drawable kind ({', '.join(sorted(KINDS))})"
            )
        if not isinstance(payload, dict):
            raise DegradedError("a drawing payload is an object")
        body = json.dumps(payload, separators=(",", ":"))
        if len(body) > MAX_PAYLOAD:
            raise DegradedError(
                f"drawing payload is {len(body)} bytes; the limit is {MAX_PAYLOAD}"
            )

        now = _now()
        did = drawing_id or new_id("dr")
        with transaction(self._conn) as tx:
            tx.execute(
                "INSERT INTO chart_drawings (id, series, kind, payload, created, updated)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET"
                "   series = excluded.series, kind = excluded.kind,"
                "   payload = excluded.payload, updated = excluded.updated",
                (did, series, kind, body, now, now),
            )
        return did

    def delete(self, drawing_id: str) -> bool:
        with transaction(self._conn) as tx:
            return tx.execute(
                "DELETE FROM chart_drawings WHERE id = ?", (drawing_id,)
            ).rowcount > 0

    def clear(self, series: str) -> int:
        """Every drawing on one series. The 'clear the chart' button."""
        with transaction(self._conn) as tx:
            return tx.execute(
                "DELETE FROM chart_drawings WHERE series = ?", (series,)
            ).rowcount

    def list(self, series: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM chart_drawings WHERE series = ? ORDER BY created",
            (series,),
        ).fetchall()
        return [
            {"id": r["id"], "series": r["series"], "kind": r["kind"],
             "created": r["created"], "updated": r["updated"],
             **json.loads(r["payload"])}
            for r in rows
        ]

    def counts(self) -> dict[str, int]:
        """Drawings per series — what `SR` would show if it ever wanted to."""
        return {
            r["series"]: r["n"]
            for r in self._conn.execute(
                "SELECT series, COUNT(*) AS n FROM chart_drawings GROUP BY series"
            ).fetchall()
        }
