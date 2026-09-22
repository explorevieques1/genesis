# Spec: Genesis Markdown/70-Schemas/Markup Spec Schema.md
"""The Markup Spec's four promises, each asserted rather than documented."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from genesis.charting.spec import (
    MAX_ANNOTATIONS,
    BarsRef,
    Fib,
    Level,
    MarkupSpec,
    TradePlan,
    Zone,
    unsourced_prices,
)


def _bars_ref() -> BarsRef:
    return BarsRef(source="test", **{"from": "2025-01-01", "to": "2026-01-01"})


def _spec(**changes) -> MarkupSpec:
    base = {
        "symbol": "nvda",
        "timeframe": "daily",
        "as_of": datetime(2026, 1, 1, tzinfo=UTC),
        "bars_ref": _bars_ref(),
        "annotations": [
            Level(price=122.10, label="PDH", type="resistance", why="prior-day high")
        ],
    }
    base.update(changes)
    return MarkupSpec.build(**base)


def test_symbol_and_timeframe_are_normalised() -> None:
    spec = _spec()
    assert spec.symbol == "NVDA"
    assert spec.timeframe == "1D"


def test_every_annotation_needs_a_why() -> None:
    """Markup Spec Schema: an unexplained line on a chart is noise."""
    with pytest.raises(ValidationError, match="no `why`"):
        Level(price=1.0, label="R", type="resistance", why="   ")


def test_text_annotations_are_the_one_why_exemption() -> None:
    from genesis.charting.spec import TextNote

    note = TextNote(label="note", content="earnings 2/12")
    assert note.why == ""


def test_specs_are_immutable() -> None:
    spec = _spec()
    with pytest.raises(ValidationError):
        spec.symbol = "AMD"  # type: ignore[misc]


def test_a_remark_is_a_child_and_leaves_the_parent_alone() -> None:
    parent = _spec()
    child = parent.remark()
    assert child.parent == parent.id
    assert child.id != parent.id
    assert parent.parent is None


def test_a_remark_cannot_forge_its_own_lineage() -> None:
    """``id``, ``created`` and ``parent`` are not the caller's to set."""
    parent = _spec()
    child = parent.remark(id="ms_forged", parent=None)
    assert child.id != "ms_forged"
    assert child.parent == parent.id


def test_the_annotation_cap_is_enforced_not_advised() -> None:
    too_many = [
        Level(price=100 + i, label=f"L{i}", type="resistance", why="test")
        for i in range(MAX_ANNOTATIONS + 3)
    ]
    with pytest.raises(ValidationError, match="exceeds the cap"):
        MarkupSpec(
            symbol="NVDA", timeframe="1D", as_of=datetime(2026, 1, 1, tzinfo=UTC),
            bars_ref=_bars_ref(), annotations=too_many,
        )


def test_build_trims_to_the_cap_by_strength() -> None:
    """Trimming, not raising: too many *good* levels is an editorial problem."""
    levels = [
        Level(price=100 + i, label=f"L{i}", type="resistance", why="test",
              strength=i / 20)
        for i in range(20)
    ]
    spec = MarkupSpec.build(
        symbol="NVDA", timeframe="1D", as_of=datetime(2026, 1, 1, tzinfo=UTC),
        bars_ref=_bars_ref(), annotations=levels,
    )
    assert len(spec.annotations) == MAX_ANNOTATIONS
    assert min(a.strength for a in spec.levels()) > 0.5


def test_zones_and_plans_survive_the_trim() -> None:
    """The cap must not drop the thing the chart is about to fit a moving average."""
    annotations = [
        Level(price=100 + i, label=f"L{i}", type="resistance", why="t", strength=0.9)
        for i in range(12
        )
    ]
    annotations.append(
        Zone(**{"from": 90.0, "to": 92.0}, label="demand", subtype="fvg", why="gap")
    )
    spec = MarkupSpec.build(
        symbol="NVDA", timeframe="1D", as_of=datetime(2026, 1, 1, tzinfo=UTC),
        bars_ref=_bars_ref(), annotations=annotations,
    )
    assert any(a.kind == "zone" for a in spec.annotations)


def test_a_trade_plan_cannot_have_an_incoherent_stop() -> None:
    with pytest.raises(ValidationError, match="not below entry"):
        TradePlan(label="plan", why="test", side="long", entry=100.0, stop=105.0)


def test_trade_plan_rr_is_recomputed_not_trusted() -> None:
    plan = TradePlan(
        label="plan", why="test", side="long", entry=100.0, stop=98.0,
        targets=[106.0], rr=99.0,
    )
    assert plan.computed_rr == 3.0


def test_unsourced_prices_finds_an_invented_level() -> None:
    """The hallucination check, which is what the eval in the note asks for."""
    spec = _spec()
    assert unsourced_prices(spec, [122.10]) == []
    assert unsourced_prices(spec, [99.0]) == [122.10]


def test_unsourced_prices_tolerates_rounding_not_error() -> None:
    spec = _spec()
    assert unsourced_prices(spec, [122.0999]) == []
    assert unsourced_prices(spec, [122.5]) == [122.10]


def test_fib_prices_derive_from_the_anchors() -> None:
    fib = Fib(
        label="fib", why="dominant swing",
        anchor_from=("2025-01-01", 100.0), anchor_to=("2025-06-01", 200.0),
        retracements=(0.5,),
    )
    assert fib.prices()[0.5] == 150.0


def test_watchable_is_levels_zones_and_plans() -> None:
    spec = MarkupSpec.build(
        symbol="NVDA", timeframe="1D", as_of=datetime(2026, 1, 1, tzinfo=UTC),
        bars_ref=_bars_ref(),
        annotations=[
            Level(price=100.0, label="R", type="resistance", why="t"),
            Zone(**{"from": 90.0, "to": 92.0}, label="d", subtype="fvg", why="t"),
            TradePlan(label="p", why="t", side="long", entry=95.0, stop=92.0),
            Fib(label="f", why="t", anchor_from=("2025-01-01", 90.0),
                anchor_to=("2025-06-01", 110.0)),
        ],
    )
    kinds = {a.kind for a in spec.watchable()}
    assert kinds == {"level", "zone", "trade_plan"}
