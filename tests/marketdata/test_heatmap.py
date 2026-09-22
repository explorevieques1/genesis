# Spec: Genesis Markdown/60-UI/Widget Catalog.md §Built — HM Heatmap
"""The `HM` heatmap's row builder, which is where it can lie.

Area is market cap and colour is the day's change, so a tile missing either is
false in whichever channel it is missing -- and a zero-change grey tile for a
name the feed could not price is exactly the confident wrong answer
[[Safety Invariants]] §10 is about. The one rule worth pinning is therefore
*"no number, no tile"*, from every direction a number can be absent.

No network here. ``_row`` takes a quote dict, which is the whole reason it is a
function rather than an inline expression in the loop.
"""

from __future__ import annotations

from genesis.marketdata import heatmap


def _quote(cap=1e12, close=110.0, prev=100.0):
    return {
        "marketCap": cap,
        "regularMarketPrice": close,
        "regularMarketPreviousClose": prev,
        "shortName": "NVIDIA Corporation",
    }


def test_row_carries_area_colour_and_sector():
    row = heatmap._row("NVDA", _quote())
    assert row["market_cap"] == 1e12
    assert row["change_pct"] == 10.0
    assert row["sector"] == heatmap.NASDAQ_100["NVDA"]
    assert row["name"] == "NVIDIA Corporation"


def test_a_fall_is_negative():
    assert heatmap._row("NVDA", _quote(close=95.0, prev=100.0))["change_pct"] == -5.0


def test_no_number_no_tile():
    """Every way a quote can be unpriceable drops the row rather than zeroing it."""
    for hole in ({"marketCap": None}, {"marketCap": 0},
                 {"regularMarketPrice": None},
                 {"regularMarketPreviousClose": None},
                 # A zero previous close would be a division by zero, and a
                 # tile whose change is undefined has no colour.
                 {"regularMarketPreviousClose": 0}):
        assert heatmap._row("NVDA", {**_quote(), **hole}) is None, hole


def test_an_unchanged_name_still_gets_a_tile():
    """Zero change is a fact, not a hole -- it must not be dropped as falsy."""
    assert heatmap._row("NVDA", _quote(close=100.0, prev=100.0))["change_pct"] == 0.0


def test_every_member_has_a_sector():
    """The tree groups by sector, so a blank one would be an unnamed block."""
    assert all(sector.strip() for sector in heatmap.NASDAQ_100.values())
    assert 90 <= len(heatmap.NASDAQ_100) <= 105, "the index is ~100 names"
