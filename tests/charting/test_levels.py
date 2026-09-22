# Spec: Genesis Markdown/10-Architecture/Charting Engine.md
"""Level computation, and the four editorial rules that make it useful."""

from __future__ import annotations

import numpy as np

from genesis.charting import indicators as ind
from genesis.charting.levels import (
    CONFLUENCE_ATR,
    LevelCandidate,
    compute_levels,
    merge_confluence,
)


def test_prior_period_levels_are_always_present(trending) -> None:
    """*"Always include prior-period high and low."* Cheap and always relevant."""
    computation = compute_levels(trending)
    labels = {level.label for level in computation.levels}
    assert {"PDH", "PDL"} <= labels


def test_prior_period_levels_survive_the_cut(trending) -> None:
    kept = {level.label for level in computation_strongest(trending)}
    assert "PDH" in kept and "PDL" in kept


def computation_strongest(bars, n: int = 8):
    return compute_levels(bars).strongest(n)


def test_the_cut_respects_the_cap(trending) -> None:
    assert len(compute_levels(trending).strongest(8)) <= 8


def test_levels_within_a_quarter_atr_merge(trending) -> None:
    """Markup Spec Schema's confluence rule, at its stated threshold."""
    atr = ind.last_atr(trending)
    near = [
        LevelCandidate(price=120.0, label="A", type="resistance", source="t",
                       why="a", touches=2, strength=0.5),
        LevelCandidate(price=120.0 + atr * 0.1, label="B", type="resistance",
                       source="t", why="b", touches=2, strength=0.4),
    ]
    merged = merge_confluence(near, atr)
    assert len(merged) == 1
    assert set(merged[0].confluence) == {"A", "B"}


def test_levels_further_than_the_threshold_do_not_merge(trending) -> None:
    atr = ind.last_atr(trending)
    apart = [
        LevelCandidate(price=120.0, label="A", type="resistance", source="t",
                       why="a", strength=0.5),
        LevelCandidate(price=120.0 + atr * (CONFLUENCE_ATR + 0.2), label="B",
                       type="resistance", source="t", why="b", strength=0.4),
    ]
    assert len(merge_confluence(apart, atr)) == 2


def test_merging_boosts_strength_but_never_reaches_certainty(trending) -> None:
    atr = ind.last_atr(trending)
    group = [
        LevelCandidate(price=120.0, label=f"L{i}", type="resistance", source="t",
                       why="x", strength=0.6)
        for i in range(3)
    ]
    merged = merge_confluence(group, atr)[0]
    assert merged.strength > 0.6
    assert merged.strength < 1.0


def test_support_merged_with_resistance_becomes_a_pivot(trending) -> None:
    """A price that has acted as both is a flip level, and saying so is the point."""
    atr = ind.last_atr(trending)
    pair = [
        LevelCandidate(price=120.0, label="S 120.00", type="support", source="sr-cluster",
                       why="a", strength=0.5),
        LevelCandidate(price=120.05, label="R 120.05", type="resistance",
                       source="sr-cluster", why="b", strength=0.4),
    ]
    merged = merge_confluence(pair, atr)[0]
    assert merged.type == "pivot"
    assert merged.label.startswith("P ")


def test_a_merged_cluster_label_matches_its_own_price(trending) -> None:
    """The chip must not read 113.91 against a line drawn at 113.70."""
    atr = ind.last_atr(trending)
    pair = [
        LevelCandidate(price=120.0, label="R 120.00", type="resistance",
                       source="sr-cluster", why="a", strength=0.5),
        LevelCandidate(price=120.1, label="R 120.10", type="resistance",
                       source="sr-cluster", why="b", strength=0.4),
    ]
    merged = merge_confluence(pair, atr)[0]
    assert f"{merged.price:.2f}" in merged.label


def test_distance_is_measured_in_atr(trending) -> None:
    computation = compute_levels(trending)
    for level in computation.levels:
        expected = (level.price - computation.spot) / computation.atr
        assert abs(level.distance_atr - expected) < 0.02


def test_a_single_untouched_pivot_is_not_a_level(ranging) -> None:
    """Two touches is the minimum that makes the word mean anything."""
    clusters = [
        level for level in compute_levels(ranging).levels
        if level.source == "sr-cluster"
    ]
    assert all(level.touches >= 2 for level in clusters)


def test_session_vwap_only_appears_intraday(trending, intraday) -> None:
    daily = {level.label for level in compute_levels(trending).levels}
    fast = {level.label for level in compute_levels(intraday).levels}
    assert "VWAP" not in daily
    assert "VWAP" in fast


def test_an_opening_range_is_not_computed_on_a_daily_chart(trending) -> None:
    assert not any(zone.subtype == "orb" for zone in compute_levels(trending).zones)


def test_no_volume_degrades_honestly_rather_than_guessing(make_frame) -> None:
    """A feed with no volume must not silently produce a volume profile."""
    close = np.linspace(100, 140, 200)
    frame = make_frame(close, volume=np.zeros(200))
    computation = compute_levels(frame)
    assert computation.degraded
    assert any("volume" in note for note in computation.notes)
    assert not any(level.label == "POC" for level in computation.levels)


def test_every_price_is_in_the_provenance_ledger(trending) -> None:
    """The input to the hallucination check must be complete."""
    computation = compute_levels(trending)
    sourced = computation.prices()
    for level in computation.levels:
        assert any(abs(level.price - p) < 1e-9 for p in sourced)
    for zone in computation.zones:
        assert any(abs(zone.low - p) < 1e-9 for p in sourced)


def test_a_trendline_needs_three_touches(trending) -> None:
    """Two points define every pair of points; three is a line."""
    for line in compute_levels(trending).lines:
        assert line.touches >= 3


def test_a_zero_atr_window_falls_back_rather_than_dividing_by_zero(make_frame) -> None:
    flat = make_frame(np.full(60, 100.0), wick=0.0)
    computation = compute_levels(flat)
    assert computation.atr > 0
    assert computation.degraded
