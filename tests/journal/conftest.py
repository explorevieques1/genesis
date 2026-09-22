# Spec: Genesis Markdown/20-Agents/Journal/Journal Family.md
"""Fixtures with *planted* patterns.

Agent — Insight Miner's acceptance criterion is *"on a seeded dataset with a
known planted pattern, the pattern is found"*, and that only means something if
the pattern is genuinely there by construction rather than by seed. So the
histories below are built to contain a specific, stated behaviour, and the tests
assert that behaviour is the one that comes back.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from genesis.journal.schema import JournalEntry, Observation, PlanAdherence
from genesis.journal.store import JournalStore

BASE = datetime(2026, 3, 2, 14, 31, tzinfo=UTC)


@pytest.fixture
def make_frame():
    """The charting fixtures' frame builder, reused.

    Imported rather than duplicated: the bridge tests assert that charting
    outcomes land in the journal, and two definitions of "a test chart" would
    eventually disagree about what was being scored.
    """
    from tests.charting.conftest import _frame

    return _frame


@pytest.fixture
def store(tmp_path) -> JournalStore:
    made = JournalStore(tmp_path / "journal.db")
    yield made
    made.close()


def entry(
    *,
    index: int = 0,
    r: float | None = 1.0,
    qty: int = 100,
    setup: str = "orb",
    session: str = "midday",
    regime: str = "trending",
    stop_moved: bool = False,
    mfe_r: float | None = None,
    strategy: str | None = None,
    at: datetime | None = None,
    **extra,
) -> JournalEntry:
    opened = at or (BASE + timedelta(days=index))
    return JournalEntry(
        symbol=extra.pop("symbol", "NVDA"),
        direction="long",
        entry_price=100.0,
        entry_ts=opened,
        exit_price=101.0,
        exit_ts=opened + timedelta(hours=1),
        qty=qty,
        r_multiple=r,
        mfe_r=mfe_r if mfe_r is not None else (abs(r) + 0.4 if r is not None else None),
        setup=setup,
        session_segment=session,
        regime=regime,
        day_of_week=opened.strftime("%A").lower(),
        duration_min=60.0,
        strategy=strategy,
        plan_adherence=PlanAdherence(stop_moved=stop_moved),
        **extra,
    )


@pytest.fixture
def planted(store) -> JournalStore:
    """A history containing one deliberate behaviour: oversizing after losses.

    After two consecutive losses the next trade is double size and averages
    clearly negative; everything else averages clearly positive. Nothing else in
    the data is arranged, so a detector that reports something else has found
    noise.
    """
    rng = random.Random(4)
    consecutive = 0
    for i in range(60):
        oversized = consecutive >= 2
        r = rng.gauss(-0.6, 0.5) if oversized else rng.gauss(0.35, 0.9)
        store.put_entry(
            entry(index=i, r=round(r, 2), qty=200 if oversized else 100)
        )
        consecutive = consecutive + 1 if r <= 0 else 0
    return store


@pytest.fixture
def level_outcomes(store) -> JournalStore:
    """Anchored VWAP holds 70%; trendlines hold 40%. Planted, and checkable."""
    for i in range(20):
        store.record(
            Observation(
                kind="level.outcome",
                subject=f"level:NVDA:{100 + i}",
                outcome="held" if i % 10 < 7 else "broke",
                source="anchored-vwap",
            )
        )
    for i in range(20):
        store.record(
            Observation(
                kind="level.outcome",
                subject=f"level:AMD:{200 + i}",
                outcome="held" if i % 10 < 4 else "broke",
                source="trendline",
            )
        )
    return store
