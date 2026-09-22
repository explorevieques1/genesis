# Spec: Genesis Markdown/10-Architecture/Company Data Model.md
"""Cached company profiles. DuckDB, beside the bars.

Same file as :mod:`genesis.marketdata.store`, different tables, and that is
deliberate: a company fact and a price are both *what the world did*, and
keeping them in one database means a query can join a fundamental to a bar
without crossing a process boundary.

**The cache is aggressive because the data is slow.** A sector does not change
intraday; a 10-Q is not restated while you look at it. Per-group TTLs from
:data:`genesis.company.schema.TTL` mean a second ``genesis company NVDA``
inside the window makes **no network call at all** -- the same promise the bar
store makes, resting on the same reasoning.

Unlike bars, profiles are **not immutable**. A market cap is supposed to
change. So this is a cache with an expiry, not an append-only history, and it
says so: there is no ``superseded`` table here because being superseded is the
normal case rather than an event worth recording.

One exception: statement lines *are* immutable once filed, and they live in
their own table keyed the way [[Company Data Model]] hazard 2 requires --
fiscal period AND filed date -- so an as-of query survives a cache refresh.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from genesis.company.schema import (
    TTL,
    CompanyProfile,
    FinancialStatement,
    Sourced,
    StatementLine,
)
from genesis.errors import FatalError
from genesis.marketdata.store import DEFAULT_STORE_PATH

__all__ = ["SCHEMA", "CompanyStore"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS company_fields (
    symbol      VARCHAR     NOT NULL,
    field       VARCHAR     NOT NULL,
    value_json  VARCHAR     NOT NULL,   -- JSON, so a scalar and a table of
                                        -- holders share one column honestly
    source      VARCHAR     NOT NULL,
    tier        INTEGER     NOT NULL,
    field_group VARCHAR     NOT NULL,
    derived     BOOLEAN     NOT NULL,
    conflict    VARCHAR,
    as_of       TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (symbol, field)
);

-- Statement lines are immutable once filed, so unlike the fields above these
-- accumulate rather than expire. `filed_date` is in the key: the same period
-- reported by two sources is two rows, and an as-of query needs both.
CREATE TABLE IF NOT EXISTS company_statements (
    symbol            VARCHAR       NOT NULL,
    statement         VARCHAR       NOT NULL,
    frequency         VARCHAR       NOT NULL,
    concept           VARCHAR       NOT NULL,
    fiscal_period_end DATE          NOT NULL,
    filed_date        DATE,
    period_type       VARCHAR       NOT NULL,
    value             DECIMAL(28,4) NOT NULL,
    currency          VARCHAR       NOT NULL,
    source            VARCHAR       NOT NULL,
    ingested_at       TIMESTAMPTZ   NOT NULL,
    PRIMARY KEY (symbol, statement, frequency, concept, fiscal_period_end, source)
);
CREATE INDEX IF NOT EXISTS company_statements_lookup
    ON company_statements (symbol, statement, frequency);
"""


