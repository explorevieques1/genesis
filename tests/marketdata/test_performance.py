# Spec: Genesis Markdown/60-UI/Widget Catalog.md §Built — PFM Performance
"""Window returns for the `PFM` board.

The board's whole claim is *"this is what 1D/1W/1M/3M did"*, so the failure that
matters is a window computed off the wrong bar -- a 1W that is really four
sessions, or a 3M silently filled from a contract that has only traded a month.
Both look completely plausible on screen, which is why they are pinned here.

``_returns`` takes a pandas Series, so none of this touches the network.
"""

from __future__ import annotations

import pandas as pd
import pytest

from genesis.marketdata import performance as perf


def series(values):
    return pd.Series(values, dtype="float64")


def test_each_window_counts_back_that_many_sessions():
    # 100, 101, ... one point per session. A window of N sessions back is
    # therefore exactly N points of gain.
    closes = series([100.0 + i for i in range(70)])
    out = perf._returns(closes)
    last = 169.0
    for label, back in perf.WINDOWS.items():
        prior = 169.0 - back
        assert out[label] == pytest.approx(round((last - prior) / prior * 100, 2)), label


def test_a_window_longer_than_the_history_is_null_not_borrowed():
    """A contract with a month of bars has a 1M and no 3M -- and must say so."""
    out = perf._returns(series([100.0 + i for i in range(30)]))
    assert out["1D"] is not None
    assert out["1W"] is not None
    assert out["1M"] is not None
    assert out["3M"] is None, "a 3M off 30 bars would be a fabricated window"


def test_one_close_is_no_row():
    """Nothing to compare against is a missing row, never a 0.00%."""
    assert perf._returns(series([100.0])) is None
    assert perf._returns(series([])) is None


def test_gaps_are_closed_before_counting():
    """A halted session is a NaN; counting it as a session shifts every window."""
    dense = series([100.0 + i for i in range(70)])
    holed = series([100.0 + i for i in range(70)])
    holed.iloc[[3, 17, 44]] = float("nan")
    # 70 slots, 67 real closes. Every window must count back through the real
    # ones: a NaN counted as a session would shift 3M by three days and land on
    # a bar that is not there.
    real = holed.dropna().tolist()
    out = perf._returns(holed)
    for label, back in perf.WINDOWS.items():
        expected = round((real[-1] - real[-1 - back]) / real[-1 - back] * 100, 2)
        assert out[label] == pytest.approx(expected), label
    # And the shift is observable: the gapped series is three sessions shorter,
    # so its 3M is not the ungapped one.
    assert out["3M"] != perf._returns(dense)["3M"]


def test_a_fall_is_negative():
    assert perf._returns(series([100.0, 95.0]))["1D"] == -5.0


def test_the_futures_table_is_well_formed():
    """Every entry is (name, group, kind) and every group is on the board."""
    for symbol, entry in perf.FUTURES.items():
        name, group, kind = entry
        assert name and group and kind, symbol
        assert group in perf.FUTURES_GROUPS, f"{symbol} is in no board group"
        assert kind in ("future", "index"), symbol
    # A cash index does not settle, and the panel says different things about
    # the two -- so the distinction must actually be drawn somewhere.
    assert {e[2] for e in perf.FUTURES.values()} == {"future", "index"}
