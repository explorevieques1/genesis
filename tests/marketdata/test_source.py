# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""StoreBarSource: the contract with the Charting Engine, and the no-network rule.

The two tests that matter most in this file are
:func:`test_store_bar_source_satisfies_the_charting_protocol` and
:func:`test_second_run_makes_no_network_call`. Both are asked for by name in the
session brief -- "prove that by test, not by assertion" and "prove it with a
test that fails if a request escapes" -- and both would be easy to write in a
way that passes without proving anything, so each one is built to fail loudly
if the property it names stops holding.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from genesis.charting.bars import Bars
from genesis.charting.source import BarSource
from genesis.errors import DegradedError
from genesis.marketdata.interface import AdapterCapabilities, BarRequest
from genesis.marketdata.normalize import Bar
from genesis.marketdata.source import StoreBarSource, resolve_symbol, to_bars
from genesis.marketdata.store import BarStore

SYMBOL = "EQ:XNAS:AAPL"


class CountingAdapter:
    """An adapter that generates bars and counts how often it was asked.

    Not a mock. It implements the real Protocol and returns real canonical
    bars, so a test using it exercises the same write path as a vendor would.
    What it adds is a counter, which is the only way to prove from outside that
    the second run did not ask.
    """

    def __init__(self, tier: int = 3, days: int = 300) -> None:
        self.calls = 0
        self.tier = tier
        self.days = days

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name="counting",
            tier=self.tier,
            timeframes=frozenset({"1D", "1H"}),
            asset_classes=frozenset({"EQ", "FUT"}),
        )

    def fetch(self, request: BarRequest):
        self.calls += 1
        out = []
        day = request.start.replace(hour=0, minute=0, second=0, microsecond=0)
        price = Decimal("100.00")
        while day < request.end:
            if day.weekday() < 5:
                price += Decimal("0.25")
                out.append(
                    Bar(
                        symbol_id=request.symbol_id,
                        timeframe=request.timeframe,
                        ts=day,
                        open=price,
                        high=price + Decimal("1.50"),
                        low=price - Decimal("1.25"),
                        close=price + Decimal("0.75"),
                        volume=Decimal("1000000"),
                        source="counting",
                        tier=self.tier,
                        as_of=day,
                        ingested_at=datetime.now(UTC),
                    )
                )
            day += timedelta(days=1)
        return out


@pytest.fixture
def store(tmp_path):
    s = BarStore(tmp_path / "m.duckdb")
    yield s
    s.close()


# -- the contract ----------------------------------------------------------


def test_store_bar_source_satisfies_the_charting_protocol(store):
    """`charting/source.py`: "nothing above this interface changes".

    Proven structurally rather than asserted: the source is bound to a
    `BarSource`-typed name, called through exactly the Protocol's signature,
    and the result is checked to be the Charting Engine's own `Bars` -- the
    same type `GatewayBarSource` returns. Anything the charting code can do
    with one, it can do with the other.
    """
    adapter = CountingAdapter()
    source: BarSource = StoreBarSource(store=store, adapters=[adapter])

    frame = source.fetch("AAPL", "1D", bars=120)

    assert isinstance(frame, Bars)
    assert len(frame) == 120
    assert frame.timeframe == "1D"
    # The properties the level computer and renderer actually reach for.
    assert frame.typical.shape == (120,)
    assert frame.last == pytest.approx(float(frame.close[-1]))


def test_the_existing_charting_path_runs_on_store_bars(store):
    """The real proof: drive levels + structure + spec with store-backed bars.

    A type check says the shapes match. This says the Charting Family's actual
    computation runs unchanged on them, which is the claim being made.
    """
    from genesis.charting.compose import compose_default
    from genesis.charting.levels import compute_levels
    from genesis.charting.structure import read_structure

    source = StoreBarSource(store=store, adapters=[CountingAdapter()])
    frame = source.fetch("AAPL", "1D", bars=200)

    spec = compose_default(frame, compute_levels(frame), read_structure(frame))
    assert spec.symbol == SYMBOL
    assert spec.timeframe == "1D"


# -- the no-network rule ---------------------------------------------------


def test_second_run_makes_no_network_call(store, monkeypatch):
    """The exit criterion. Fails if any request escapes on the second run.

    The socket is not mocked at the adapter boundary -- it is removed from the
    interpreter. If any layer beneath us (an adapter, a vendor SDK, an HTTP
    client warming a pool) opens a connection, this raises. That is stronger
    than counting adapter calls, because it also catches a fetch that happens
    somewhere we did not think to count.
    """
    adapter = CountingAdapter()
    first = StoreBarSource(store=store, adapters=[adapter])
    first.fetch("AAPL", "1D", bars=120)
    assert adapter.calls == 1

    def no_network(*args, **kwargs):
        raise AssertionError("a network call escaped on the second run")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)

    second = StoreBarSource(store=store, adapters=[adapter])
    frame = second.fetch("AAPL", "1D", bars=120)

    assert adapter.calls == 1, "the store was not consulted before the vendor"
    assert len(frame) == 120


def test_an_empty_window_is_not_refetched(store):
    """Coverage, end to end. A contract with no data must be asked about once.

    Without this, a delisted symbol or a holiday-only window is re-fetched on
    every single run forever -- which defeats "never re-fetch a bar you hold"
    precisely where a vendor is most likely to rate limit for asking.
    """

    class EmptyAdapter(CountingAdapter):
        def fetch(self, request):
            self.calls += 1
            return []

    adapter = EmptyAdapter()
    source = StoreBarSource(store=store, adapters=[adapter])

    with pytest.raises(DegradedError):
        source.fetch("AAPL", "1D", bars=120)
    assert adapter.calls == 1

    with pytest.raises(DegradedError):
        source.fetch("AAPL", "1D", bars=120)
    assert adapter.calls == 1, "an empty window was re-fetched"


def test_store_only_source_never_fetches(store):
    """Market Data Sources: backtests read stored bars only."""
    adapter = CountingAdapter()
    source = StoreBarSource(store=store, adapters=[adapter], allow_fetch=False)

    with pytest.raises(DegradedError):
        source.fetch("AAPL", "1D", bars=120)
    assert adapter.calls == 0


# -- symbol resolution -----------------------------------------------------


def test_bare_futures_root_is_refused():
    """Open Questions §13. 'ES' is a family, not an instrument."""
    with pytest.raises(DegradedError, match="family"):
        resolve_symbol("ES")


def test_month_code_resolves_to_a_dated_contract():
    got = resolve_symbol("ESZ5")
    assert got.startswith("FUT:CME:ES:")
    assert got.endswith("-12")


def test_canonical_ids_pass_through():
    assert resolve_symbol("FUT:CME:ES:2025-12") == "FUT:CME:ES:2025-12"


def test_equities_default_to_an_exchange_qualified_id():
    assert resolve_symbol("AAPL") == SYMBOL


# -- the Decimal/float seam ------------------------------------------------


def test_mixed_provenance_reports_the_worst_tier():
    """A window that is 90% tier 1 and 10% tier 3 is a tier 3 window."""
    ts = datetime(2026, 3, 2, tzinfo=UTC)
    rows = [
        Bar(SYMBOL, "1D", ts, *([Decimal("1")] * 5), source="a", tier=1),
        Bar(
            SYMBOL, "1D", ts + timedelta(days=1),
            *([Decimal("1")] * 5), source="b", tier=3,
        ),
    ]
    frame = to_bars(rows)
    assert frame.tier == 3
    assert frame.source == "a+b"