@dataclass
class CompanyStore:
    """Read and write cached profiles.

    The company tables live in the **same DuckDB file as the bars**, so this
    shares the process's bar-store handle rather than opening its own
    connection. It used to open one, unconditionally writable, and that was the
    third opener of one file in a single process: a read route took the file
    read-only, a company profile route then asked for it writable, and DuckDB
    refused the mismatch outright rather than degrading.

    Asking for a writable handle is honest -- this store writes cache rows -- and
    it upgrades the shared handle exactly once, on first use.
    """

    path: Path | str = DEFAULT_STORE_PATH

    def __post_init__(self) -> None:
        from genesis.marketdata.store import open_store

        self.path = (
            Path(self.path).expanduser() if str(self.path) != ":memory:" else ":memory:"
        )
        self._lock = threading.Lock()
        try:
            self._store = open_store(self.path)
        except FatalError:
            raise
        except Exception as exc:
            raise FatalError(f"cannot open the company store at {self.path}: {exc}") from exc
        # TimeZone is already pinned to UTC by the bar store, for the same
        # reason: DuckDB renders TIMESTAMPTZ in local time by default, which
        # shifts a date across midnight for half the day.
        self.conn.execute(SCHEMA)

    @property
    def conn(self) -> Any:
        """The shared connection, read through rather than captured.

        A captured reference would go stale: ``open_store`` swaps the underlying
        connection when it upgrades a read-only handle to writable, and a
        CompanyStore holding the old object would be talking to a closed
        connection with no obvious symptom.
        """
        return self._store.conn

    def close(self) -> None:
        """A no-op. The connection belongs to the process, not to this object."""
        return None

    def __enter__(self) -> "CompanyStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- writing -----------------------------------------------------------

    def write(self, profile: CompanyProfile) -> None:
        with self._lock:
            self.conn.execute("BEGIN TRANSACTION")
            try:
                for name, entry in profile.values.items():
                    self.conn.execute(
                        "INSERT OR REPLACE INTO company_fields (symbol, field, "
                        "value_json, source, tier, field_group, derived, conflict, "
                        "as_of) VALUES (?,?,?,?,?,?,?,?,?)",
                        [
                            profile.symbol, name, _dump(entry.value), entry.source,
                            entry.tier, entry.group, entry.derived, entry.conflict,
                            entry.as_of,
                        ],
                    )
                now = datetime.now(UTC)
                for (statement, frequency), block in profile.statements.items():
                    for line in block.lines:
                        self.conn.execute(
                            "INSERT OR REPLACE INTO company_statements (symbol, "
                            "statement, frequency, concept, fiscal_period_end, "
                            "filed_date, period_type, value, currency, source, "
                            "ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            [
                                profile.symbol, statement, frequency, line.concept,
                                line.fiscal_period_end, line.filed_date,
                                line.period_type, line.value, line.currency,
                                line.source, now,
                            ],
                        )
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    # -- reading -----------------------------------------------------------

    def read(self, symbol: str) -> CompanyProfile | None:
        """The cached profile, expired fields omitted.

        Returns ``None`` only when nothing at all is held. A profile with some
        groups expired comes back partial rather than empty, so a caller can
        refresh just the stale groups -- which is what makes the 15-minute
        market TTL affordable next to the 30-day identity TTL.
        """
        rows = self.conn.execute(
            "SELECT field, value_json, source, tier, field_group, derived, "
            "conflict, as_of FROM company_fields WHERE symbol = ?",
            [symbol],
        ).fetchall()
        if not rows:
            return None

        profile = CompanyProfile(symbol=symbol)
        now = datetime.now(UTC)
        for field_name, payload, source, tier, group, derived, conflict, as_of in rows:
            stamp = as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
            if now - stamp > TTL.get(group, timedelta(hours=1)):
                continue  # expired; the caller refetches this group
            profile.set(
                field_name,
                Sourced(
                    value=_decode(json.loads(payload)),
                    source=source,
                    tier=int(tier),
                    as_of=stamp,
                    group=group,
                    derived=bool(derived),
                    conflict=conflict,
                ),
            )
        self._load_statements(profile)
        return profile if profile.values or profile.statements else None

    def _load_statements(self, profile: CompanyProfile) -> None:
        rows = self.conn.execute(
            "SELECT statement, frequency, concept, fiscal_period_end, filed_date, "
            "period_type, value, currency, source FROM company_statements "
            "WHERE symbol = ? ORDER BY fiscal_period_end",
            [profile.symbol],
        ).fetchall()
        buckets: dict[tuple[str, str], list[StatementLine]] = {}
        for st, freq, concept, period_end, filed, period_type, value, ccy, src in rows:
            buckets.setdefault((st, freq), []).append(
                StatementLine(
                    concept=concept,
                    value=Decimal(str(value)),
                    fiscal_period_end=_as_date(period_end),
                    filed_date=_as_date(filed) if filed else None,
                    period_type=period_type,
                    frequency=freq,
                    currency=ccy,
                    source=src,
                )
            )
        for (statement, frequency), lines in buckets.items():
            profile.statements[(statement, frequency)] = FinancialStatement(
                statement=statement,  # type: ignore[arg-type]
                frequency=frequency,
                lines=tuple(lines),
                # A block assembled from possibly several sources says so,
                # rather than claiming whichever one happened to be first.
                source="+".join(sorted({line.source for line in lines})),
            )

    def fresh_groups(self, symbol: str) -> set[str]:
        """Which field groups are cached and still inside their TTL."""
        rows = self.conn.execute(
            "SELECT field_group, MAX(as_of) FROM company_fields "
            "WHERE symbol = ? GROUP BY field_group",
            [symbol],
        ).fetchall()
        now = datetime.now(UTC)
        out = set()
        for group, newest in rows:
            stamp = newest if newest.tzinfo else newest.replace(tzinfo=UTC)
            if now - stamp <= TTL.get(group, timedelta(hours=1)):
                out.add(group)
        return out

    def symbols(self) -> list[str]:
        return [
            row[0]
            for row in self.conn.execute(
                "SELECT DISTINCT symbol FROM company_fields ORDER BY symbol"
            ).fetchall()
        ]


#: Marker for a value whose Python type JSON cannot express. Kept short and
#: unlikely to collide with a vendor's own key.
_TYPED = "__t"


def _dump(value: Any) -> str:
    """JSON that round-trips Decimal and dates as themselves.

    ``json.dumps(value, default=str)`` was the first version and it was wrong
    in a way that passed its own test: a Decimal went in and a **str** came
    back out. Conventions.md §Money says prices are Decimal, and a cache hit
    silently returning a string means arithmetic downstream either raises or,
    worse, concatenates.

    It survived because the test asserted ``Decimal(got.get(...)) == ...`` --
    the coercion in the assertion re-created the type the store had lost. A
    test written around the bug rather than against it.

    So the type travels with the value. Floats are deliberately NOT used for
    Decimal: that is the precision loss this whole convention exists to
    prevent.
    """
    return json.dumps(_encode(value))


def _encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {_TYPED: "dec", "v": str(value)}
    if isinstance(value, datetime):
        return {_TYPED: "dt", "v": value.isoformat()}
    if isinstance(value, date):
        return {_TYPED: "date", "v": value.isoformat()}
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        kind = value.get(_TYPED)
        if kind == "dec":
            return Decimal(value["v"])
        if kind == "dt":
            return datetime.fromisoformat(value["v"])
        if kind == "date":
            return date.fromisoformat(value["v"])
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)[:10]).date()
