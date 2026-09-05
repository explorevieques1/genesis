# Spec: Genesis Markdown/20-Agents/Strategy/Agent — Backtest Runner.md
"""Where finished runs live.

A backtest is expensive to produce and cheap to keep, and the thing a person
actually does with one is compare it to another. So runs are durable and
addressable: the UI lists them, opens one by id, and puts two side by side.

The result body is stored as JSON exactly as the runner normalised it. Not
shredded into columns — deliberately. A backtest report is a *document*, its
shape follows the engine's, and normalising it into fifteen tables would mean a
schema migration every time Nautilus adds a statistic. The columns that exist
here are the ones worth querying across runs: which symbol, which strategy, how
it did, when it ran.

`Agent — Backtest Vs Live Drift` is the eventual consumer. It compares live
outcomes against the backtest that justified the strategy, which only works if
that backtest is still on disk and still says exactly what it said at the time.
So rows here are never updated — a re-run is a new row.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genesis.memory.db import connect

__all__ = ["BacktestStore", "StoredRun", "DEFAULT_PATH"]

DEFAULT_PATH = Path("~/.genesis/memory/backtest.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    name          TEXT NOT NULL,
    symbol_id     TEXT NOT NULL,
    timeframe     TEXT NOT NULL,
    engine        TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    -- The headline figures, lifted out so a list view does not have to parse
    -- every stored document to render a table.
    positions     INTEGER NOT NULL DEFAULT 0,
    pnl_total     REAL,
    pnl_pct       REAL,
    win_rate      REAL,
    sharpe        REAL,
    -- The full normalised run, as produced. Never rewritten.
    body          TEXT NOT NULL,
    -- What the person said, when a run came from an utterance. The sentence
    -- that produced the numbers, kept beside them.
    prompt        TEXT
);
CREATE INDEX IF NOT EXISTS runs_by_symbol ON runs(symbol_id, created_at DESC);
CREATE INDEX IF NOT EXISTS runs_by_time ON runs(created_at DESC);

-- A run is a record of something that happened. Editing one would make every
-- drift comparison built on it silently wrong.
CREATE TRIGGER IF NOT EXISTS runs_are_immutable
BEFORE UPDATE ON runs
BEGIN
    SELECT RAISE(ABORT, 'backtest runs are immutable; re-run instead');
END;
"""


@dataclass(frozen=True)
class StoredRun:
    """One row of the list view."""

    run_id: str
    created_at: str
    name: str
    symbol_id: str
    timeframe: str
    engine: str
    engine_version: str
    positions: int
    pnl_total: float | None
    pnl_pct: float | None
    win_rate: float | None
    sharpe: float | None
    prompt: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "created_at": self.created_at,
            "name": self.name, "symbol_id": self.symbol_id,
            "timeframe": self.timeframe, "engine": self.engine,
            "engine_version": self.engine_version, "positions": self.positions,
            "pnl_total": self.pnl_total, "pnl_pct": self.pnl_pct,
            "win_rate": self.win_rate, "sharpe": self.sharpe,
            "prompt": self.prompt,
        }


@dataclass
class BacktestStore:
    path: Path | str = DEFAULT_PATH
    _conn: sqlite3.Connection | None = None

    def __post_init__(self) -> None:
        self._conn = connect(self.path)
        self._conn.executescript(SCHEMA)

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("store is closed")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "BacktestStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def put(self, run: Any, *, prompt: str | None = None) -> str:
        """Persist a :class:`~genesis.backtest.runner.BacktestRun`."""
        body = run.to_dict() if hasattr(run, "to_dict") else dict(run)
        meta = body.get("meta", {})
        spec = body.get("spec", {})
        headline = _headline(body)

        self.conn.execute(
            "INSERT INTO runs (run_id, created_at, name, symbol_id, timeframe, "
            "engine, engine_version, positions, pnl_total, pnl_pct, win_rate, "
            "sharpe, body, prompt) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                body["run_id"],
                datetime.now(UTC).isoformat(),
                str(spec.get("name", "unnamed")),
                str(meta.get("symbol_id", spec.get("symbol_id", ""))),
                str(meta.get("timeframe", spec.get("timeframe", ""))),
                str(meta.get("engine", "unknown")),
                str(meta.get("engine_version", "unknown")),
                int(meta.get("total_positions", 0) or 0),
                headline["pnl_total"], headline["pnl_pct"],
                headline["win_rate"], headline["sharpe"],
                json.dumps(body),
                prompt or spec.get("prompt"),
            ),
        )
        self.conn.commit()
        return body["run_id"]

    def get(self, run_id: str) -> dict[str, Any] | None:
        """The full stored document, or ``None``."""
        row = self.conn.execute(
            "SELECT body FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, *, symbol_id: str | None = None, limit: int = 50) -> list[StoredRun]:
        sql = (
            "SELECT run_id, created_at, name, symbol_id, timeframe, engine, "
            "engine_version, positions, pnl_total, pnl_pct, win_rate, sharpe, prompt "
            "FROM runs"
        )
        params: list[Any] = []
        if symbol_id:
            sql += " WHERE symbol_id = ?"
            params.append(symbol_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        return [StoredRun(*row) for row in self.conn.execute(sql, params).fetchall()]

    def delete(self, run_id: str) -> bool:
        cursor = self.conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def __len__(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0])


def _headline(body: dict[str, Any]) -> dict[str, float | None]:
    """Pull the four figures a list view shows out of the stats blocks.

    Nautilus keys its statistics by human strings — ``"Win Rate"``,
    ``"Sharpe Ratio (252 days)"`` — and the Sharpe key carries its annualisation
    window in the name, so it cannot be matched exactly. Matched by prefix, and
    missing rather than guessed when absent.
    """
    stats = body.get("stats", {})
    pnls = stats.get("pnls") or {}
    returns = stats.get("returns") or {}

    # A single-currency run is the normal case; take the first block rather
    # than assuming USD, which would silently report nothing for anything else.
    first = next(iter(pnls.values()), {}) if pnls else {}
    sharpe = next(
        (v for k, v in returns.items() if k.startswith("Sharpe Ratio")), None
    )
    return {
        "pnl_total": _number(first.get("PnL (total)")),
        "pnl_pct": _number(first.get("PnL% (total)")),
        "win_rate": _number(first.get("Win Rate")),
        "sharpe": _number(sharpe),
    }


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN check without importing math
