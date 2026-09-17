# Spec: Genesis Markdown/20-Agents/Execution/Agent — Position And PnL Accountant.md
"""Position truth, heat, staleness, and zero-tolerance reconciliation."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal as D
from pathlib import Path

import pytest

from genesis.agents.execution.accountant import Accountant, PositionView
from genesis.memory.ledger import Fill, TradeLedger

NOW = dt.datetime(2026, 9, 17, 18, 30, tzinfo=dt.UTC)  # inside the CME day


@pytest.fixture()
def ledger(tmp_path: Path) -> TradeLedger:
    instance = TradeLedger(tmp_path / "ledger.db")
    yield instance
    instance.close()


def fill(**kw) -> Fill:
    base = dict(
        account_id="DU123", client_order_id="gen_1", broker_fill_id="bf_1",
        approval_id="appr_1", symbol="NQZ6", side="buy", qty=2,
        price=D("20000.00"), fee=D("4.00"), trace_id="tr_1",
        ts="2026-09-17T18:05:00.000+00:00",
    )
    base.update(kw)
    return Fill(**base)


class Broker:
    """Only what the accountant reads."""

    account = "DU123"

    def __init__(self, *, qty: int = 2, equity: str = "100000") -> None:
        self.qty = qty
        self.equity = D(equity)
        self.up = True

    def connected(self) -> bool:
        return self.up

    def net_liquidation(self) -> D:
        return self.equity

    def available_funds(self) -> D:
        return self.equity / 2

    def positions(self) -> list[dict]:
        if not self.qty:
            return []
        return [{"con_id": 555, "local_symbol": "NQZ6", "root": "NQ", "qty": self.qty,
                 "multiplier": D(20), "avg_price": D("20000")}]


def quoter(mid: str, *, age_sec: float = 0.0, source: str = "realtime"):
    def q(_key: object) -> dict:
        return {"mid": D(mid), "source": source,
                "ts": (NOW - dt.timedelta(seconds=age_sec)).isoformat()}
    return q


def _stop(ledger: TradeLedger, price: str, *, state: str = "submitted") -> None:
    ledger.record_order({
        "account_id": "DU123", "client_order_id": "gen_stop", "approval_id": "appr_1",
        "symbol": "NQZ6", "side": "sell", "qty": 2, "order_type": "stop",
        "state": state, "trace_id": "tr_1", "role": "stop", "stop_price": price, "ts": "2026-09-17T18:06:00+00:00",
        "con_id": 555,
    })


# --------------------------------------------------------------------------
# position truth and marks
# --------------------------------------------------------------------------


def test_positions_come_from_the_fills(ledger: TradeLedger) -> None:
    ledger.record_fill(fill())
    ledger.record_fill(fill(broker_fill_id="bf_2", client_order_id="gen_2", qty=1,
                            price=D("20100.00")))
    snap = Accountant(ledger=ledger, broker=Broker(qty=3),
                      quote=quoter("20200"), clock=lambda: NOW).snapshot()
    assert [(p.symbol, p.qty) for p in snap.positions] == [("NQZ6", 3)]
    pos = snap.positions[0]
    # 2 @ 20000 + 1 @ 20100, weighted, marked at 20200, x20 multiplier
    assert pos.avg_entry == (D("20000") * 2 + D("20100")) / 3
    assert pos.unrealized == (D("20200") - pos.avg_entry) * 3 * 20


def test_fees_land_in_realized_pnl(ledger: TradeLedger) -> None:
    ledger.record_fill(fill())
    ledger.record_fill(fill(broker_fill_id="bf_2", client_order_id="gen_2", side="sell",
                            price=D("20000.00")))
    snap = Accountant(ledger=ledger, broker=Broker(qty=0), quote=quoter("20000"),
                      clock=lambda: NOW).snapshot()
    assert snap.realized_today == D("-8.00"), "flat at the same price, so only fees remain"
    assert snap.fees_today == D("8.00")


# --------------------------------------------------------------------------
# heat
# --------------------------------------------------------------------------


def test_heat_is_entry_to_stop_times_size(ledger: TradeLedger) -> None:
    ledger.record_fill(fill())
    _stop(ledger, "19950.00")
    snap = Accountant(ledger=ledger, broker=Broker(), quote=quoter("20000"),
                      clock=lambda: NOW).snapshot()
    # (20000 - 19950) x 2 x 20 = 2000 on 100k equity
    assert snap.positions[0].risk_open == D("2000")
    assert snap.portfolio_heat_pct == D("2")
    assert snap.positions[0].protected


def test_an_unprotected_position_is_the_riskiest_thing_on_the_page(ledger: TradeLedger) -> None:
    """No stop is not zero risk -- the naive reading is exactly backwards."""
    ledger.record_fill(fill())
    snap = Accountant(ledger=ledger, broker=Broker(), quote=quoter("20000"),
                      clock=lambda: NOW).snapshot()
    assert snap.positions[0].risk_open == D("20000") * 2 * 20
    assert not snap.positions[0].protected
    assert any("no protective stop" in p for p in snap.problems)
    assert not snap.auto_mode_permitted


def test_a_filled_stop_no_longer_protects(ledger: TradeLedger) -> None:
    ledger.record_fill(fill())
    _stop(ledger, "19950.00", state="filled")
    snap = Accountant(ledger=ledger, broker=Broker(), quote=quoter("20000"),
                      clock=lambda: NOW).snapshot()
    assert not snap.positions[0].protected


def test_a_short_positions_stop_is_above_it(ledger: TradeLedger) -> None:
    ledger.record_fill(fill(side="sell"))
    ledger.record_order({
        "account_id": "DU123", "client_order_id": "gen_stop", "approval_id": "appr_1",
        "symbol": "NQZ6", "side": "buy", "qty": 2, "order_type": "stop", "state": "submitted",
        "trace_id": "tr_1", "role": "stop", "stop_price": "20050.00", "con_id": 555, "ts": "2026-09-17T18:06:00+00:00",
    })
    snap = Accountant(ledger=ledger, broker=Broker(qty=-2), quote=quoter("20000"),
                      clock=lambda: NOW).snapshot()
    pos = snap.positions[0]
    assert pos.side == "short"
    assert pos.risk_open == (D("20050") - D("20000")) * 2 * 20


# --------------------------------------------------------------------------
# staleness
# --------------------------------------------------------------------------


def test_a_stale_mark_degrades_the_snapshot_and_suspends_auto(ledger: TradeLedger) -> None:
    ledger.record_fill(fill())
    _stop(ledger, "19950.00")
    snap = Accountant(ledger=ledger, broker=Broker(), clock=lambda: NOW,
                      quote=quoter("20000", age_sec=900, source="delayed")).snapshot()
    assert snap.degraded
    assert any("900000 ms old" in r for r in snap.degraded_reasons)
    assert not snap.auto_mode_permitted


def test_no_mark_means_no_unrealized_rather_than_zero(ledger: TradeLedger) -> None:
    ledger.record_fill(fill())
    snap = Accountant(ledger=ledger, broker=Broker(), quote=None, clock=lambda: NOW).snapshot()
    assert snap.unrealized is None
    assert snap.net_today is None
    assert snap.degraded


def test_no_broker_means_no_percentages_rather_than_invented_ones(ledger: TradeLedger) -> None:
    ledger.record_fill(fill())
    snap = Accountant(ledger=ledger, broker=None, quote=quoter("20000"),
                      clock=lambda: NOW).snapshot()
    assert snap.equity is None
    assert snap.portfolio_heat_pct is None
    assert snap.gross_exposure_pct is None


# --------------------------------------------------------------------------
# reconciliation -- zero tolerance
# --------------------------------------------------------------------------


def test_one_contract_of_disagreement_is_a_mismatch(ledger: TradeLedger) -> None:
    ledger.record_fill(fill(qty=2))
    result = Accountant(ledger=ledger, broker=Broker(qty=1), clock=lambda: NOW).reconcile()
    assert result["matched"] is False
    assert "ledger 2 vs broker 1" in result["detail"]


def test_agreement_is_recorded(ledger: TradeLedger) -> None:
    ledger.record_fill(fill(qty=2))
    result = Accountant(ledger=ledger, broker=Broker(qty=2), clock=lambda: NOW).reconcile()
    assert result["matched"] is True
    snap = Accountant(ledger=ledger, broker=Broker(qty=2), quote=quoter("20000"),
                      clock=lambda: NOW).snapshot()
    assert snap.reconciled is True and snap.reconciled_at == result["at"]


def test_an_unreachable_broker_is_unknown_not_matched(ledger: TradeLedger) -> None:
    broker = Broker(qty=2)
    broker.up = False
    result = Accountant(ledger=ledger, broker=broker, clock=lambda: NOW).reconcile()
    assert result["matched"] is None, "fail closed: unknown is never 'agreed'"
    assert "unreachable" in result["detail"]


def test_a_position_the_broker_has_and_we_do_not_is_a_mismatch(ledger: TradeLedger) -> None:
    result = Accountant(ledger=ledger, broker=Broker(qty=2), clock=lambda: NOW).reconcile()
    assert result["matched"] is False
    assert "ledger 0 vs broker 2" in result["detail"]


# --------------------------------------------------------------------------
# the position cache is never trusted
# --------------------------------------------------------------------------


def test_cache_drift_is_reported_not_used(ledger: TradeLedger) -> None:
    ledger.record_fill(fill())
    ledger.snapshot_positions("2026-09-17T18:10:00+00:00")
    ledger.record_fill(fill(broker_fill_id="bf_2", client_order_id="gen_2", qty=1))
    snap = Accountant(ledger=ledger, broker=Broker(qty=3), quote=quoter("20000"),
                      clock=lambda: NOW).snapshot()
    assert snap.positions[0].qty == 3, "the fills are the truth"
    assert any("cache drift" in p for p in snap.problems)


def test_the_snapshot_serialises_without_floats(ledger: TradeLedger) -> None:
    ledger.record_fill(fill())
    _stop(ledger, "19950.00")
    body = Accountant(ledger=ledger, broker=Broker(), quote=quoter("20000"),
                      clock=lambda: NOW).snapshot().to_dict()
    import json

    text = json.dumps(body)
    assert "e+" not in text and "e-" not in text
    assert body["pnl"]["unrealized"] == "0.00"
    assert isinstance(body["positions"][0]["avg_entry"], str)


def test_the_accountant_has_no_model() -> None:
    from genesis.agents.execution.accountant import DECLARATION

    assert DECLARATION.model_tier == "none"
    assert PositionView is not None


# --------------------------------------------------------------------------
# the two symbol spaces
# --------------------------------------------------------------------------


def test_the_broker_and_the_ledger_name_the_same_contract_differently(
    ledger: TradeLedger,
) -> None:
    """The ledger holds `FUT:CME:NQ:2026-12`; IBKR says `NQZ6`.

    Comparing the spellings directly makes every real position look like a
    mismatch, and a mismatch is a halt. Caught here because the fixture above
    uses one spelling for both and would never have shown it.
    """
    ledger.record_fill(fill(symbol="FUT:CME:NQ:2026-12"))
    ledger.record_order({
        "account_id": "DU123", "client_order_id": "gen_entry", "approval_id": "appr_1",
        "symbol": "FUT:CME:NQ:2026-12", "side": "buy", "qty": 2, "order_type": "market",
        "state": "filled", "trace_id": "tr_1", "role": "entry", "con_id": 555,
        "ts": "2026-09-17T18:05:00+00:00",
    })
    accountant = Accountant(ledger=ledger, broker=Broker(qty=2), quote=quoter("20000"),
                            clock=lambda: NOW)
    assert accountant.reconcile()["matched"] is True
    snap = accountant.snapshot()
    assert [p.symbol for p in snap.positions] == ["FUT:CME:NQ:2026-12"]
    assert snap.positions[0].multiplier == D(20), "the broker's multiplier still found it"


def test_a_broker_position_the_ledger_never_saw_is_a_mismatch(ledger: TradeLedger) -> None:
    """Unresolvable is not the same as absent, and both are mismatches."""
    result = Accountant(ledger=ledger, broker=Broker(qty=2), clock=lambda: NOW).reconcile()
    assert result["matched"] is False
    assert "NQZ6" in result["detail"]
