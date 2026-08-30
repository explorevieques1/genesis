# Spec: Genesis Markdown/40-Memory/Memory Fabric.md
"""SQLite connection policy, shared by every durable layer.

The pragmas are the durability contract, not tuning knobs:

``journal_mode=WAL``
    Readers do not block the writer, which matters because the dashboard and
    the Insight Miner read the Episodic Log while the daemon is appending to it.
    WAL also makes a commit a single atomic frame append -- a process killed
    mid-write leaves the frame incomplete and it is discarded on recovery,
    which is what "no half-row" rests on.

``synchronous=FULL``
    The WAL is fsynced on every commit. With ``NORMAL``, a commit is durable
    against process death but not against machine death; the Trade Ledger's
    acceptance criterion is that an acknowledged write survives, so it pays the
    fsync. Our threat model is process kill, not a lying disk controller.

``foreign_keys=ON``
    Off by default in SQLite, per-connection, and silently ignored if set on the
    wrong connection -- which is exactly how a fill ends up referencing an order
    that does not exist.

``busy_timeout``
    Several supervised workers write concurrently. Without it, a contended write
    raises ``database is locked`` immediately instead of waiting.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

__all__ = ["connect", "transaction"]

BUSY_TIMEOUT_MS = 5_000


def connect(path: Path | str, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a connection with the durability pragmas applied."""
    path = Path(path).expanduser()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(path),
        timeout=BUSY_TIMEOUT_MS / 1000,
        isolation_level=None,  # explicit transactions; see `transaction`
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    if read_only:
        conn.execute("PRAGMA query_only=ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
    """An explicit transaction that commits on success and rolls back on error.

    ``BEGIN IMMEDIATE`` takes the write lock up front. The default deferred
    behaviour acquires it on first write, which turns a concurrent writer into
    a mid-transaction ``database is locked`` that cannot be retried safely.
    """
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
