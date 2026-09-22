# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""What the world did. DuckDB, Decimal, write-once.

:mod:`genesis.charting.store` already drew this line and this module honours the
other side of it: the Memory Fabric in SQLite holds what the system *believes*,
this store holds what the world *did*. Different lifecycle, different truth
conditions, different size class -- and losing one is expensive while losing the
other is merely annoying.

DuckDB because Market Data Plane.md says so and gives the reason: columnar, no
server, and the files are directly readable by pandas and vectorbt, which
matters because the trading corpus is Python and a backtest should not need a
translation layer to read our history.

Three properties this module exists to guarantee.

**Closed bars are immutable and written once.** Never re-fetch a bar you hold.
This is what makes the second run of anything free, and it is enforced by
:meth:`BarStore.write` refusing to overwrite rather than by callers being
careful.

**A restatement supersedes, it does not overwrite.** When a vendor sends a
different value for a bar we already hold, the old row moves to
``bars_superseded`` and both are kept. Market Data Plane.md is emphatic: *"a
changed history invalidates backtests"* -- and a history that changed silently
invalidates them without anyone noticing, which is worse than one that changed
loudly.

**Coverage is recorded, not inferred.** This is the subtle one, and the reason
:class:`BarStore` has a second table that a first draft would not have. "Do I
already hold this window?" cannot be answered by looking for bars, because an
*empty* answer is ambiguous: a Sunday has no bars and neither does a window we
have never fetched. Without a coverage record, every ingest re-asks the vendor
about every holiday, forever -- which quietly defeats "never re-fetch" on
exactly the days the vendor is most likely to rate limit you for asking. So a
fetch records the window it covered, and emptiness becomes a fact rather than
an absence.

Prices are ``DECIMAL(18,8)``. Conventions.md §Money, and futures are where it
first bites: ES trades in quarter points and 4512.25 has no exact float
representation. The float conversion happens once, on the way out, in
:mod:`genesis.marketdata.source`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from genesis.errors import DegradedError, FatalError
from genesis.marketdata.normalize import Bar, parse_instrument_id

__all__ = ["BarStore", "Coverage", "DEFAULT_STORE_PATH", "SCHEMA", "open_store"]

DEFAULT_STORE_PATH = Path("~/.genesis/market/market.duckdb")

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol_id    VARCHAR       NOT NULL,
    timeframe    VARCHAR       NOT NULL,
    ts           TIMESTAMPTZ   NOT NULL,
    open         DECIMAL(18,8) NOT NULL,
    high         DECIMAL(18,8) NOT NULL,
    low          DECIMAL(18,8) NOT NULL,
    close        DECIMAL(18,8) NOT NULL,
    volume       DECIMAL(28,8) NOT NULL,
    source       VARCHAR       NOT NULL,
    tier         INTEGER       NOT NULL,
    as_of        TIMESTAMPTZ,
    ingested_at  TIMESTAMPTZ   NOT NULL,
    adjusted     BOOLEAN       NOT NULL,
    PRIMARY KEY (symbol_id, timeframe, ts)
);

-- Restatements. Same key as `bars`, plus when it was displaced and by what.
-- Append-only: nothing ever deletes from here, because this table IS the
-- record that the history changed.
CREATE TABLE IF NOT EXISTS bars_superseded (
    symbol_id    VARCHAR       NOT NULL,
    timeframe    VARCHAR       NOT NULL,
    ts           TIMESTAMPTZ   NOT NULL,
    open         DECIMAL(18,8) NOT NULL,
    high         DECIMAL(18,8) NOT NULL,
    low          DECIMAL(18,8) NOT NULL,
    close        DECIMAL(18,8) NOT NULL,
    volume       DECIMAL(28,8) NOT NULL,
    source       VARCHAR       NOT NULL,
    tier         INTEGER       NOT NULL,
    as_of        TIMESTAMPTZ,
    ingested_at  TIMESTAMPTZ   NOT NULL,
    adjusted     BOOLEAN       NOT NULL,
    superseded_at TIMESTAMPTZ  NOT NULL,
    superseded_by VARCHAR      NOT NULL
);

