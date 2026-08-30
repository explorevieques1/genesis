# Spec: Genesis Markdown/40-Memory/Trade Ledger.md
"""The financial source of truth. Append-only, double-entry, zero tolerance.

Phase 1 builds the smallest surface that makes the durability and rebuild
criteria real: the schema, an atomic fill append, crash recovery, and the
fills-to-positions reducer. There is no Accountant agent, no broker, and no
order lifecycle here -- those are Phase 7, and the risk gate is built before any
of them.

Four properties carry the design:

**Append-only, enforced by the database.** ``BEFORE UPDATE``/``BEFORE DELETE``
triggers on ``fills``, ``orders``, ``cash_flows`` and ``entries``. Never
``UPDATE`` a fill.

**Double-entry.** Every economic event writes balanced legs that must sum to
exactly zero, checked before the transaction commits. Single-entry position
tracking drifts and you find out when the numbers are already wrong.

**Money is ``Decimal``, stored as TEXT.** SQLite's ``REAL`` is an IEEE double;
storing 121.06 in one and reading it back is how a float sneaks into a system
that forbids them. Text in, ``Decimal`` out, exact both ways.

**Positions are derived, never authoritative.** :func:`rebuild_positions` is a
pure function of the fills. It can be dropped and rebuilt at any time, and doing
so is part of the test suite -- if a rebuild disagrees with a stored snapshot,
something is wrong and you want to know.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from genesis.errors import FatalError
from genesis.ids import new_id
from genesis.memory.db import connect, transaction

__all__ = [
    "Fill",
    "Leg",
    "Position",
    "TradeLedger",
    "SCHEMA",
    "rebuild_positions",
]

ZERO = Decimal("0")

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id               TEXT PRIMARY KEY,
    account_id       TEXT NOT NULL,
    client_order_id  TEXT NOT NULL,
    broker_order_id  TEXT,
    approval_id      TEXT NOT NULL,      -- REQUIRED: no order without the risk gate
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL CHECK (side IN ('buy','sell')),
    qty              INTEGER NOT NULL CHECK (qty > 0),
    order_type       TEXT NOT NULL,
    limit_price      TEXT,
    state            TEXT NOT NULL,
    trace_id         TEXT NOT NULL,
    strategy         TEXT,
    ts               TEXT NOT NULL,
    UNIQUE (account_id, client_order_id)
);

CREATE TABLE IF NOT EXISTS fills (
    id               TEXT PRIMARY KEY,
    account_id       TEXT NOT NULL,      -- Open Questions §10: multi-account from day one
    order_id         TEXT,
    client_order_id  TEXT NOT NULL,
    broker_fill_id   TEXT NOT NULL,
    approval_id      TEXT NOT NULL,      -- REQUIRED: a fill without one is a critical bug
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL CHECK (side IN ('buy','sell')),
    qty              INTEGER NOT NULL CHECK (qty > 0),
    price            TEXT NOT NULL,      -- Decimal as text, never REAL
    fee              TEXT NOT NULL,
    currency         TEXT NOT NULL DEFAULT 'USD',
    venue            TEXT,
    trace_id         TEXT NOT NULL,
    strategy         TEXT,
    idea             TEXT,
    ts               TEXT NOT NULL,
    -- The idempotency key for recovery replay. A broker fill is unique per
    -- account; replaying it must reconcile to exactly one row, not two.
    UNIQUE (account_id, broker_fill_id)
);

CREATE INDEX IF NOT EXISTS fills_account_symbol ON fills(account_id, symbol, ts);
CREATE INDEX IF NOT EXISTS fills_trace          ON fills(trace_id);

-- Double-entry legs. Every event's legs must sum to zero.
CREATE TABLE IF NOT EXISTS entries (
    id          TEXT PRIMARY KEY,
    event_id    TEXT NOT NULL,           -- the fill / cash flow this balances
    account_id  TEXT NOT NULL,
    leg         TEXT NOT NULL CHECK (leg IN ('cash','position','fee')),
    symbol      TEXT,
    amount      TEXT NOT NULL,           -- Decimal as text; signed
    currency    TEXT NOT NULL DEFAULT 'USD',
    ts          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS entries_event   ON entries(event_id);
CREATE INDEX IF NOT EXISTS entries_account ON entries(account_id, leg);

CREATE TABLE IF NOT EXISTS cash_flows (
    id          TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,
    amount      TEXT NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'USD',
    trace_id    TEXT NOT NULL,
    ts          TEXT NOT NULL
);

-- Derived and rebuildable. Deliberately NOT append-only.
CREATE TABLE IF NOT EXISTS positions (
    account_id     TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    qty            INTEGER NOT NULL,
    avg_entry      TEXT NOT NULL,
    realized_pnl   TEXT NOT NULL,
    fees_paid      TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (account_id, symbol)
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    id          TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL,
    equity      TEXT NOT NULL,
    cash        TEXT NOT NULL,
    ts          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconciliations (
    id          TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL,
    matched     INTEGER NOT NULL,
    detail      TEXT,
    ts          TEXT NOT NULL
);
"""

