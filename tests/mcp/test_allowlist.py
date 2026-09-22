# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Deny by default, and the one syntax that means one thing."""

from __future__ import annotations

import pytest

from genesis.agents.base import AgentDeclaration
from genesis.mcp.allowlist import AllowList, matches
from genesis.mcp.errors import ToolNotAllowedError
from genesis.mcp.registry import ToolRegistry
from genesis.mcp.spec import ToolSpec, Trust


def tool(tool_id: str, capability: str) -> ToolSpec:
    server, name = tool_id.split(".", 1)
    return ToolSpec(
        id=tool_id, server=server, name=name, capability=capability,
        mutating=False, trust=Trust.TRUSTED, tier=1,
    )


def test_exact_and_namespace_grants() -> None:
    assert matches("web.fetch", "web.fetch")
    assert matches("news.*", "news.headlines")
    assert not matches("news.*", "newsletter.send")  # prefix, not substring
    assert not matches("web.fetch", "web.fetch.deep")


def test_there_is_no_bare_wildcard() -> None:
    """A grant nobody can audit at a glance is not a grant we can offer."""
    assert not matches("*", "anything.at.all")


def test_an_agent_with_no_declaration_can_do_nothing() -> None:
    assert AllowList.of("stranger", ()).permits("web.fetch") is False


def test_rejection_is_fatal_and_names_the_tool_reached_for() -> None:
    allow = AllowList.of("news-catalyst", ("news.*", "web.fetch"))
    with pytest.raises(ToolNotAllowedError) as exc:
        allow.check("broker.account", "alpaca.get_account")
    assert exc.value.failure_class == "fatal"
    assert exc.value.retryable is False
    assert "alpaca.get_account" in str(exc.value)


def test_granted_answers_what_this_agent_can_actually_do() -> None:
    registry = ToolRegistry()
    registry.register_all(
        [
            tool("alpaca.get_stock_bars", "market-data.ohlcv"),
            tool("alpaca.get_account", "broker.account"),
            tool("exa.search", "web.search"),
        ]
    )
    analyst = AllowList.of("market-analyst", ("market-data.*",))
    assert analyst.granted(registry) == ("alpaca.get_stock_bars",)


def test_a_pattern_matching_nothing_is_reported_not_ignored() -> None:
    """Usually a typo, and the failure it causes otherwise is a mystery."""
    registry = ToolRegistry()
    registry.register(tool("alpaca.get_stock_bars", "market-data.ohlcv"))
    allow = AllowList.of("screener", ("market-data.ohlcv", "market-dat.levels"))
    assert allow.unmatched(registry) == ("market-dat.levels",)


def test_the_declaration_and_the_gateway_share_one_matcher() -> None:
    """Two implementations of an allow-list is one implementation and one bug.

    ``genesis-execution.*`` is how MCP Gateway.md writes a whole grant, and
    exact matching alone would have refused every real tool under it.
    """
    declaration = AgentDeclaration(
        id="order-manager",
        name="Order Manager",
        family="execution",
        cadence=[{"type": "on-demand"}],
        tools=["genesis-execution.*"],
    )
    assert declaration.may_use_tool("genesis-execution.propose_order")
    assert not declaration.may_use_tool("web.fetch")
