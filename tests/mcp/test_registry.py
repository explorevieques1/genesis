# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""The catalogue rules, which are safety rules wearing a catalogue's clothes."""

from __future__ import annotations

import pytest

from genesis.config import ConfigError
from genesis.mcp.errors import ToolNotRegisteredError
from genesis.mcp.registry import ToolRegistry
from genesis.mcp.spec import ToolSpec, Trust


def tool(tool_id: str, capability: str, *, tier: int = 5, mutating: bool = False) -> ToolSpec:
    server, name = tool_id.split(".", 1)
    return ToolSpec(
        id=tool_id,
        server=server,
        name=name,
        capability=capability,
        tier=tier,
        mutating=mutating,
        trust=Trust.TRUSTED,
    )


def test_lowest_tier_wins_a_capability_contest() -> None:
    """Three servers return quotes; exactly one is registered for the job."""
    registry = ToolRegistry()
    registry.register_all(
        [
            tool("openbb.get_quote", "market-data.quote", tier=3),
            tool("alpaca.get_stock_quote", "market-data.quote", tier=1),
            tool("tradingview.quote", "market-data.quote", tier=4),
        ]
    )

    assert len(registry) == 1
    assert registry.for_capability("market-data.quote").id == "alpaca.get_stock_quote"
    # And the losers are gone from the catalogue entirely, not merely ranked
    # below -- the router cannot pick what it cannot see.
    assert "openbb.get_quote" not in registry
    assert "tradingview.quote" not in registry


def test_registration_order_does_not_change_the_outcome() -> None:
    """The same config loaded twice must catalogue the same tools."""
    specs = [
        tool("a.quote", "market-data.quote", tier=3),
        tool("b.quote", "market-data.quote", tier=1),
        tool("c.quote", "market-data.quote", tier=2),
    ]
    first, second = ToolRegistry(), ToolRegistry()
    first.register_all(specs)
    second.register_all(list(reversed(specs)))
    assert first.surface() == second.surface()


def test_a_tie_raises_rather_than_picking() -> None:
    """A silent coin-flip between two data sources is the thing to prevent."""
    registry = ToolRegistry()
    with pytest.raises(ConfigError, match="cannot pick between them"):
        registry.register_all(
            [
                tool("a.quote", "market-data.quote", tier=2),
                tool("b.quote", "market-data.quote", tier=2),
            ]
        )


def test_writes_are_refused_by_default_and_the_reason_is_kept() -> None:
    registry = ToolRegistry()
    assert registry.register(tool("obsidian.write", "vault.write", mutating=True)) is False
    assert any("read-only" in r.reason for r in registry.rejected)


def test_a_registry_told_to_allow_writes_takes_ordinary_ones() -> None:
    """Phase 4's exit criterion is a daily brief *in the vault* — that is a write."""
    registry = ToolRegistry(allow_writes=True)
    assert registry.register(tool("obsidian.write", "vault.write", mutating=True))


def test_ordinary_write_permission_does_not_reach_the_broker() -> None:
    """The two gates are separate because the two risks are not the same.

    Safety Invariants §1: there is no place_order in a catalogue with no risk
    engine, and the flag somebody has a daily motive to turn on — the one that
    lets an agent write a markdown file — must not be the flag that opens this.
    """
    registry = ToolRegistry(allow_writes=True)
    for capability in ("order.place", "broker.transfer", "position.close"):
        assert registry.register(
            tool(f"alpaca.{capability.replace('.', '_')}", capability, mutating=True)
        ) is False
    assert all("execution-namespace" in r.reason for r in registry.rejected)


def test_phase_7_can_open_the_execution_gate_deliberately() -> None:
    """One flag, on the server that owns the risk gate, once it exists."""
    registry = ToolRegistry(allow_writes=True, allow_execution_writes=True)
    assert registry.register(
        tool("genesis-execution.propose", "order.propose", mutating=True)
    )


def test_duplicate_ids_raise() -> None:
    registry = ToolRegistry()
    registry.register(tool("a.one", "cap.one"))
    with pytest.raises(ConfigError, match="registered twice"):
        registry.register(tool("a.one", "cap.two"))


def test_missing_tool_is_a_typed_fatal() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolNotRegisteredError) as exc:
        registry.get("nope.nothing")
    assert exc.value.failure_class == "fatal"
    assert exc.value.retryable is False


def test_adding_fifty_tools_keeps_one_owner_per_capability() -> None:
    """The exit criterion in miniature: many tools, no ambiguity."""
    registry = ToolRegistry()
    registry.register_all(
        tool(f"s{i}.t{j}", f"cap.{i}.{j}") for i in range(10) for j in range(10)
    )
    assert len(registry) == 100
    assert len(set(registry.capabilities)) == 100
