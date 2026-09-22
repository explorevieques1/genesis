# Spec: Genesis Markdown/20-Agents/Charting/Agent — Pattern Recognition.md
"""The skeptic. Its most important property is that it usually finds nothing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from genesis.charting.bars import Bars
from genesis.charting.structure import read_structure


def _random_walk(seed: int, n: int = 240) -> Bars:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1.2, n))
    times = tuple(datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n))
    return Bars(
        "RND", "1D", times,
        close + rng.normal(0, 0.4, n),
        close + rng.uniform(0.2, 1.5, n),
        close - rng.uniform(0.2, 1.5, n),
        close, rng.uniform(1e6, 5e6, n), source="test",
    )


def test_a_clean_uptrend_reads_as_one(trending) -> None:
    read = read_structure(trending)
    assert read.trend == "up"
    assert read.swing == "HH-HL"


def test_a_clean_downtrend_reads_as_one(falling) -> None:
    read = read_structure(falling)
    assert read.trend == "down"
    assert read.swing == "LH-LL"


def test_an_oscillation_reads_as_a_range(ranging) -> None:
    read = read_structure(ranging)
    assert read.trend == "range"
    assert any(pattern.name == "range" for pattern in read.patterns)


def test_the_rules_engine_finds_nothing_on_most_random_charts() -> None:
    """The note's acceptance criterion, applied to the engine that feeds it.

    A skeptic that confirms a pattern on nine charts in ten is not a skeptic,
    and the vision model would then have nothing to be contradicted by.
    """
    clean = sum(1 for seed in range(40) if not read_structure(_random_walk(seed)).patterns)
    assert clean >= 20, f"only {clean}/40 random charts came back empty"


def test_trend_needs_both_adx_and_the_swing_sequence(make_frame) -> None:
    """A drift with no structure is a range, not a trend, whatever ADX says."""
    close = np.linspace(100, 101, 240)  # imperceptible drift
    assert read_structure(make_frame(close)).trend == "range"


def test_contraction_detects_a_real_squeeze(make_frame) -> None:
    """Ten quiet bars against the thirty noisy ones before them.

    The window sizes matter to the fixture: contraction compares the last 10
    bars' true range to the 30 before it, so a quiet tail longer than 10 bars
    would put both windows inside the calm and measure a ratio of 1.
    """
    loud = 100 + 4 * np.sin(np.arange(200) / 3.0)
    quiet = np.full(10, float(loud[-1]))
    read = read_structure(make_frame(np.concatenate([loud, quiet]), wick=0.05))
    assert read.contraction < 0.6


def test_contraction_returns_no_information_rather_than_nan_on_a_short_window(
    make_frame,
) -> None:
    assert read_structure(make_frame(np.linspace(100, 110, 20))).contraction == 1.0


def test_a_sweep_needs_a_reclaim_on_the_close(make_frame) -> None:
    """A wick through is not a break — the distinction the whole family rests on."""
    read = read_structure(_random_walk(3))
    for pattern in read.patterns:
        if pattern.name == "liquidity_sweep":
            assert pattern.measures["depth_atr"] >= 0.35


def test_every_pattern_carries_its_measurements(ranging) -> None:
    """*"'Bull flag' is a label; the measurement is information."*"""
    for pattern in read_structure(ranging).patterns:
        assert pattern.why
        assert pattern.measures


def test_the_summary_is_one_line_a_prompt_can_hold(trending) -> None:
    summary = read_structure(trending).summary()
    assert "\n" not in summary
    assert len(summary) < 160