-- What we have ASKED about, as opposed to what we hold. See the module
-- docstring: without this, an empty window is indistinguishable from an
-- unfetched one and the store re-asks the vendor about every holiday forever.
CREATE TABLE IF NOT EXISTS coverage (
    symbol_id    VARCHAR       NOT NULL,
    timeframe    VARCHAR       NOT NULL,
    start        TIMESTAMPTZ   NOT NULL,
    "end"        TIMESTAMPTZ   NOT NULL,
    source       VARCHAR       NOT NULL,
    tier         INTEGER       NOT NULL,
    fetched_at   TIMESTAMPTZ   NOT NULL,
    bar_count    INTEGER       NOT NULL
);
CREATE INDEX IF NOT EXISTS coverage_lookup ON coverage (symbol_id, timeframe);
"""

_PRICE_FIELDS = ("open", "high", "low", "close", "volume")


def _as_utc(value: datetime | None) -> datetime | None:
    """Every timestamp leaving the store is UTC. See the SET TimeZone comment."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class Coverage:
    """A window we have already asked a vendor about."""

    start: datetime
    end: datetime
    source: str
    tier: int
    bar_count: int


class BarStore:
    """The bar store. One instance per process; DuckDB is single-writer.

    The lock is a real requirement rather than defensive habit: ingest runs as
    a supervised daemon worker while the CLI and the dashboard read, and
    DuckDB's own concurrency model is one writer per database file. Serialising
    writes here turns a corruption risk into a short wait.
    """

    def __init__(
        self,
        path: Path | str = DEFAULT_STORE_PATH,
        *,
        read_only: bool = False,
        shared: bool = False,
    ) -> None:
        import duckdb

        self.path = Path(path).expanduser() if str(path) != ":memory:" else Path(":memory:")
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.read_only = read_only
        #: A store handed out by :func:`open_store` is the process's one handle
        #: on this file, so ``close()`` on it is a no-op -- see that method.
        self._shared = shared
        self._lock = threading.Lock()
        self._local = threading.local()
        try:
            self._db = duckdb.connect(str(self.path), read_only=read_only)
        except Exception as exc:  # duckdb raises several unrelated types
            raise FatalError(
                f"cannot open the market data store at {self.path}: {exc}"
            ) from exc
        # Pin the session to UTC. DuckDB renders TIMESTAMPTZ in the *local*
        # zone by default, so a bar written at 2026-03-11T00:00Z reads back as
        # 2026-03-10 20:00-04:00 -- the same instant, correctly, but a
        # different calendar day. Every date-based query and every chart label
        # would then be off by one for half the day, in a way that looks like
        # a data problem rather than a display one. The connection says UTC and
        # `_to_bar` converts as well: two defences, because this one is silent.
        self.conn.execute("SET TimeZone='UTC'")
        if not read_only:
            self.conn.execute(SCHEMA)

    def close(self) -> None:
        """Close the connection -- unless this is the process's shared store.

        A shared store is handed to every caller in the process, so one of them
        closing it in a ``finally`` would pull the connection out from under the
        others. The daemon's read routes and its command handlers do exactly
        that, which is how a chart command used to leave the read API answering
        "store not created yet" for the rest of the process's life.
        """
        if self._shared:
            return
        self._db.close()

    @property
    def conn(self) -> Any:
        """This thread's cursor on the store.

        A DuckDB connection is not safe to share between threads: a read on one
        thread replaces the pending result of a query on another. `genesis
        serve` has three -- the IBKR live session, the chart's load worker and
        the read routes -- and the symptom was a write's ``fetchone()`` handed a
        row from someone else's query (``Decimal('EQ:XNAS:AAPL')``). A cursor
        per thread is DuckDB's own answer; they share one database instance, so
        the one-configuration-per-file rule in :func:`open_store` still holds.
        """
        local = self._local
        if getattr(local, "db", None) is not self._db:
            local.db = self._db
            local.cursor = self._db.cursor()
            local.cursor.execute("SET TimeZone='UTC'")
        return local.cursor

    def _become_writable(self) -> None:
        """Take the write handle on a store that was opened read-only.

        DuckDB caches one database instance per file **per process**, and a
        second connection with a different configuration is refused outright:

            Can't open a connection to same database file with a different
            configuration than existing connections

        So the read handle has to be given up before the write handle can be
        taken -- they cannot coexist. That ordering has a real failure window:
        if another process holds the write lock, we have already closed our
        reader. Reopening read-only is the recovery, and the raise afterwards is
        deliberate: a writer that cannot write must say so rather than continue
        against a connection that will reject every INSERT.
        """
        import duckdb

        with self._lock:
            if not self.read_only:
                return
            self._db.close()
            try:
                self._db = duckdb.connect(str(self.path), read_only=False)
            except Exception as exc:  # duckdb raises several unrelated types
                self._db = duckdb.connect(str(self.path), read_only=True)
                self.conn.execute("SET TimeZone='UTC'")
                raise FatalError(
                    f"cannot take the write handle on {self.path}: {exc}. "
                    "Another process is holding it -- an ingest run, or a second "
                    "`genesis serve`."
                ) from exc
            self.conn.execute("SET TimeZone='UTC'")
            self.conn.execute(SCHEMA)
            self.read_only = False

    def __enter__(self) -> "BarStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- writing -----------------------------------------------------------

    def write(self, bars: Sequence[Bar]) -> dict[str, int]:
        """Write closed bars. Returns counts of ``written``/``held``/``superseded``.

        Bars already held with identical values are **skipped silently** -- that
        is the normal case on a re-run and is not worth a log line. Bars already
        held with *different* values are restatements and take the loud path.

        Refuses continuous-contract ids outright. Open Questions §13 is
        unanswered, and a continuous series written under one roll convention
        cannot be distinguished later from one written under another. Refusing
        now costs a session; discovering it in six months costs the history.
        """
        if not bars:
            return {"written": 0, "held": 0, "superseded": 0}

        for bar in bars:
            if parse_instrument_id(bar.symbol_id).is_continuous:
                raise DegradedError(
                    f"{bar.symbol_id}: refusing to store a continuous series. "
                    f"Open Questions §13 (roll rule and adjustment method) is "
                    f"unanswered, and history written under an unrecorded "
                    f"convention cannot be repaired. Store dated contracts."
                )

        now = datetime.now(UTC)
        written = held = superseded = 0
        with self._lock:
            self.conn.execute("BEGIN TRANSACTION")
            try:
                for bar in bars:
                    existing = self.conn.execute(
                        "SELECT open, high, low, close, volume, source, tier, "
                        "as_of, ingested_at, adjusted FROM bars "
                        "WHERE symbol_id=? AND timeframe=? AND ts=?",
                        [bar.symbol_id, bar.timeframe, bar.ts],
                    ).fetchone()

                    if existing is None:
                        self._insert(bar, now)
                        written += 1
                        continue

                    if self._same_values(existing, bar):
                        held += 1
                        continue

                    # A restatement. Preserve, then replace, then say so.
                    self.conn.execute(
                        'INSERT INTO bars_superseded SELECT *, ?, ? FROM bars '
                        "WHERE symbol_id=? AND timeframe=? AND ts=?",
                        [now, bar.source, bar.symbol_id, bar.timeframe, bar.ts],
                    )
                    self.conn.execute(
                        "DELETE FROM bars WHERE symbol_id=? AND timeframe=? AND ts=?",
                        [bar.symbol_id, bar.timeframe, bar.ts],
                    )
                    self._insert(bar, now)
                    superseded += 1
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return {"written": written, "held": held, "superseded": superseded}

    def record_coverage(
        self,
        symbol_id: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        *,
        source: str,
        tier: int,
        bar_count: int,
    ) -> None:
        """Record that this window was fetched, whatever came back.

        Called even when the answer was zero bars -- especially then. That is
        the whole reason this table exists.
        """
        with self._lock:
            self.conn.execute(
                'INSERT INTO coverage (symbol_id, timeframe, start, "end", source, '
                "tier, fetched_at, bar_count) VALUES (?,?,?,?,?,?,?,?)",
                [symbol_id, timeframe, start, end, source, tier,
                 datetime.now(UTC), bar_count],
            )

    # -- reading -----------------------------------------------------------

    def read(
        self,
        symbol_id: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
        min_tier: int | None = None,
    ) -> list[Bar]:
        """Bars in ``[start, end)``, chronological.

        ``min_tier`` filters on trust: a lower number is more trusted, so
        ``min_tier=2`` returns tier 1 and 2 and excludes tier 3. Market Data
        Sources requires that a tier-3 bar never silently satisfy a tier-2
        request, and the filter is only possible because the tier is a column
        on the row rather than a property of the cache it arrived in.

        ``limit`` takes the most RECENT n bars, not the first. A chart wants
        the last 252 days; nothing wants the first 252 days of everything we
        hold.
        """
        clauses = ["symbol_id = ?", "timeframe = ?"]
        params: list[Any] = [symbol_id, timeframe]
        if start is not None:
            clauses.append("ts >= ?")
            params.append(start)
        if end is not None:
            clauses.append("ts < ?")
            params.append(end)
        if min_tier is not None:
            clauses.append("tier <= ?")
            params.append(min_tier)
        sql = (
            "SELECT symbol_id, timeframe, ts, open, high, low, close, volume, "
            "source, tier, as_of, ingested_at, adjusted FROM bars "
            f"WHERE {' AND '.join(clauses)} ORDER BY ts"
        )
        if limit is not None:
            sql += f" DESC LIMIT {int(limit)}"
        rows = self.conn.execute(sql, params).fetchall()
        if limit is not None:
            rows = list(reversed(rows))
        return [self._to_bar(row) for row in rows]

    def coverage(self, symbol_id: str, timeframe: str) -> list[Coverage]:
        rows = self.conn.execute(
            'SELECT start, "end", source, tier, bar_count FROM coverage '
            "WHERE symbol_id=? AND timeframe=? ORDER BY start",
            [symbol_id, timeframe],
        ).fetchall()
        return [Coverage(r[0], r[1], r[2], int(r[3]), int(r[4])) for r in rows]

    def covers(
        self, symbol_id: str, timeframe: str, start: datetime, end: datetime
    ) -> bool:
        """Has ``[start, end)`` already been fetched, in full?

        Merges the recorded windows before testing, so a range assembled from
        several ingests still counts as covered. Adjacent-or-overlapping
        windows merge; a gap of any size does not, and the answer is then
        ``False`` -- fail closed, per Safety Invariants. Claiming coverage we
        do not have is how a chart silently loses a week.
        """
        windows = sorted(
            ((c.start, c.end) for c in self.coverage(symbol_id, timeframe)),
        )
        if not windows:
            return False
        cursor = start
        for w_start, w_end in windows:
            if w_start > cursor:
                return False  # a hole opens before this window
            cursor = max(cursor, w_end)
            if cursor >= end:
                return True
        return cursor >= end

    def last_bar_time(self, symbol_id: str, timeframe: str) -> datetime | None:
        row = self.conn.execute(
            "SELECT MAX(ts) FROM bars WHERE symbol_id=? AND timeframe=?",
            [symbol_id, timeframe],
        ).fetchone()
        return row[0] if row and row[0] is not None else None

    def symbols(self) -> list[tuple[str, str, int]]:
        """``(symbol_id, timeframe, bar_count)`` for everything held."""
        return [
            (r[0], r[1], int(r[2]))
            for r in self.conn.execute(
                "SELECT symbol_id, timeframe, COUNT(*) FROM bars "
                "GROUP BY symbol_id, timeframe ORDER BY symbol_id, timeframe"
            ).fetchall()
        ]

    def superseded(self, symbol_id: str, timeframe: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM bars_superseded WHERE symbol_id=? AND timeframe=?",
            [symbol_id, timeframe],
        ).fetchone()
        return int(row[0]) if row else 0

    # -- internals ---------------------------------------------------------

    def _insert(self, bar: Bar, now: datetime) -> None:
        self.conn.execute(
            "INSERT INTO bars (symbol_id, timeframe, ts, open, high, low, close, "
            "volume, source, tier, as_of, ingested_at, adjusted) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                bar.symbol_id, bar.timeframe, bar.ts,
                bar.open, bar.high, bar.low, bar.close, bar.volume,
                bar.source, bar.tier, bar.as_of, bar.ingested_at or now, bar.adjusted,
            ],
        )

    @staticmethod
    def _same_values(existing: Sequence[Any], bar: Bar) -> bool:
        """Is the held row the same *fact* as this bar?

        Compares prices and volume only. Provenance deliberately does not
        count: the same bar arriving from a second vendor is not a
        restatement, it is corroboration, and treating it as a restatement
        would fill ``bars_superseded`` with noise and hide the real ones.
        """
        return all(
            Decimal(str(existing[i])) == getattr(bar, name)
            for i, name in enumerate(_PRICE_FIELDS)
        )

    @staticmethod
    def _to_bar(row: Sequence[Any]) -> Bar:
        return Bar(
            symbol_id=row[0],
            timeframe=row[1],
            ts=(row[2].replace(tzinfo=UTC) if row[2].tzinfo is None
                else row[2].astimezone(UTC)),
            open=Decimal(str(row[3])),
            high=Decimal(str(row[4])),
            low=Decimal(str(row[5])),
            close=Decimal(str(row[6])),
            volume=Decimal(str(row[7])),
            source=row[8],
            tier=int(row[9]),
            as_of=_as_utc(row[10]),
            ingested_at=_as_utc(row[11]),
            adjusted=bool(row[12]),
        )


