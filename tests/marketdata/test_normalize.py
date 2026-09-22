# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""Symbol identity and the bar schema — the two things that cannot be retrofitted."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from genesis.marketdata.normalize import (
    Bar,
    NormalizeError,
    continuous_id,
    instrument_id,
    normalise_bars,
    parse_instrument_id,
    to_decimal,
    utc,
)


# -- symbol identity -------------------------------------------------------


def test_a_futures_id_requires_a_contract_month():
    """Open Questions §13: 'ES' is a family. Never guess the front month --
    an id built from 'today's front month' names a different contract
    tomorrow."""
    with pytest.raises(NormalizeError, match="family"):
        instrument_id("FUT", "CME", "ES")


def test_the_four_things_called_ES_are_four_different_ids():
    dated_z5 = instrument_id("FUT", "CME", "ES", contract_month="2025-12")
    dated_z6 = instrument_id("FUT", "CME", "ES", contract_month="2026-12")
    continuous = continuous_id("CME", "ES", "volume", "back")
    ratio = continuous_id("CME", "ES", "volume", "ratio")

    assert len({dated_z5, dated_z6, continuous, ratio}) == 4


def test_continuous_ids_cannot_be_built_through_the_normal_path():
    with pytest.raises(NormalizeError, match="§13"):
        instrument_id("CONT", "CME", "ES")


def test_month_code_round_trip():
    inst = parse_instrument_id("FUT:CME:ES:2025-12")
    assert inst.month_code == "Z5"
    assert inst.is_future
    assert inst.root == "ES"


def test_a_malformed_month_is_refused():
    with pytest.raises(NormalizeError, match="YYYY-MM"):
        instrument_id("FUT", "CME", "ES", contract_month="Dec25")


def test_a_continuous_id_parses_but_is_flagged():
    inst = parse_instrument_id("CONT:CME:ES:volume:back")
    assert inst.is_continuous


# -- the bar ---------------------------------------------------------------


def test_a_naive_timestamp_is_refused():
    """A bar without a timezone is a bar in an unknown session."""
    with pytest.raises(NormalizeError, match="naive"):
        Bar(
            "EQ:XNAS:AAPL", "1D", datetime(2026, 3, 2),
            *([Decimal("1")] * 5),
        )


def test_high_below_low_is_a_parse_failure():
    with pytest.raises(NormalizeError, match="below low"):
        Bar(
            "EQ:XNAS:AAPL", "1D", datetime(2026, 3, 2, tzinfo=UTC),
            Decimal("10"), Decimal("5"), Decimal("9"), Decimal("7"), Decimal("1"),
        )


def test_a_settlement_close_outside_the_range_is_allowed():
    """Deliberate: some vendors legitimately report this. Rejecting it would
    discard real data to satisfy a tidiness rule."""
    Bar(
        "FUT:CME:ES:2025-12", "1D", datetime(2026, 3, 2, tzinfo=UTC),
        Decimal("10"), Decimal("12"), Decimal("9"), Decimal("12.25"), Decimal("1"),
    )


def test_a_missing_price_is_never_a_zero():
    with pytest.raises(NormalizeError, match="refusing to invent"):
        to_decimal(None, field="close")


def test_nan_is_refused():
    with pytest.raises(NormalizeError, match="NaN"):
        to_decimal(float("nan"), field="close")


def test_decimals_do_not_pass_through_float():
    """A CME quarter point, exactly. Decimal(4512.25) from a float would carry
    binary representation error into the store permanently."""
    assert to_decimal(4512.25) == Decimal("4512.25")
    assert to_decimal("0.1") + to_decimal("0.2") == to_decimal("0.3")


# -- timestamps ------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        1772668800,                      # seconds
        1772668800_000,                  # milliseconds
        1772668800_000_000_000,          # nanoseconds
        "2026-03-05T00:00:00Z",
        "2026-03-05T00:00:00+00:00",
        datetime(2026, 3, 5, tzinfo=UTC),
    ],
)
def test_every_vendor_timestamp_spelling_lands_on_the_same_instant(value):
    assert utc(value) == datetime(2026, 3, 5, tzinfo=UTC)


def test_bars_are_sorted_and_deduplicated():
    rows = [
        {"ts": "2026-03-03T00:00:00Z", "open": 2, "high": 3, "low": 1, "close": 2},
        {"ts": "2026-03-02T00:00:00Z", "open": 1, "high": 2, "low": 0.5, "close": 1},
        {"ts": "2026-03-03T00:00:00Z", "open": 2, "high": 4, "low": 1, "close": 3},
    ]
    bars = normalise_bars(
        rows, symbol_id="EQ:XNAS:AAPL", timeframe="1D", source="v", tier=3
    )
    assert [b.ts.day for b in bars] == [2, 3]
    # Last duplicate wins within one payload -- vendors legitimately resend.
    assert bars[-1].close == Decimal("3")


def test_provenance_is_stamped_on_every_bar():
    bars = normalise_bars(
        [{"ts": "2026-03-02T00:00:00Z", "open": 1, "high": 2, "low": 1, "close": 1}],
        symbol_id="EQ:XNAS:AAPL", timeframe="1D", source="databento", tier=2,
    )
    (b,) = bars
    assert (b.source, b.tier) == ("databento", 2)
    assert b.as_of is not None and b.ingested_at is not None
