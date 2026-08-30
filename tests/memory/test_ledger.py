# Spec: Genesis Markdown/40-Memory/Trade Ledger.md
"""Append-only, double-entry, Decimal, and rebuildable positions."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from genesis.errors import FatalError
from genesis.memory.ledger import Fill, Position, TradeLedger, rebuild_positions

D = Decimal


@pytest.fixture
def ledger(tmp_path: Path) -> TradeLedger:
    instance = TradeLedger(tmp_path / "ledger.db")
    yield instance
    instance.close()


def fill(**kw) -> Fill:
    base = dict(
        account_id="primary", client_order_id="gen_1", broker_fill_id="bf_1",
        approval_id="appr_1", symbol="NVDA", side="buy", qty=100,
        price=D("100.00"), fee=D("1.00"), trace_id="tr_1",
        ts="2026-08-29T14:31:00.000Z",
    )
    base.update(kw)
    return Fill(**base)


# --------------------------------------------------------------------------
# Append-only, at the database level
# --------------------------------------------------------------------------


def seed_every_money_table(ledger: TradeLedger) -> None:
    """Put one row in each append-only table.

    SQLite row triggers fire per matched row, so an UPDATE against an empty
    table succeeds trivially and would make this test pass for the wrong reason.
    """
    ledger.record_fill(fill())  # fills + entries
    ledger.connection.execute(
        "INSERT INTO orders (id, account_id, client_order_id, approval_id, symbol, "
        "side, qty, order_type, state, trace_id, ts) "
        "VALUES ('ord_1','primary','gen_1','appr_1','NVDA','buy',100,'limit',"
        "'filled','tr_1','2026-08-29T14:31:00.000Z')"
    )
    ledger.connection.execute(
        "INSERT INTO cash_flows (id, account_id, kind, amount, trace_id, ts) "
        "VALUES ('cf_1','primary','deposit','1000.00','tr_1',"
        "'2026-08-29T14:31:00.000Z')"
    )


@pytest.mark.parametrize("table", ["fills", "orders", "cash_flows", "entries"])
def test_update_and_delete_fail_at_the_database_level(
    ledger: TradeLedger, table: str
) -> None:
    """Never UPDATE a fill — enforced, not requested."""
    seed_every_money_table(ledger)
    assert ledger.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.connection.execute(f"UPDATE {table} SET id = 'x'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.connection.execute(f"DELETE FROM {table}")


def test_positions_table_is_rebuildable_not_append_only(ledger: TradeLedger) -> None:
    """Derived, not authoritative: it must be droppable and recomputable."""
    ledger.record_fill(fill())
    ledger.snapshot_positions("2026-08-29T16:00:00.000Z")
    ledger.connection.execute("DELETE FROM positions")  # must not raise
    assert ledger.stored_positions() == {}
    ledger.snapshot_positions("2026-08-29T16:00:00.000Z")
    assert len(ledger.stored_positions()) == 1


# --------------------------------------------------------------------------
# Required-field invariants
# --------------------------------------------------------------------------


def test_a_fill_without_an_approval_id_is_rejected() -> None:
    """A fill without one means an order bypassed the risk engine."""
    with pytest.raises(FatalError, match="risk engine"):
        fill(approval_id="")


def test_float_in_a_monetary_field_is_refused() -> None:
    """Conventions § Money: Decimal, never float. Everywhere. No exceptions."""
    with pytest.raises(FatalError, match="float"):
        fill(price=121.06)
    with pytest.raises(FatalError, match="float"):
        fill(fee=0.6)


def test_prices_survive_the_database_round_trip_exactly(ledger: TradeLedger) -> None:
    """SQLite REAL would silently make this a float."""
    ledger.record_fill(fill(price=D("121.06"), fee=D("0.60")))
    stored = ledger.fills()[0]
    assert stored.price == D("121.06")
    assert isinstance(stored.price, Decimal)
    assert str(stored.price) == "121.06"


def test_no_monetary_column_is_declared_real(ledger: TradeLedger) -> None:
    for table in ("fills", "entries", "cash_flows"):
        for column in ledger.connection.execute(f"PRAGMA table_info({table})"):
            if column["name"] in ("price", "fee", "amount"):
                assert column["type"] == "TEXT", f"{table}.{column['name']} is REAL"


@pytest.mark.parametrize("bad", [{"qty": 0}, {"qty": -5}, {"side": "long"}])
def test_malformed_fills_are_rejected(bad: dict) -> None:
    with pytest.raises(FatalError):
        fill(**bad)


# --------------------------------------------------------------------------
# Double-entry
# --------------------------------------------------------------------------


def test_legs_sum_to_zero(ledger: TradeLedger) -> None:
    assert sum(leg.amount for leg in fill().legs()) == D("0")


def test_sell_legs_also_balance() -> None:
    assert sum(leg.amount for leg in fill(side="sell").legs()) == D("0")


def test_every_stored_event_balances(ledger: TradeLedger) -> None:
    ledger.record_fill(fill(broker_fill_id="bf_1", side="buy"))
    ledger.record_fill(fill(broker_fill_id="bf_2", side="sell", price=D("105.00")))
    report = ledger.verify()
    assert report["unbalanced_events"] == []
    assert report["consistent"]


def test_a_fill_always_has_its_legs(ledger: TradeLedger) -> None:
    ledger.record_fill(fill())
    assert ledger.verify()["orphan_fills"] == []


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


def test_the_same_broker_fill_is_recorded_once(ledger: TradeLedger) -> None:
    assert ledger.record_fill(fill()) is not None
    assert ledger.record_fill(fill()) is None
    assert ledger.count_fills() == 1


def test_different_accounts_are_independent(ledger: TradeLedger) -> None:
    """Open Questions §10: multi-account from day one."""
    ledger.record_fill(fill(account_id="primary"))
    ledger.record_fill(fill(account_id="funded"))
    assert ledger.count_fills() == 2


# --------------------------------------------------------------------------
# The reducer — a pure function
# --------------------------------------------------------------------------


def test_reducer_is_pure_and_takes_no_ledger() -> None:
    positions = rebuild_positions([fill()])
    assert positions[("primary", "NVDA")].qty == 100


def test_open_then_add_averages_the_entry() -> None:
    positions = rebuild_positions([
        fill(broker_fill_id="a", qty=100, price=D("100.00"), ts="...01"),
        fill(broker_fill_id="b", qty=100, price=D("110.00"), ts="...02"),
    ])
    pos = positions[("primary", "NVDA")]
    assert pos.qty == 200
    assert pos.avg_entry == D("105.00")


def test_close_realizes_pnl_net_of_fees() -> None:
    """A strategy profitable before fees and losing after must show as losing."""
    positions = rebuild_positions([
        fill(broker_fill_id="a", side="buy", qty=100, price=D("100.00"),
             fee=D("1.00"), ts="...01"),
        fill(broker_fill_id="b", side="sell", qty=100, price=D("100.50"),
             fee=D("60.00"), ts="...02"),
    ])
    pos = positions[("primary", "NVDA")]
    assert pos.qty == 0
    assert pos.fees_paid == D("61.00")
    assert pos.realized_pnl == D("50.00") - D("61.00")
    assert pos.realized_pnl < 0, "gross profit, net loss — must read as a loss"


def test_partial_close_keeps_the_remainder() -> None:
    positions = rebuild_positions([
        fill(broker_fill_id="a", side="buy", qty=100, price=D("100.00"), fee=D("0"), ts="...01"),
        fill(broker_fill_id="b", side="sell", qty=40, price=D("110.00"), fee=D("0"), ts="...02"),
    ])
    pos = positions[("primary", "NVDA")]
    assert pos.qty == 60
    assert pos.avg_entry == D("100.00")
    assert pos.realized_pnl == D("400.00")


def test_reversal_through_flat_opens_the_other_side() -> None:
    positions = rebuild_positions([
        fill(broker_fill_id="a", side="buy", qty=100, price=D("100.00"), fee=D("0"), ts="...01"),
        fill(broker_fill_id="b", side="sell", qty=150, price=D("110.00"), fee=D("0"), ts="...02"),
    ])
    pos = positions[("primary", "NVDA")]
    assert pos.qty == -50
    assert pos.avg_entry == D("110.00")
    assert pos.realized_pnl == D("1000.00")


def test_short_then_cover_realizes_correctly() -> None:
    positions = rebuild_positions([
        fill(broker_fill_id="a", side="sell", qty=100, price=D("100.00"), fee=D("0"), ts="...01"),
        fill(broker_fill_id="b", side="buy", qty=100, price=D("90.00"), fee=D("0"), ts="...02"),
    ])
    pos = positions[("primary", "NVDA")]
    assert pos.qty == 0
    assert pos.realized_pnl == D("1000.00")


def test_positions_are_keyed_by_account_and_symbol() -> None:
    positions = rebuild_positions([
        fill(account_id="primary", broker_fill_id="a"),
        fill(account_id="funded", broker_fill_id="b"),
    ])
    assert set(positions) == {("primary", "NVDA"), ("funded", "NVDA")}


# --------------------------------------------------------------------------
# Rebuild is a continuous test
# --------------------------------------------------------------------------


def test_rebuild_matches_the_stored_snapshot(ledger: TradeLedger) -> None:
    """The nightly check: divergence is a bug alert."""
    for i, (side, price) in enumerate(
        [("buy", "100.00"), ("buy", "110.00"), ("sell", "120.00")]
    ):
        ledger.record_fill(
            fill(broker_fill_id=f"bf_{i}", side=side, qty=50, price=D(price),
                 ts=f"2026-08-29T14:31:0{i}.000Z")
        )
    ledger.snapshot_positions("2026-08-29T16:00:00.000Z")
    assert ledger.rebuild() == ledger.stored_positions()


def test_positions_can_be_dropped_and_rebuilt_identically(ledger: TradeLedger) -> None:
    ledger.record_fill(fill())
    before = ledger.rebuild()
    ledger.connection.execute("DELETE FROM positions")
    assert ledger.rebuild() == before