# Append-only, enforced by the database on every money table.
for _table in ("orders", "fills", "cash_flows", "entries"):
    SCHEMA += f"""
CREATE TRIGGER IF NOT EXISTS {_table}_no_update
BEFORE UPDATE ON {_table}
BEGIN
    SELECT RAISE(ABORT, '{_table} is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS {_table}_no_delete
BEFORE DELETE ON {_table}
BEGIN
    SELECT RAISE(ABORT, '{_table} is append-only: DELETE forbidden');
END;
"""


def _d(value: Any) -> Decimal:
    """Coerce to Decimal, refusing float.

    A float argument is rejected rather than converted: ``Decimal(0.1)`` is
    0.1000000000000000055511151231257827, and silently accepting it here would
    defeat every other precaution in the system.
    """
    if isinstance(value, float):
        raise FatalError(
            f"float {value!r} in a monetary field — use Decimal or str "
            f"(Conventions § Money)"
        )
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class Leg:
    """One side of a double-entry event."""

    leg: str
    amount: Decimal
    symbol: str | None = None
    currency: str = "USD"


@dataclass(frozen=True)
class Fill:
    """An execution, in the Order And Fill Schema shape."""

    account_id: str
    client_order_id: str
    broker_fill_id: str
    approval_id: str
    symbol: str
    side: str
    qty: int
    price: Decimal
    fee: Decimal
    trace_id: str
    ts: str
    id: str = ""
    order_id: str | None = None
    currency: str = "USD"
    venue: str | None = None
    strategy: str | None = None
    idea: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "price", _d(self.price))
        object.__setattr__(self, "fee", _d(self.fee))
        if not self.approval_id:
            # A fill without an approval means an order reached the broker
            # without passing the risk engine. Safety Invariants §1 forbids that
            # structurally; this is the detection that makes it visible.
            raise FatalError(
                f"fill for {self.symbol} has no approval_id — an order reached "
                f"the broker without passing the pre-trade risk engine"
            )
        if self.qty <= 0:
            raise FatalError(f"fill qty must be positive, got {self.qty}")
        if self.side not in ("buy", "sell"):
            raise FatalError(f"unknown side {self.side!r}")

    @property
    def notional(self) -> Decimal:
        return self.price * self.qty

    @property
    def signed_qty(self) -> int:
        return self.qty if self.side == "buy" else -self.qty

    def legs(self) -> tuple[Leg, ...]:
        """Balanced double-entry legs. These sum to exactly zero.

        A buy moves value from cash into the position and pays a fee:
        position +N, cash -N, fee +F, cash -F.
        """
        notional = self.notional
        direction = Decimal(1) if self.side == "buy" else Decimal(-1)
        return (
            Leg("position", direction * notional, symbol=self.symbol, currency=self.currency),
            Leg("cash", -direction * notional, currency=self.currency),
            Leg("fee", self.fee, currency=self.currency),
            Leg("cash", -self.fee, currency=self.currency),
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Fill:
        return cls(
            id=row["id"],
            account_id=row["account_id"],
            order_id=row["order_id"],
            client_order_id=row["client_order_id"],
            broker_fill_id=row["broker_fill_id"],
            approval_id=row["approval_id"],
            symbol=row["symbol"],
            side=row["side"],
            qty=row["qty"],
            price=Decimal(row["price"]),
            fee=Decimal(row["fee"]),
            currency=row["currency"],
            venue=row["venue"],
            trace_id=row["trace_id"],
            strategy=row["strategy"],
            idea=row["idea"],
            ts=row["ts"],
        )


@dataclass(frozen=True)
class Position:
    """A derived snapshot. Rebuildable from fills at any time."""

    account_id: str
    symbol: str
    qty: int = 0
    avg_entry: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    fees_paid: Decimal = ZERO

    @property
    def is_flat(self) -> bool:
        return self.qty == 0


def rebuild_positions(fills: Iterable[Fill]) -> dict[tuple[str, str], Position]:
    """Fold fills into positions. A pure function -- no state, no I/O, no agent.

    Keyed by ``(account_id, symbol)``: multi-account from day one, per Open
    Questions §10. Retrofitting the key onto an append-only ledger would mean
    rewriting the one structure that cannot be rewritten in place.

    Average-cost within a side, which is FIFO-equivalent for realized P&L when
    a position is only ever reduced or reversed as a whole. Fees are subtracted
    from realized P&L: a strategy profitable before fees and losing after must
    show as losing.
    """
    positions: dict[tuple[str, str], Position] = {}

    for fill in sorted(fills, key=lambda f: (f.ts, f.id)):
        key = (fill.account_id, fill.symbol)
        pos = positions.get(key) or Position(account_id=fill.account_id, symbol=fill.symbol)

        signed = fill.signed_qty
        fees_paid = pos.fees_paid + fill.fee
        realized = pos.realized_pnl - fill.fee

        if pos.qty == 0 or (pos.qty > 0) == (signed > 0):
            # Opening or adding: weighted-average the entry price.
            total_qty = pos.qty + signed
            if total_qty == 0:
                new_avg = ZERO
            else:
                new_avg = (
                    (pos.avg_entry * abs(pos.qty)) + (fill.price * abs(signed))
                ) / abs(total_qty)
            pos = replace(pos, qty=total_qty, avg_entry=new_avg)
        else:
            # Reducing, closing, or reversing.
            closing = min(abs(signed), abs(pos.qty))
            direction = Decimal(1) if pos.qty > 0 else Decimal(-1)
            realized += (fill.price - pos.avg_entry) * closing * direction

            remaining = pos.qty + signed
            if remaining == 0:
                pos = replace(pos, qty=0, avg_entry=ZERO)
            elif (remaining > 0) == (pos.qty > 0):
                pos = replace(pos, qty=remaining)
            else:
                # Reversed through flat: the excess opens a new position.
                pos = replace(pos, qty=remaining, avg_entry=fill.price)

        positions[key] = replace(pos, realized_pnl=realized, fees_paid=fees_paid)

    return positions


class TradeLedger:
    """Append fills, recover from a crash, rebuild positions."""

    def __init__(self, path: Path | str, *, conn: sqlite3.Connection | None = None) -> None:
        self.path = path
        self._conn = conn if conn is not None else connect(path)
        self._conn.executescript(SCHEMA)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Append
    # ------------------------------------------------------------------

    def record_fill(self, fill: Fill) -> Fill | None:
        """Append a fill and its balanced legs in one atomic commit.

        Returns the stored fill, or ``None`` if this ``broker_fill_id`` is
        already recorded for the account -- an idempotent no-op, which is what
        makes recovery replay exactly-once rather than at-least-once.

        The fill row and its legs are written in a single transaction. A process
        killed at any point either has all of it or none: WAL discards an
        incomplete commit frame on recovery, so there is no such thing as a fill
        without its legs.
        """
        legs = fill.legs()
        total = sum((leg.amount for leg in legs), ZERO)
        if total != ZERO:
            # Checked before the write, not after. The books must balance after
            # every event, and an unbalanced event must never reach disk.
            raise FatalError(
                f"double-entry legs for {fill.symbol} sum to {total}, not zero"
            )

        fill_id = fill.id or new_id("fill")
        try:
            with transaction(self._conn) as tx:
                tx.execute(
                    """
                    INSERT INTO fills
                        (id, account_id, order_id, client_order_id, broker_fill_id,
                         approval_id, symbol, side, qty, price, fee, currency,
                         venue, trace_id, strategy, idea, ts)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        fill_id, fill.account_id, fill.order_id, fill.client_order_id,
                        fill.broker_fill_id, fill.approval_id, fill.symbol, fill.side,
                        fill.qty, str(fill.price), str(fill.fee), fill.currency,
                        fill.venue, fill.trace_id, fill.strategy, fill.idea, fill.ts,
                    ),
                )
                tx.executemany(
                    """
                    INSERT INTO entries
                        (id, event_id, account_id, leg, symbol, amount, currency, ts)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    [
                        (
                            new_id("ent"), fill_id, fill.account_id, leg.leg,
                            leg.symbol, str(leg.amount), leg.currency, fill.ts,
                        )
                        for leg in legs
                    ],
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc):
                return None  # already recorded; replay is a no-op
            raise

        return replace(fill, id=fill_id)

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def replay(self, fills: Sequence[Fill]) -> dict[str, int]:
        """Reconcile a batch of broker fills into the ledger after a restart.

        Each is inserted only if its ``broker_fill_id`` is not already present,
        so replaying the same batch twice changes nothing. This is the ledger's
        own application of *"order placement is never blind-retried"*: recovery
        reconciles by key rather than re-appending.
        """
        applied = skipped = 0
        for fill in fills:
            if self.record_fill(fill) is None:
                skipped += 1
            else:
                applied += 1
        return {"applied": applied, "skipped": skipped}

    def verify(self) -> dict[str, Any]:
        """Integrity check: every fill has legs, and every event balances.

        A fill whose legs are missing would mean a write was torn -- the thing
        atomicity is supposed to make impossible. This is how the test proves it
        rather than assuming it.
        """
        orphans = [
            row["id"]
            for row in self._conn.execute(
                "SELECT f.id FROM fills f "
                "LEFT JOIN entries e ON e.event_id = f.id "
                "WHERE e.id IS NULL"
            )
        ]
        unbalanced = []
        for row in self._conn.execute(
            "SELECT event_id, GROUP_CONCAT(amount) AS amounts FROM entries "
            "GROUP BY event_id"
        ):
            total = sum((Decimal(a) for a in row["amounts"].split(",")), ZERO)
            if total != ZERO:
                unbalanced.append((row["event_id"], total))
        return {
            "fills": self.count_fills(),
            "orphan_fills": orphans,
            "unbalanced_events": unbalanced,
            "consistent": not orphans and not unbalanced,
        }

    # ------------------------------------------------------------------
    # Read and derive
    # ------------------------------------------------------------------

    def fills(self, *, account_id: str | None = None) -> list[Fill]:
        sql = "SELECT * FROM fills"
        params: tuple[Any, ...] = ()
        if account_id is not None:
            sql += " WHERE account_id = ?"
            params = (account_id,)
        sql += " ORDER BY ts, id"
        return [Fill.from_row(r) for r in self._conn.execute(sql, params)]

    def count_fills(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0])

    def has_broker_fill(self, account_id: str, broker_fill_id: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM fills WHERE account_id = ? AND broker_fill_id = ?",
                (account_id, broker_fill_id),
            ).fetchone()
            is not None
        )

    def rebuild(self, *, account_id: str | None = None) -> dict[tuple[str, str], Position]:
        """Recompute positions from fills. The authoritative derivation."""
        return rebuild_positions(self.fills(account_id=account_id))

    def snapshot_positions(self, ts: str) -> int:
        """Persist the derived positions. Overwritable — this table is not a ledger."""
        positions = self.rebuild()
        with transaction(self._conn) as tx:
            tx.execute("DELETE FROM positions")
            tx.executemany(
                "INSERT INTO positions (account_id, symbol, qty, avg_entry, "
                "realized_pnl, fees_paid, updated_at) VALUES (?,?,?,?,?,?,?)",
                [
                    (p.account_id, p.symbol, p.qty, str(p.avg_entry),
                     str(p.realized_pnl), str(p.fees_paid), ts)
                    for p in positions.values()
                ],
            )
        return len(positions)

    def stored_positions(self) -> dict[tuple[str, str], Position]:
        return {
            (r["account_id"], r["symbol"]): Position(
                account_id=r["account_id"],
                symbol=r["symbol"],
                qty=r["qty"],
                avg_entry=Decimal(r["avg_entry"]),
                realized_pnl=Decimal(r["realized_pnl"]),
                fees_paid=Decimal(r["fees_paid"]),
            )
            for r in self._conn.execute("SELECT * FROM positions")
        }
