# Spec: Genesis Markdown/10-Architecture/Market Data Sources.md
"""The tier-1 gate: does the harness measure honestly, and refuse honestly?

The failure this file guards against is a reconciliation that *passes* when it
should not — because a pass here is what licenses a feed to become execution
truth, and a lenient pass is worse than no harness at all. It would supply
false evidence for exactly the promotion that must not be made on faith.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from genesis.errors import DegradedError
from genesis.marketdata.normalize import Bar
from genesis.marketdata.reconcile import reconcile

ES = "FUT:CME:ES:2025-12"
T0 = datetime(2026, 9, 3, 13, 0, tzinfo=UTC)


def bars(closes, *, source="a", start=T0, step=timedelta(hours=1)):
    return [
        Bar(
            symbol_id=ES,
            timeframe="1H",
            ts=start + step * i,
            open=Decimal(str(c)),
            high=Decimal(str(c)) + Decimal("2"),
            low=Decimal(str(c)) - Decimal("2"),
            close=Decimal(str(c)),
            volume=Decimal("1000"),
            source=source,
            tier=3,
        )
        for i, c in enumerate(closes)
    ]


def test_identical_feeds_measure_zero():
    result = reconcile(bars([1, 2, 3]), bars([1, 2, 3]), source_a="ibkr", source_b="db")
    assert result.aligned == 3
    assert result.worst_abs == 0
    assert result.within(Decimal("0.25"))


def test_the_measured_difference_is_the_worst_case_not_the_average():
    """A tolerance is a promise about the worst bar, not the typical one.
    Averaging would hide the single bar that sizes a position wrongly."""
    result = reconcile(bars([100, 100, 100]), bars([100, 100, 105]))
    assert result.worst_abs == Decimal("5")
    assert result.fields["close"].mean_abs < result.fields["close"].max_abs
    assert result.fields["close"].worst_at == T0 + timedelta(hours=2)


def test_a_difference_outside_tolerance_fails():
    result = reconcile(bars([100, 100, 100]), bars([100, 100, 101]))
    assert not result.within(Decimal("0.25"))
    assert result.within(Decimal("1.00"))


def test_unaligned_bars_fail_even_when_the_prices_agree():
    """The two feeds disagreeing about which bars EXIST is a real finding --
    usually a session boundary convention. Silently intersecting would turn it
    into a clean-looking pass over whatever happened to overlap."""
    a = bars([100, 100, 100])
    b = bars([100, 100, 100])[:2]

    result = reconcile(a, b)
    assert result.worst_abs == 0          # the prices match perfectly
    assert not result.within(Decimal("1"))  # and it still does not pass
    assert result.only_a and not result.only_b


def test_a_reconciliation_with_no_overlap_is_absent_not_lenient():
    """Zero aligned bars must never read as 'no differences found'."""
    a = bars([100, 100])
    b = bars([100, 100], start=T0 + timedelta(days=5))
    result = reconcile(a, b)
    assert result.aligned == 0
    assert not result.within(Decimal("1000"))


def test_an_empty_source_refuses_rather_than_scoring():
    with pytest.raises(DegradedError, match="Both sources"):
        reconcile(bars([1, 2]), [])


def test_relative_difference_is_comparable_across_instruments():
    """0.25 on ES and 0.25 on a $10 contract mean different things."""
    result = reconcile(bars([100]), bars([101]))
    assert result.fields["close"].max_rel == pytest.approx(Decimal("1") / Decimal("101"))


def test_the_report_names_both_sources_and_the_worst_number():
    result = reconcile(
        bars([100, 100]), bars([100, 100.5]), source_a="ibkr", source_b="databento"
    )
    text = result.report()
    assert "ibkr" in text and "databento" in text
    assert "0.5" in text
    assert "aligned bars: 2" in text


def test_the_report_surfaces_unaligned_bars_prominently():
    result = reconcile(bars([1, 2, 3]), bars([1, 2]))
    assert "UNALIGNED" in result.report()


def test_every_ohlcv_field_is_measured_not_just_close():
    """A feed that agrees on closes and disagrees on highs is not a feed you
    can compute a stop against."""
    a = bars([100])
    b = bars([100])
    b[0] = Bar(**{**b[0].__dict__, "high": Decimal("999")})
    result = reconcile(a, b)
    assert result.fields["high"].max_abs > 0
    assert result.fields["close"].max_abs == 0
    assert set(result.fields) == {"open", "high", "low", "close", "volume"}
