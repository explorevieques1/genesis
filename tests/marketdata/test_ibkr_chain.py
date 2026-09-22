# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""IBKR inside the real chain: store, budget, fallback, and the Charting Engine.

The unit tests in ``test_ibkr.py`` check the adapter in isolation. These check
the thing that isolation cannot: that IBKR behaves correctly *as one link in
the chain* — that its bars reach the store as Decimal, that a dead gateway
degrades to the next source instead of failing the request, that the budget
actually meters it, and that the Charting Engine draws what comes out.

The claim being tested is the one the whole session rests on: **adding IBKR is
a config change, not a code change.**
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from genesis.errors import DegradedError, TransientError
from genesis.marketdata.adapters.ibkr import IbkrAdapter, IbkrConnection
from genesis.marketdata.budget import Budget
from genesis.marketdata.interface import BarRequest
from genesis.marketdata.source import StoreBarSource
from genesis.marketdata.store import BarStore

pytest.importorskip("ib_async")


def _front_month() -> str:
    soon = datetime.now(UTC) + timedelta(days=60)
    return f"FUT:CME:ES:{soon.year}-{soon.month:02d}"


ES = _front_month()


@dataclass
class FakeBar:
    date: Any
    open: float
    high: float
    low: float
    close: float
    volume: float


class FakeIB:
    def __init__(self, n: int = 400):
        self.n = n
        self.calls = 0

    def isConnected(self) -> bool:  # noqa: N802
        return True

    def reqMarketDataType(self, code: int) -> None:  # noqa: N802
        pass

    def qualifyContracts(self, *contracts):  # noqa: N802
        return list(contracts)

    def reqHistoricalData(self, contract, **kwargs):  # noqa: N802
        self.calls += 1
        base = datetime.now(UTC).replace(
            minute=0, second=0, microsecond=0
        ) - timedelta(hours=self.n)
        # Quarter points -- the value that has no exact float representation,
        # which is the whole reason the store holds Decimal.
        return [
            FakeBar(
                base + timedelta(hours=i),
                4500.25 + i, 4510.25 + i, 4495.25 + i, 4505.25 + i, 1000 + i,
            )
            for i in range(self.n)
        ]

    def sleep(self, _s: float) -> None:
        pass


class DeadGateway(FakeIB):
    """A gateway that is not there. The common case, not an exotic one."""

    def reqHistoricalData(self, contract, **kwargs):  # noqa: N802
        raise ConnectionRefusedError(111, "Connect call failed")


def ibkr(ib: Any, tier: int = 3) -> IbkrAdapter:
    connection = IbkrConnection(use_watchdog=False)
    connection._ib = ib
    return IbkrAdapter(connection=connection, tier=tier)


class OtherSource:
    """A second adapter, so 'fell through the chain' is observable."""

    def __init__(self):
        self.calls = 0

    def capabilities(self):
        from genesis.marketdata.interface import AdapterCapabilities

        return AdapterCapabilities(
            name="backup",
            tier=3,
            timeframes=frozenset({"1H", "1D"}),
            asset_classes=frozenset({"FUT", "EQ"}),
        )

    def fetch(self, request: BarRequest):
        from genesis.marketdata.normalize import normalise_bars

        self.calls += 1
        base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        return normalise_bars(
            [
                {
                    "ts": base - timedelta(hours=i),
                    "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10,
                }
                for i in range(400)
            ],
            symbol_id=request.symbol_id,
            timeframe=request.timeframe,
            source="backup",
            tier=3,
        )


@pytest.fixture
def store(tmp_path):
    s = BarStore(tmp_path / "m.duckdb")
    yield s
    s.close()


def test_ibkr_bars_reach_the_store_as_decimal(store):
    """End to end: IBKR -> normalize -> store, with the quarter point intact."""
    source = StoreBarSource(store=store, adapters=[ibkr(FakeIB())])
    source.fetch(ES, "1H", bars=100)

    rows = store.read(ES, "1H", limit=5)
    assert rows
    assert all(isinstance(r.close, Decimal) for r in rows)
    assert all(r.source == "ibkr" and r.tier == 3 for r in rows)
    # The exact value a float would have mangled.
    assert rows[0].close.as_tuple().exponent <= -2
    assert str(rows[0].open).endswith(".25000000")


