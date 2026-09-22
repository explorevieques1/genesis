# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Pinning our reading of the SDK's types against the SDK's actual types.

Everything else in ``tests/mcp`` runs against fakes, deliberately -- the safety
rules must be exercisable without a live server. The cost of that choice is
this file, which is the one place the fakes could drift from reality.

It exists because they did. The SDK renamed ``inputSchema`` to ``input_schema``
and ``readOnlyHint`` to ``read_only_hint`` in v2, keeping the old names only as
wire aliases. Our ``getattr`` for the camelCase names therefore returned the
default and nothing failed: every tool in the catalogue silently carried an
empty schema, which the router would eventually have had to plan with. A
rename that breaks a test is a morning's work; a rename that silently empties
the catalogue is a phase spent debugging the wrong thing.
"""

from __future__ import annotations

from mcp import types

from genesis.mcp.gateway import _discovered_from


class _Listing:
    def __init__(self, tools: list[types.Tool]) -> None:
        self.tools = tools


def test_a_real_sdk_tool_yields_a_real_schema() -> None:
    tool = types.Tool(
        name="get_stock_bars",
        description="Historical bars",
        inputSchema={
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    )
    discovered = _discovered_from(_Listing([tool]))[0]

    assert discovered.name == "get_stock_bars"
    assert discovered.description == "Historical bars"
    assert discovered.input_schema["properties"]["symbol"]["type"] == "string"
    assert discovered.input_schema["required"] == ["symbol"]


def test_a_real_read_only_hint_is_read() -> None:
    tool = types.Tool(
        name="get_quote",
        inputSchema={"type": "object"},
        annotations=types.ToolAnnotations(readOnlyHint=True),
    )
    assert _discovered_from(_Listing([tool]))[0].read_only_hint is True


def test_a_destructive_hint_overrides_a_read_only_one() -> None:
    """A server contradicting itself gets read the dangerous way."""
    tool = types.Tool(
        name="cleanup",
        inputSchema={"type": "object"},
        annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=True),
    )
    assert _discovered_from(_Listing([tool]))[0].read_only_hint is False


def test_no_annotations_means_no_claim() -> None:
    tool = types.Tool(name="mystery", inputSchema={"type": "object"})
    assert _discovered_from(_Listing([tool]))[0].read_only_hint is None
