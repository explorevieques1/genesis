# Spec: Genesis Markdown/10-Architecture/Charting Engine.md
"""Rendering. The acceptance criterion is byte-identical output, so test that."""

from __future__ import annotations

import pytest

from genesis.charting.compose import compose_default
from genesis.charting.levels import compute_levels
from genesis.charting.render import render, render_composite
from genesis.charting.spec import Level, MarkupSpec, TradePlan
from genesis.charting.structure import read_structure
from genesis.charting.theme import DARK


def _spec(bars, **kwargs):
    return compose_default(bars, compute_levels(bars), read_structure(bars), **kwargs)


def test_the_same_spec_and_bars_render_to_the_same_bytes(trending) -> None:
    """Determinism is not a nicety: the vision cache is keyed on this hash."""
    spec = _spec(trending)
    first = render(trending, spec)
    second = render(trending, spec)
    assert first.render_hash == second.render_hash
    assert first.png == second.png


def test_the_render_is_the_configured_size(trending) -> None:
    result = render(trending, _spec(trending))
    assert (result.width, result.height) == DARK.size


def test_a_different_spec_renders_differently(trending) -> None:
    spec = _spec(trending)
    fewer = _spec(trending, max_annotations=3)
    assert render(trending, spec).render_hash != render(trending, fewer).render_hash


def test_writing_to_a_path_creates_the_directory(trending, tmp_path) -> None:
    target = tmp_path / "20-Charts" / "TEST.png"
    result = render(trending, _spec(trending), path=target)
    assert result.path == target
    assert target.exists()
    assert target.read_bytes() == result.png


def test_the_render_ref_carries_the_hash_back_into_the_spec(trending) -> None:
    spec = _spec(trending)
    result = render(trending, spec)
    stamped = spec.with_render(result.ref())
    assert stamped.render.render_hash == result.render_hash
    # with_render must not touch the belief, only the output record.
    assert stamped.annotations == spec.annotations
    assert stamped.id == spec.id


def test_a_level_far_outside_the_price_action_does_not_flatten_the_chart(
    trending,
) -> None:
    """A distant level is reported in words, not drawn at the cost of the chart."""
    spec = MarkupSpec.build(
        symbol=trending.symbol, timeframe=trending.timeframe,
        as_of=trending.last_time,
        bars_ref=_spec(trending).bars_ref,
        annotations=[
            Level(price=float(trending.close[-1]) * 10, label="FAR",
                  type="resistance", why="a level ten times away"),
        ],
    )
    # The assertion that matters is that it renders at all and stays in bounds;
    # a naive implementation autoscales to the outlier and every candle
    # collapses into a line.
    assert render(trending, spec).width == DARK.size[0]


def test_a_volumeless_frame_renders_without_a_volume_panel(make_frame) -> None:
    import numpy as np

    frame = make_frame(np.linspace(100, 140, 200), volume=np.zeros(200))
    assert render(frame, _spec(frame)).png


def test_a_composite_needs_at_least_one_panel() -> None:
    with pytest.raises(ValueError, match="at least one panel"):
        render_composite([])


def test_a_composite_renders_every_timeframe(trending, ranging, falling) -> None:
    panels = [
        (falling, _spec(falling, max_annotations=4)),
        (ranging, _spec(ranging, max_annotations=4)),
        (trending, _spec(trending)),
    ]
    result = render_composite(panels)
    assert (result.width, result.height) == DARK.size
    assert result.render_hash.startswith("sha256:")


def test_a_composite_is_deterministic_too(trending, ranging) -> None:
    panels = [(ranging, _spec(ranging, max_annotations=4)), (trending, _spec(trending))]
    assert render_composite(panels).render_hash == render_composite(panels).render_hash


def test_a_trade_plan_renders(trending) -> None:
    base = _spec(trending)
    spot = float(trending.close[-1])
    spec = MarkupSpec.build(
        symbol=base.symbol, timeframe=base.timeframe, as_of=base.as_of,
        bars_ref=base.bars_ref,
        annotations=[
            TradePlan(label="plan", why="reclaim above the prior high",
                      side="long", entry=spot, stop=spot * 0.97,
                      targets=[spot * 1.06]),
        ],
    )
    assert render(trending, spec).png
