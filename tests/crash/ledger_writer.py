# Spec: Genesis Markdown/40-Memory/Trade Ledger.md
"""Child process for the crash tests. Kills itself at an instrumented point.

Run as:  python ledger_writer.py <db> <kill_point> <n_fills>

``kill_point`` selects where ``os.kill(os.getpid(), SIGKILL)`` fires:

``none``
    Write everything and exit cleanly. The control.
``before_append``
    Die with the fill constructed but not yet written. Nothing should exist.
``mid_append``
    Die *inside* the transaction, after the fill row is inserted but before its
    legs are. This is the torn-write case: the commit never happens, so WAL must
    discard the whole frame and leave no orphan fill.
``after_commit``
    Die immediately after the commit returns, before any in-memory bookkeeping.
    The acknowledged write must survive.
``during_replay``
    Die partway through a recovery replay, so the next replay resumes over a
    partially-applied batch and must still converge to exactly one row per
    broker fill id.

SIGKILL is used, not an exception -- it cannot be caught, so no cleanup, no
context manager exit, and no ``finally`` runs. That is the point.
"""

from __future__ import annotations

import os
import signal
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from genesis.memory.db import transaction  # noqa: E402
from genesis.memory.ledger import Fill, TradeLedger  # noqa: E402


def die() -> None:
    sys.stdout.flush()
    os.kill(os.getpid(), signal.SIGKILL)


def make_fill(i: int) -> Fill:
    return Fill(
        account_id="primary",
        client_order_id=f"gen_{i:04d}",
        broker_fill_id=f"bf_{i:04d}",
        approval_id=f"appr_{i:04d}",
        symbol="NVDA",
        side="buy",
        qty=10,
        price=Decimal("121.06"),
        fee=Decimal("0.60"),
        trace_id="tr_crash",
        ts=f"2026-08-29T14:31:{i:02d}.000Z",
    )


def main() -> None:
    db, kill_point, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
    ledger = TradeLedger(db)

    if kill_point == "before_append":
        make_fill(0)
        die()

    if kill_point == "mid_append":
        # Reproduce record_fill's transaction by hand so we can die between the
        # fill insert and its legs -- the exact torn-write this must survive.
        fill = make_fill(0)
        with transaction(ledger.connection) as tx:
            tx.execute(
                "INSERT INTO fills (id, account_id, order_id, client_order_id, "
                "broker_fill_id, approval_id, symbol, side, qty, price, fee, "
                "currency, venue, trace_id, strategy, idea, ts) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("fill_torn", fill.account_id, None, fill.client_order_id,
                 fill.broker_fill_id, fill.approval_id, fill.symbol, fill.side,
                 fill.qty, str(fill.price), str(fill.fee), "USD", None,
                 fill.trace_id, None, None, fill.ts),
            )
            die()  # inside the transaction: COMMIT is never reached

    if kill_point == "after_commit":
        stored = ledger.record_fill(make_fill(0))
        print(stored.id, flush=True)
        die()  # acknowledged; must survive

    if kill_point == "during_replay":
        batch = [make_fill(i) for i in range(count)]
        for i, fill in enumerate(batch):
            ledger.record_fill(fill)
            if i == count // 2:
                die()

    for i in range(count):
        ledger.record_fill(make_fill(i))
    print("clean", flush=True)


if __name__ == "__main__":
    main()
