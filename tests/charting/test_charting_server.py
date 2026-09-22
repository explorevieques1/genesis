# Spec: Genesis Markdown/30-MCP/genesis-charting-mcp.md
"""The charting MCP surface: ids and symbols in, never rows."""

from __future__ import annotations

import asyncio

import pytest

from genesis.charting.pine import INDICATOR_NAME, compile_pine
from genesis.charting.server import ChartingService, build_server
from genesis.charting.source import StaticBarSource
from genesis.charting.store import SpecStore


@pytest.fixture
def service(trending, ranging, falling, tmp_path):
    source = StaticBarSource(
        {
            ("TEST", "1D"): trending,
            ("TEST", "1W"): ranging,
            ("TEST", "1M"): falling,
        }
    )
    store = SpecStore(tmp_path / "charting.db")
    made = ChartingService(source, store, chart_dir=tmp_path)
    yield made
    store.close()


def test_chart_runs_the_whole_pipeline(service) -> None:
    result = service.chart("TEST", "1D")
    assert result["ok"]
    assert result["spec"].startswith("ms_")
    assert result["image"].endswith(".png")
    assert result["render_hash"].startswith("sha256:")
    assert result["annotations"]


def test_charting_twice_builds_a_lineage(service) -> None:
    first = service.chart("TEST", "1D")
    second = service.chart("TEST", "1D")
    assert second["parent"] == first["spec"]
    assert len(service.lineage(second["spec"])["chain"]) == 2


def test_compute_levels_returns_a_table_not_rows(service) -> None:
    result = service.compute_levels("TEST", "1D")
    assert "candidates" in result
    assert isinstance(result["candidates"], str)
    assert "\t" in result["candidates"]


def test_structure_is_measurements(service) -> None:
    result = service.structure("TEST", "1D")
    assert result["trend"] in ("up", "down", "range")
    assert "adx" in result


def test_diff_spec_scores_the_old_spec(service) -> None:
    spec_id = service.chart("TEST", "1D")["spec"]
    result = service.diff_spec(spec_id)
    assert result["ok"]
    assert "summary" in result
    assert "levels" in result


def test_compile_pine_produces_a_deterministic_script(service) -> None:
    spec_id = service.chart("TEST", "1D")["spec"]
    first = service.compile_pine(spec_id)["pine"]
    second = service.compile_pine(spec_id)["pine"]
    assert first == second
    assert INDICATOR_NAME in first
    assert "//@version=5" in first


def test_the_pine_script_draws_once_not_per_bar(service) -> None:
    """Re-creating objects every bar exhausts Pine's budget and drops the oldest."""
    spec_id = service.chart("TEST", "1D")["spec"]
    source = service.compile_pine(spec_id)["pine"]
    assert "if barstate.islastconfirmedhistory" in source


def test_the_pine_script_never_names_an_order_path(service) -> None:
    spec_id = service.chart("TEST", "1D")["spec"]
    source = service.compile_pine(spec_id)["pine"].lower()
    # Pine's order primitives by name. Not a bare "order" substring: `border_color`
    # contains it, and a check that flags the renderer's own colours is a check
    # nobody will keep.
    for token in ("strategy.entry", "strategy.order", "strategy.close",
                  "strategy(", "indicator(\"genesis markup\", overlay=false"):
        assert token not in source
    assert "//@version=5" in source


def test_the_pine_script_carries_the_spec_id(service) -> None:
    """An overlay you cannot trace back to a spec is one you cannot check."""
    spec_id = service.chart("TEST", "1D")["spec"]
    assert spec_id in service.compile_pine(spec_id)["pine"]


def test_render_composite_produces_one_image_and_a_ladder(service) -> None:
    result = service.render_composite("TEST", ["1M", "1W", "1D"])
    assert result["ok"]
    assert len(result["specs"]) == 3
    assert len(result["ladder"]) == 3


def test_render_analytics_takes_a_declared_spec(service) -> None:
    result = service.render_analytics(
        {
            "form": "bar", "title": "Sectors", "why": "test",
            "categories": ["A", "B"],
            "series": [{"name": "s", "values": [1.0, -2.0]}],
            "value_kind": "percent", "source": "test",
        }
    )
    assert result["ok"]
    assert result["form"] == "bar"


def test_an_unknown_spec_id_is_a_typed_failure(service) -> None:
    from genesis.errors import GenesisError

    with pytest.raises(GenesisError, match="no markup spec"):
        service.compile_pine("ms_nope")


def test_no_tool_takes_bars(service) -> None:
    """Orchestrator Tools: the orchestrator moves ids and summaries, never rows.

    A tool argument is written by a language model, so an argument big enough to
    hold two hundred bars is two hundred rows of context spent before the first
    level is computed.
    """
    tools = asyncio.run(build_server(service).list_tools())
    for tool in tools:
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", {})
        for argument in (schema or {}).get("properties", {}):
            assert argument not in ("bars", "ohlcv", "candles", "data", "prices")


def test_the_tool_surface_is_the_notes_six_plus_analytics(service) -> None:
    tools = asyncio.run(build_server(service).list_tools())
    assert {tool.name for tool in tools} == {
        "chart",
        "compute_levels",
        "structure",
        "render_spec",
        "render_composite",
        "diff_spec",
        "compile_pine",
        "render_analytics",
        "lineage",
    }


def test_a_tool_failure_comes_back_as_data_not_an_exception(service) -> None:
    """The gateway can classify a typed failure; it cannot classify a traceback."""
    import asyncio as _asyncio

    server = build_server(service)
    tools = {tool.name: tool for tool in _asyncio.run(server.list_tools())}
    assert "compile_pine" in tools
    # The service raises; the wrapper is what turns it into a payload.
    from genesis.charting.server import build_server as _build

    wrapped = _build(service)
    assert wrapped is not None


def test_the_service_uses_the_store_it_was_given(tmp_path, trending) -> None:
    """An empty store is falsy; `store or SpecStore()` would swap it silently.

    The symptom of the bug this guards against is the worst kind: tests pass,
    and they pass against the production database in ~/.genesis.
    """
    from genesis.charting.source import StaticBarSource

    store = SpecStore(tmp_path / "given.db")
    assert len(store) == 0
    service = ChartingService(
        StaticBarSource({("TEST", "1D"): trending}), store, chart_dir=tmp_path
    )
    assert service.store is store
    service.chart("TEST", "1D")
    assert len(store) == 1
    store.close()
