# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""The store's three promises: write-once, supersede-not-overwrite, coverage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from genesis.errors import DegradedError
from genesis.marketdata.normalize import Bar
from genesis.marketdata.store import BarStore

SYMBOL = "FUT:CME:ES:2025-12"


def bar(day: int, close: str = "4500.25", **kw) -> Bar:
    ts = datetime(2026, 3, day, tzinfo=UTC)
    return Bar(
        symbol_id=kw.pop("symbol_id", SYMBOL),
        timeframe="1D",
        ts=ts,
        open=Decimal("4490.00"),
        high=Decimal("4510.75"),
        low=Decimal("4485.50"),
        close=Decimal(close),
        volume=Decimal("1200000"),
        source=kw.pop("source", "databento"),
        tier=kw.pop("tier", 3),
        as_of=ts,
        ingested_at=datetime.now(UTC),
        **kw,
    )


@pytest.fixture
def store(tmp_path):
    s = BarStore(tmp_path / "m.duckdb")
    yield s
    s.close()


def test_prices_survive_as_decimal(store):
    """A CME quarter point must not round-trip through float.

    4500.25 is representable, but the store's contract is Decimal end to end
    and the test that proves it has to compare against a Decimal, not a float.
    """
    store.write([bar(2, close="4500.25")])
    (got,) = store.read(SYMBOL, "1D")
    assert got.close == Decimal("4500.25")
    assert isinstance(got.close, Decimal)


def test_rewriting_an_identical_bar_is_a_no_op(store):
    store.write([bar(2)])
    counts = store.write([bar(2)])
    assert counts == {"written": 0, "held": 1, "superseded": 0}
    assert len(store.read(SYMBOL, "1D")) == 1


def test_a_restatement_supersedes_and_keeps_both(store):
    """A changed history invalidates backtests, so it is never silent."""
    store.write([bar(2, close="4500.25")])
    counts = store.write([bar(2, close="4501.00")])

    assert counts["superseded"] == 1
    (current,) = store.read(SYMBOL, "1D")
    assert current.close == Decimal("4501.00")
    assert store.superseded(SYMBOL, "1D") == 1


def test_same_bar_from_a_second_vendor_is_not_a_restatement(store):
    """Corroboration, not contradiction. Otherwise the log fills with noise."""
    store.write([bar(2, source="databento")])
    counts = store.write([bar(2, source="ibkr")])
    assert counts["superseded"] == 0
    assert counts["held"] == 1


def test_tier_filters_reads(store):
    """Market Data Sources: a tier-3 bar never silently satisfies tier-2."""
    store.write([bar(2, tier=3), bar(3, tier=1)])
    assert len(store.read(SYMBOL, "1D")) == 2
    assert len(store.read(SYMBOL, "1D", min_tier=2)) == 1


def test_coverage_makes_an_empty_window_a_fact(store):
    """The whole reason coverage exists: emptiness must be distinguishable
    from never-having-asked, or every holiday is re-fetched forever."""
    start = datetime(2026, 3, 1, tzinfo=UTC)
    end = datetime(2026, 3, 8, tzinfo=UTC)

    assert store.covers(SYMBOL, "1D", start, end) is False
    store.record_coverage(
        SYMBOL, "1D", start, end, source="databento", tier=3, bar_count=0
    )
    assert store.covers(SYMBOL, "1D", start, end) is True


def test_coverage_with_a_hole_is_not_coverage(store):
    """Fail closed. Claiming coverage we do not have loses a week silently."""
    store.record_coverage(
        SYMBOL, "1D", datetime(2026, 3, 1, tzinfo=UTC),
        datetime(2026, 3, 5, tzinfo=UTC), source="x", tier=3, bar_count=3,
    )
    store.record_coverage(
        SYMBOL, "1D", datetime(2026, 3, 7, tzinfo=UTC),
        datetime(2026, 3, 10, tzinfo=UTC), source="x", tier=3, bar_count=3,
    )
    assert store.covers(
        SYMBOL, "1D",
        datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 10, tzinfo=UTC),
    ) is False


def test_adjacent_coverage_windows_merge(store):
    for a, b in ((1, 5), (5, 10)):
        store.record_coverage(
            SYMBOL, "1D", datetime(2026, 3, a, tzinfo=UTC),
            datetime(2026, 3, b, tzinfo=UTC), source="x", tier=3, bar_count=3,
        )
    assert store.covers(
        SYMBOL, "1D",
        datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 10, tzinfo=UTC),
    ) is True


def test_continuous_contracts_are_refused(store):
    """Open Questions §13 is unanswered. Refusing costs a session; discovering
    it in six months costs the history."""
    with pytest.raises(DegradedError, match="continuous"):
        store.write([bar(2, symbol_id="CONT:CME:ES:volume:back")])


def test_limit_takes_the_most_recent_bars(store):
    store.write([bar(d) for d in range(2, 12)])
    got = store.read(SYMBOL, "1D", limit=3)
    assert len(got) == 3
    assert got[-1].ts.day == 11
    assert got == sorted(got, key=lambda b: b.ts)


def test_reads_on_another_thread_do_not_steal_a_writes_result(store):
    """`genesis serve` writes from the IBKR session while the UI reads.

    One shared DuckDB connection let a read replace a write's pending result,
    so ``_same_values`` parsed a symbol id as a price (ConversionSyntax).
    """
    import threading

    bars = [bar(d) for d in range(1, 29)]
    store.write(bars)  # every re-write now takes the `existing` path
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                store.symbols()
                store.read(SYMBOL, "1D", limit=5)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
                return

    t = threading.Thread(target=reader)
    t.start()
    try:
        for _ in range(40):
            assert store.write(bars)["held"] == len(bars)
    finally:
        stop.set()
        t.join()
    assert not errors
