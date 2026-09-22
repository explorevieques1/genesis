# Spec: Genesis Markdown/20-Agents/Charting/Agent — Data Viz.md
"""The non-price renderer, and the design rules it enforces rather than requests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from genesis.charting.analytics import (
    MAX_BARS,
    MAX_SERIES,
    AnalyticsSpec,
    Series,
    render_analytics,
)


def _bar(**changes) -> AnalyticsSpec:
    base = {
        "form": "bar",
        "title": "Sector return",
        "why": "ranking sectors",
        "categories": ["Utilities", "Technology", "Energy"],
        "series": [Series(name="12m", values=[24.8, 12.9, -4.3])],
        "value_kind": "percent",
        "source": "test",
    }
    base.update(changes)
    return AnalyticsSpec(**base)


def test_a_ranked_bar_renders() -> None:
    assert render_analytics(_bar()).png


def test_rendering_is_deterministic() -> None:
    spec = _bar()
    assert render_analytics(spec).render_hash == render_analytics(spec).render_hash


def test_every_chart_needs_a_why() -> None:
    with pytest.raises(ValidationError):
        AnalyticsSpec(form="bar", title="t", categories=["a"],
                      series=[Series(name="s", values=[1.0])])


def test_more_than_eight_series_is_a_build_time_error() -> None:
    """A ninth categorical hue is indistinguishable from one already used."""
    with pytest.raises(ValidationError, match="exceeds"):
        AnalyticsSpec(
            form="line", title="t", why="w",
            times=["2026-01-01", "2026-02-01"],
            series=[
                Series(name=f"s{i}", values=[1.0, 2.0])
                for i in range(MAX_SERIES + 1)
            ],
        )


def test_too_many_bars_is_an_error_not_a_smear() -> None:
    """Past thirty the labels overlap into grey and it still looks like a chart."""
    with pytest.raises(ValidationError, match="legible"):
        _bar(
            categories=[f"c{i}" for i in range(MAX_BARS + 1)],
            series=[Series(name="s", values=[1.0] * (MAX_BARS + 1))],
        )


def test_a_series_of_the_wrong_length_is_rejected() -> None:
    with pytest.raises(ValidationError, match="values for"):
        _bar(series=[Series(name="s", values=[1.0, 2.0])])


def test_a_line_chart_needs_times_and_a_bar_chart_needs_categories() -> None:
    with pytest.raises(ValidationError, match="needs `times`"):
        AnalyticsSpec(form="line", title="t", why="w",
                      series=[Series(name="s", values=[])])
    with pytest.raises(ValidationError, match="needs `categories`"):
        AnalyticsSpec(form="bar", title="t", why="w",
                      series=[Series(name="s", values=[])])


def test_a_heatmap_needs_its_matrix_rows_and_columns() -> None:
    with pytest.raises(ValidationError, match="needs `matrix`"):
        AnalyticsSpec(form="heatmap", title="t", why="w", categories=["a", "b"])


def test_a_line_chart_renders_with_callouts() -> None:
    spec = AnalyticsSpec(
        form="line", title="Fed funds", why="macro context",
        times=[f"20{y:02d}-01-01" for y in range(6, 26)],
        series=[Series(name="EFFR", values=[float(i % 5) for i in range(20)])],
        value_kind="rate", source="FRED DFF",
        notes=[{"x": "2008-01-01", "text": "GFC"}],
    )
    assert render_analytics(spec).png


def test_a_heatmap_renders() -> None:
    spec = AnalyticsSpec(
        form="heatmap", title="Correlation", why="basket concentration",
        categories=["A", "B"], rows=["A", "B"],
        matrix=[[1.0, 0.4], [0.4, 1.0]], value_kind="ratio", source="test",
    )
    assert render_analytics(spec).png


def test_a_stat_tile_renders_a_single_number() -> None:
    spec = AnalyticsSpec(
        form="stat", title="CPI year over year", why="one number is not a bar chart",
        series=[Series(name="cpi", values=[3.1, 3.4])],
        value_kind="percent", source="FRED",
    )
    assert render_analytics(spec).png


def test_a_missing_observation_renders_as_a_gap_not_a_zero() -> None:
    spec = AnalyticsSpec(
        form="line", title="With a hole", why="missing prints happen",
        times=["2026-01-01", "2026-02-01", "2026-03-01"],
        series=[Series(name="s", values=[1.0, None, 3.0])],
        source="test",
    )
    assert render_analytics(spec).png


def test_the_left_gutter_grows_with_the_longest_label(tmp_path) -> None:
    """A fixed margin clips "Consumer Discretionary" and wastes half the plot on "Q1"."""
    from genesis.charting.analytics import _left_margin

    short = _bar(categories=["A", "B", "C"],
                 series=[Series(name="s", values=[1.0, 2.0, 3.0])])
    long = _bar(categories=["Consumer Discretionary", "B", "C"],
                series=[Series(name="s", values=[1.0, 2.0, 3.0])])
    assert _left_margin(long) > _left_margin(short)