# ---------------------------------------------------------------------------
# one store per process, per file
# ---------------------------------------------------------------------------

_OPEN: dict[Path, BarStore] = {}
_OPEN_LOCK = threading.Lock()


def open_store(
    path: Path | str = DEFAULT_STORE_PATH, *, read_only: bool = False
) -> BarStore:
    """The process's handle on a bar store. **Use this, not ``BarStore()``.**

    DuckDB keys one database instance per file per process and refuses a second
    connection whose configuration differs from the first. Two call sites
    opening the same file -- a read route with ``read_only=True`` and a chart
    command with ``read_only=False`` -- is therefore not "two connections", it
    is a crash:

        FatalError: cannot open the market data store at ~/.genesis/market/
        market.duckdb: Connection Error: Can't open a connection to same
        database file with a different configuration than existing connections

    That is what this function exists to make structurally impossible. The
    process opens each file once and everyone shares the handle, so there is no
    second configuration to disagree with.

    ``read_only`` is a *floor*, not a mode. A read-only request is satisfied by
    a writable handle -- reading through it is fine. A write request against a
    read-only handle upgrades it in place, because a command that needs to
    ingest cannot be told "someone read first". The daemon therefore starts
    read-only, and stays read-only until something actually needs to write,
    which is what lets a separate ``genesis ingest`` process hold the write lock
    in the meantime.

    Not a cache for performance. It is the thing that keeps one process from
    disagreeing with itself about a file it has open.
    """
    # ponytail: the handle never downgrades. Once a command writes, `genesis
    # serve` holds the write lock until it restarts, so an external `genesis
    # ingest` cannot run in the meantime -- where before, each write opened and
    # closed and left gaps to slip through. Add a refcounted downgrade back to
    # read-only if that starts biting; it needs care, because a downgrade races
    # every in-flight write.
    key = Path(path).expanduser() if str(path) != ":memory:" else Path(":memory:")
    with _OPEN_LOCK:
        store = _OPEN.get(key)
        if store is None:
            store = BarStore(key, read_only=read_only, shared=True)
            _OPEN[key] = store
            return store
    # Upgrade outside the registry lock: it can block on another process's
    # write lock, and holding the registry while that happens would stall every
    # read route in the daemon.
    if not read_only:
        store._become_writable()
    return store


def close_open_stores() -> None:
    """Drop every shared handle. For tests and for daemon shutdown."""
    with _OPEN_LOCK:
        stores = list(_OPEN.values())
        _OPEN.clear()
    for store in stores:
        store.conn.close()
