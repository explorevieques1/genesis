# Spec: Genesis Markdown/20-Agents/Journal/Agent — Performance Analyst.md
"""The sample-size discipline, and the arithmetic underneath it."""

from __future__ import annotations

import pytest

from genesis.metrics import (
    CONCLUSIVE_N,
    RECOMMEND_N,
    calibration,
    drawdown_r,
    equity_curve_r,
    slice_by,
    streaks,
    summarize,
)


class Row:
    def __init__(self, r=None, setup=None, confidence=None, pnl=0.0):
        self.r_multiple = r
        self.setup = setup
        self.confidence = confidence
        self.pnl_net = pnl


def test_an_empty_sample_reports_none_not_zero() -> None:
    """A zero expectancy and no data must never read the same."""
    empty = summarize([])
    assert empty.n == 0
    assert empty.expectancy_r is None
    assert empty.qualifier() == "no trades"


def test_ungraded_trades_are_dropped_not_counted_as_breakeven() -> None:
    """A trade whose R could not be computed is not a breakeven trade."""
    assert summarize([1.0, None, -1.0]).n == 2


def test_no_losers_means_no_profit_factor() -> None:
    """'inf' in a report reads as a result rather than as an absence."""
    assert summarize([1.0, 2.0]).profit_factor is None


def test_the_two_thresholds_are_distinct() -> None:
    """Describing a slice is cheaper than telling someone to change how they trade."""
    sample = summarize([0.5] * (CONCLUSIVE_N + 1))
    assert sample.conclusive is True
    assert sample.actionable is False
    bigger = summarize([0.5] * (RECOMMEND_N + 1))
    assert bigger.actionable is True


def test_the_qualifier_labels_a_thin_sample() -> None:
    assert "indicative" in summarize([1.0] * 5).qualifier()


def test_expectancy_and_win_rate() -> None:
    sample = summarize([2.0, -1.0, -1.0, 2.0])
    assert sample.expectancy_r == pytest.approx(0.5)
    assert sample.win_rate == pytest.approx(0.5)
    assert sample.avg_win_r == pytest.approx(2.0)
    assert sample.avg_loss_r == pytest.approx(-1.0)


def test_drawdown_is_measured_on_the_r_curve() -> None:
    assert drawdown_r([1.0, -1.0, -1.0, -1.0, 2.0]) == pytest.approx(3.0)
    assert drawdown_r([1.0, 1.0]) == 0.0


def test_the_equity_curve_starts_at_zero() -> None:
    assert equity_curve_r([1.0, -0.5]) == [0.0, 1.0, 0.5]


def test_streaks() -> None:
    found = streaks([True, False, False, True, True, True])
    assert found["longest_loss"] == 2
    assert found["longest_win"] == 3
    assert found["current_is_win"] is True


def test_a_slice_sentence_carries_its_n() -> None:
    """'Always state the sample size in the same breath as the finding.'"""
    found = slice_by([Row(1.0, "orb"), Row(0.5, "orb")], "setup", lambda r: r.setup)
    assert "over 2 trades" in found[0].sentence()


def test_rows_with_no_dimension_value_are_dropped() -> None:
    """A trade with no recorded setup is not evidence about a setup called None."""
    found = slice_by([Row(1.0, None), Row(1.0, "orb")], "setup", lambda r: r.setup)
    assert [s.value for s in found] == ["orb"]


def test_slices_come_back_best_first() -> None:
    found = slice_by(
        [Row(-1.0, "bad"), Row(2.0, "good")], "setup", lambda r: r.setup
    )
    assert [s.value for s in found] == ["good", "bad"]


def test_calibration_needs_a_sample_before_it_judges() -> None:
    rows = [Row(1.0, confidence=0.75), Row(-0.5, confidence=0.45)]
    assert "too few" in calibration(rows, confidence_of=lambda r: r.confidence)["verdict"]


def test_calibration_detects_an_inversion() -> None:
    """If high-confidence ideas do not outperform, the scoring is broken."""
    rows = (
        [Row(-1.0, confidence=0.75) for _ in range(15)]
        + [Row(1.0, confidence=0.45) for _ in range(15)]
    )
    result = calibration(rows, confidence_of=lambda r: r.confidence)
    assert result["monotonic"] is False
    assert "not calibrated" in result["verdict"]


def test_calibration_confirms_a_working_scorer() -> None:
    rows = (
        [Row(-0.5, confidence=0.45) for _ in range(15)]
        + [Row(1.2, confidence=0.75) for _ in range(15)]
    )
    result = calibration(rows, confidence_of=lambda r: r.confidence)
    assert result["monotonic"] is True
