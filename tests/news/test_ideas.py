# Spec: Genesis Markdown/20-Agents/Research/Agent — News And Catalyst.md · 70-Schemas/Idea Schema.md
"""A brief's trade ideas, promoted — and the ones that must not be.

The rule this module exists to hold is Idea Schema's: *no invalidation, no
idea*. It is applied to a model's output exactly as it is applied to the
trader's own words, which is the only way it means anything — a rule enforced
on the person and waived for the machine is not a rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genesis.news.ideas import NEWS_AUTHOR, promote_brief
from genesis.research.store import ResearchStore


@pytest.fixture()
def store(tmp_path: Path):
    s = ResearchStore(path=tmp_path / "research.db", vault=None)
    yield s
    s.close()


def brief(*ideas: dict) -> dict:
    return {"id": "brf_1", "title": "Weekend news review — 2026-09-20",
            "body": {"confidence": 0.5, "trade_ideas": list(ideas)}}


IDEA = {"idea": "Long energy on exhausted buffers", "symbols": ["CVX", "CL=F"],
        "bias": "long", "rationale": "Buffers are depleted.",
        "invalidation": "A lasting geopolitical resolution."}


def test_a_directional_idea_becomes_a_real_idea(store) -> None:  # noqa: ANN001
    out = promote_brief(store, brief(IDEA))
    assert len(out.ideas) == 1 and not out.dropped

    from genesis.agents.research.session_plan import live_ideas

    (note_id, idea), = live_ideas(store)
    assert idea.symbol == "CVX", "the first named symbol, upper-cased — never a model's guess"
    assert idea.direction == "long"
    assert idea.author == NEWS_AUTHOR, "the author is how the weekly review slices by source"
    assert idea.invalidation == IDEA["invalidation"], "the brief's own words, not a paraphrase"
    assert "not assessed" in idea.conflicts, (
        "a brief argues one side; claiming a counter-argument was weighed would be a lie"
    )
    assert note_id


def test_an_idea_with_no_invalidation_is_dropped_not_patched(store) -> None:  # noqa: ANN001
    """No invalidation, no idea — including when a model wrote it."""
    out = promote_brief(store, brief({**IDEA, "invalidation": ""}))
    assert out.ideas == []
    assert len(out.dropped) == 1 and "no invalidation" in out.dropped[0]


def test_an_idea_with_no_symbol_is_dropped(store) -> None:  # noqa: ANN001
    """Nobody knows the ticker: 'energy' is not an instrument, and no model is
    asked to turn it into one."""
    out = promote_brief(store, brief({**IDEA, "symbols": []}))
    assert out.ideas == [] and "named no symbol" in out.dropped[0]


def test_a_watch_item_is_never_an_idea(store) -> None:  # noqa: ANN001
    """It has no side. Inventing one is how a watch item becomes a position."""
    from genesis.agents.research.session_plan import live_ideas

    out = promote_brief(store, brief({**IDEA, "bias": "watch"}))
    assert out.ideas == [] and len(out.watching) == 1
    assert live_ideas(store) == [], "nothing that sizes may ever see a watch item"


def test_news_ideas_do_not_collide_with_the_traders_own(store) -> None:  # noqa: ANN001
    """One store, three authors — and none of them overwrites another.

    The trader's own CVX long lives at `cvx-long`, the synthesizer's at `cvx`,
    and this at `cvx-news-long`. Sharing a subject would mean a brief silently
    replacing an idea the trader wrote down.
    """
    from genesis.agents.research.session_plan import record_idea

    record_idea(store, {"symbol": "CVX", "direction": "long", "thesis": "mine",
                        "invalidation": "below 140", "stop_price": 140.0})
    promote_brief(store, brief(IDEA))

    from genesis.agents.research.session_plan import live_ideas

    authors = sorted(idea.author for _id, idea in live_ideas(store))
    assert authors == ["human", NEWS_AUTHOR], authors