def test_a_dead_gateway_falls_through_to_the_next_source(store):
    """IBKR being down must degrade the chain, not fail the request. This is
    the difference between 'the market data plane is offline' and 'the best
    source is offline'."""
    backup = OtherSource()
    source = StoreBarSource(
        store=store, adapters=[ibkr(DeadGateway()), backup]
    )
    frame = source.fetch(ES, "1H", bars=100)

    assert backup.calls == 1
    assert frame.source == "backup"
    assert len(frame) == 100


def test_the_chain_reports_every_failure_not_just_the_last(store):
    """A chain that says 'yfinance failed' while IBKR was never tried is how a
    fallback chain silently stops being one."""
    source = StoreBarSource(store=store, adapters=[ibkr(DeadGateway())])
    with pytest.raises(DegradedError) as caught:
        source.fetch(ES, "1H", bars=100)
    assert "ibkr" in caught.value.reason


def test_the_budget_meters_ibkr_through_the_chain(store, tmp_path):
    """The pacing rules are not decoration: they are consumed on a real fetch,
    which is what makes 'agents never see a 429' true."""
    budget = Budget(tmp_path / "b.db")
    adapter = ibkr(FakeIB())
    source = StoreBarSource(store=store, adapters=[adapter], budget=budget)
    source.fetch(ES, "1H", bars=100)

    spent = budget.conn.execute(
        "SELECT rule, COUNT(*) FROM spend WHERE vendor='ibkr' GROUP BY rule"
    ).fetchall()
    assert {row["rule"] for row in spent} == {
        "sixty-per-ten-minutes",
        "no-identical-within-15s",
        "six-per-contract-per-2s",
    }
    budget.close()


def test_a_second_run_does_not_ask_ibkr_again(store):
    """The store's promise holds for the broker feed exactly as for the rest.
    IBKR is the vendor where it matters most -- 60 requests per 10 minutes is
    the tightest budget in the chain."""
    ib = FakeIB()
    adapter = ibkr(ib)
    StoreBarSource(store=store, adapters=[adapter]).fetch(ES, "1H", bars=100)
    assert ib.calls == 1

    StoreBarSource(store=store, adapters=[adapter]).fetch(ES, "1H", bars=100)
    assert ib.calls == 1


def test_the_charting_engine_draws_ibkr_bars_unchanged(store):
    """The claim from the plane session, now with IBKR behind it: nothing above
    the BarSource interface changed."""
    from genesis.charting.compose import compose_default
    from genesis.charting.levels import compute_levels
    from genesis.charting.structure import read_structure

    source = StoreBarSource(store=store, adapters=[ibkr(FakeIB())])
    frame = source.fetch(ES, "1H", bars=300)

    spec = compose_default(frame, compute_levels(frame), read_structure(frame))
    assert spec.symbol == ES
    assert frame.tier == 3


def test_promoting_ibkr_to_tier_1_is_a_config_value_not_a_code_change(store):
    """The tier travels from config to the adapter to the bar to the chart.
    Promotion is one number in one file -- which is exactly why the gate has to
    be a recorded measurement rather than a habit."""
    source = StoreBarSource(store=store, adapters=[ibkr(FakeIB(), tier=1)])
    frame = source.fetch(ES, "1H", bars=100)

    assert frame.tier == 1
    assert store.read(ES, "1H", limit=1)[0].tier == 1
    # And a tier-2 minimum is now satisfiable, which it was not at tier 3.
    assert store.read(ES, "1H", min_tier=2)


def test_a_tier_3_ibkr_cannot_satisfy_a_tier_2_read(store):
    """Market Data Sources: a tier-3 bar never silently satisfies tier 2.
    Before promotion, IBKR is tier 3 and this is what that means in practice."""
    source = StoreBarSource(store=store, adapters=[ibkr(FakeIB(), tier=3)])
    source.fetch(ES, "1H", bars=100)
    assert store.read(ES, "1H", min_tier=2) == []


def test_a_1m_chart_waits_out_the_per_contract_rule_instead_of_failing_over(store, tmp_path):
    """390 one-minute bars is eight one-day chunks; IBKR allows six per contract
    per 2s. The seventh used to fail the whole fetch over to the next source,
    discarding the six already fetched -- a future charted nothing on 1m."""
    budget = Budget(tmp_path / "b.db")
    ib = FakeIB()
    source = StoreBarSource(store=store, adapters=[ibkr(ib)], budget=budget)
    bars = source.fetch(ES, "1m", bars=390)
    assert ib.calls > 6
    assert bars.source == "ibkr"
    budget.close()
