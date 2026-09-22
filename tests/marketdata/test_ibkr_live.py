# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""The live IBKR session, one full session against a fake gateway.

Backfill lands in the store, a closed bar is stored and pushed, the forming bar
is pushed and NOT stored, the account arrives with its mode read from the
account id, and a dropped connection ends the session instead of hanging.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from genesis.config import load_config
from genesis.marketdata import ibkr_live
from genesis.marketdata.store import close_open_stores, open_store

from tests.marketdata.test_ibkr import FakeBar, FakeIB, FakeSubscription

pytest.importorskip("ib_async")

NOW = datetime.now(UTC).replace(second=0, microsecond=0)
SOON = NOW + timedelta(days=60)
NQ = f"FUT:CME:NQ:{SOON.year}-{SOON.month:02d}"


@dataclass
class Value:
    account: str
    tag: str
    value: str
    currency: str


class LiveIB(FakeIB):
    def __init__(self) -> None:
        # Two closed 1m bars for the backfill, then a stream of three.
        base = NOW - timedelta(minutes=3)
        bars = [FakeBar(base + timedelta(minutes=i), 100 + i, 101 + i, 99 + i, 100.5 + i, 10) for i in range(3)]
        super().__init__(bars=bars)
        self.subscription = FakeSubscription(bars)
        self.ticks = 0

    def reqHistoricalData(self, contract, **kwargs):  # noqa: N802
        if kwargs.get("keepUpToDate"):
            return self.subscription
        return super().reqHistoricalData(contract, **kwargs)

    def sleep(self, _seconds: float) -> None:
        self.ticks += 1
        if self.ticks == 1:  # a new bar prints: the old forming bar has closed
            self.subscription.push(FakeBar(NOW, 110, 111, 109, 110.5, 7))
        else:
            self._connected = False

    def managedAccounts(self):  # noqa: N802
        return ["DU1234567"]

    def accountValues(self):  # noqa: N802
        return [
            Value("DU1234567", "NetLiquidation", "1000000.00", "USD"),
            Value("DU1234567", "NetLiquidation", "1000000.00", "BASE"),
            Value("DU1234567", "Leverage", "0", ""),
        ]

    def portfolio(self):
        return [SimpleNamespace(
            account="DU1234567", position=1.0, marketPrice=110.5, marketValue=2210.0,
            averageCost=2000.0, unrealizedPNL=210.0, realizedPNL=0.0,
            contract=SimpleNamespace(localSymbol="NQZ6", symbol="NQ", secType="FUT"),
        )]


def test_one_live_session(tmp_path) -> None:
    config = load_config(None)
    md = config.marketdata.model_copy(update={
        "store_path": tmp_path / "market.duckdb",
        "budget_path": tmp_path / "budget.db",
        "live": [{"symbol_id": NQ, "timeframe": "1m"}],
    })
    config = config.model_copy(update={"marketdata": md})

    events: list[tuple[str, dict[str, Any]]] = []
    live = ibkr_live.IbkrLive(config, lambda e, d: events.append((e, d)))
    ib = LiveIB()
    configure = live._configure

    def fake_configure() -> None:  # every session rebuilds its connection; fake it after
        configure()
        live.connection._ib = ib
        live.connection.connect = lambda: ib  # type: ignore[method-assign]

    live._configure = fake_configure  # type: ignore[method-assign]

    try:
        with pytest.raises(Exception, match="disconnected"):
            live._session()

        store = open_store(md.store_path)
        held = store.read(NQ, "1m")
        closed = [d for e, d in events if e == "market.bar" and d["closed"]]
        forming = [d for e, d in events if e == "market.bar" and not d["closed"]]

        # the bar that was forming when streaming began is now closed and stored
        assert closed and closed[0]["bar"]["close"] == "102.5"
        assert any(b.ts == ib.subscription[2].date for b in held)
        # the new forming bar was pushed, and never written
        assert forming[-1]["bar"]["time"] == int(NOW.timestamp())
        assert all(b.ts != NOW for b in held)

        (account,) = [d for e, d in events if e == "broker.account"]
        assert account["mode"] == "paper"
        assert account["values"]["DU1234567"] == {"NetLiquidation": {"value": "1000000.00", "currency": "USD"}}
        assert account["positions"][0]["symbol"] == "NQZ6"
        assert ("broker.connection", {"broker": "ibkr", "state": "live", "detail": "1 series streaming"}) in events
    finally:
        close_open_stores()


def test_a_live_account_id_reads_as_live() -> None:
    ib = SimpleNamespace(managedAccounts=lambda: ["U7654321"], accountValues=list, portfolio=list)
    assert ibkr_live.account_snapshot(ib)["mode"] == "live"
