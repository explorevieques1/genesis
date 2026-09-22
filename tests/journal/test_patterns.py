# Spec: Genesis Markdown/20-Agents/Journal/Agent — Insight Miner.md
"""The detectors: quantified, comparative, and allowed to find nothing."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from genesis.journal.patterns import (
    DETECTORS,
    cutting_winners,
    detect_all,
    level_quality,
    revenge_trading,
    selection_bias,
    sequence_effect,
    size_effect,
    stop_migration,
)
from genesis.journal.schema import JournalEntry, Observation
from tests.journal.conftest import BASE, entry


def _flat(n: int = 40, r: float = 0.2) -> list[JournalEntry]:
    """A history with nothing in it. The control.

    ``mfe_r`` is set just above the result rather than left to the helper's
    default. The default (``|r| + 0.4``) makes every small winner look like it
    captured a third of its move, which is a real cutting-winners signal — in
    the fixture, not in the data. A control that quietly contains a pattern
    tests nothing.
    """
    rng = random.Random(11)
    out = []
    for i in range(n):
        value = round(r + rng.gauss(0, 0.4), 2)
        out.append(entry(index=i, r=value, mfe_r=abs(value) + 0.05))
    return out


def test_a_featureless_history_produces_no_findings() -> None:
    """Most histories contain no behavioural pattern, and saying so is correct."""
    assert detect_all(_flat()) == []


def test_the_planted_sequence_effect_is_found() -> None:
    rng = random.Random(4)
    entries: list[JournalEntry] = []
    consecutive = 0
    for i in range(60):
        oversized = consecutive >= 2
        r = rng.gauss(-0.6, 0.5) if oversized else rng.gauss(0.35, 0.9)
        entries.append(entry(index=i, r=round(r, 2), qty=200 if oversized else 100))
        consecutive = consecutive + 1 if r <= 0 else 0

    found = sequence_effect(entries)
    assert found is not None
    assert found.key == "sequence.after-two-losses"
    assert "consecutive losses" in found.finding
    # Comparative, never absolute: the baseline is in the sentence.
    assert "against" in found.finding


def test_stop_migration_needs_three_occurrences() -> None:
    two = [entry(index=i, r=-1.0, stop_moved=i < 2) for i in range(20)]
    assert stop_migration(two) is None
    three = [entry(index=i, r=-1.0, stop_moved=i < 3) for i in range(20)]
    assert stop_migration(three) is not None


def test_cutting_winners_measures_against_the_move_not_the_target() -> None:
    """A target never approached says nothing about your exits."""
    disciplined = [entry(index=i, r=1.0, mfe_r=1.1) for i in range(20)]
    assert cutting_winners(disciplined) is None
    early = [entry(index=i, r=1.0, mfe_r=3.0) for i in range(20)]
    found = early and cutting_winners(early)
    assert found is not None
    assert "capture" in found.finding


def test_revenge_trading_only_fires_when_it_is_worse() -> None:
    now = BASE
    quick_and_fine = []
    for i in range(30):
        opened = now + timedelta(days=i)
        quick_and_fine.append(entry(index=i, r=-1.0 if i % 2 else 1.0, at=opened))
    assert revenge_trading(quick_and_fine) is None


def test_size_effect_is_comparative() -> None:
    rng = random.Random(3)
    mixed = [
        entry(index=i, r=round(rng.gauss(-0.8, 0.4), 2), qty=400)
        if i % 3 == 0
        else entry(index=i, r=round(rng.gauss(0.4, 0.4), 2), qty=100)
        for i in range(40)
    ]
    found = size_effect(mixed)
    assert found is not None
    assert "1.5x average size" in found.finding


def test_level_quality_needs_two_level_types_that_differ() -> None:
    same = [
        Observation(kind="level.outcome", subject=f"l{i}", outcome="held", source="a")
        for i in range(10)
    ] + [
        Observation(kind="level.outcome", subject=f"m{i}", outcome="held", source="b")
        for i in range(10)
    ]
    assert level_quality([], observations=same) is None

    differing = [
        Observation(
            kind="level.outcome", subject=f"l{i}",
            outcome="held" if i < 7 else "broke", source="anchored-vwap",
        )
        for i in range(10)
    ] + [
        Observation(
            kind="level.outcome", subject=f"m{i}",
            outcome="held" if i < 3 else "broke", source="trendline",
        )
        for i in range(10)
    ]
    found = level_quality([], observations=differing)
    assert found is not None
    assert "anchored-vwap" in found.finding


def test_selection_bias_needs_the_skipped_ideas() -> None:
    """A skipped idea leaves no trade — the journal alone can never see it."""
    observations = [
        Observation(kind="idea.outcome", subject=f"i{i}", outcome="taken", value=0.1)
        for i in range(10)
    ] + [
        Observation(kind="idea.outcome", subject=f"j{i}", outcome="skipped", value=0.9)
        for i in range(10)
    ]
    found = selection_bias([], observations=observations)
    assert found is not None
    assert "skipped" in found.finding


def test_every_finding_carries_evidence_and_a_stable_key() -> None:
    rng = random.Random(4)
    entries: list[JournalEntry] = []
    consecutive = 0
    for i in range(60):
        oversized = consecutive >= 2
        r = rng.gauss(-0.6, 0.5) if oversized else rng.gauss(0.35, 0.9)
        entries.append(entry(index=i, r=round(r, 2), qty=200 if oversized else 100))
        consecutive = consecutive + 1 if r <= 0 else 0

    first = {f.key for f in detect_all(entries)}
    second = {f.key for f in detect_all(entries)}
    assert first == second and first
    for finding in detect_all(entries):
        assert finding.evidence.observations > 0
        assert 0.0 <= finding.evidence.confidence <= 0.9


def test_a_broken_detector_does_not_end_the_pass() -> None:
    def explodes(entries, **kwargs):
        raise RuntimeError("boom")

    entries = [entry(index=i, r=-1.0, stop_moved=i < 5) for i in range(20)]
    found = detect_all(entries, detectors=(explodes, stop_migration))
    assert len(found) == 1


def test_confidence_never_reaches_certainty() -> None:
    """Mining a small dataset many ways; some of what is found is coincidence."""
    entries = [entry(index=i, r=-1.0, stop_moved=True) for i in range(500)]
    for finding in detect_all(entries):
        assert finding.evidence.confidence <= 0.9
