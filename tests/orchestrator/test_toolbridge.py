# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""The translation layer between the gateway and a model's tool surface.

What these assert, in the order they matter: that nothing the model says can
reach a server the allow-list did not already permit, that a call always
produces a result, and that the tool surface stays small enough for the voice
budget no matter how large the catalogue grows.
"""

from __future__ import annotations

import pytest

from genesis.errors import DegradedError
from genesis.llm.anthropic_backend import ToolCall
from genesis.mcp.spec import ToolSpec, Trust
from genesis.orchestrator.toolbridge import (
    SEARCH_TOOL_NAME,
    ToolBridge,
    schema_for,
    wire_name,
)


class FakeSelection:
    def __init__(self, tools):
        self.tools = tuple(tools)
        self.considered = len(self.tools)
        self.matched = True

    def __iter__(self):
        return iter(self.tools)

    def __len__(self):
        return len(self.tools)


class FakeGateway:
    """Stands in for the gateway, recording what it was asked to do."""

    def __init__(self, specs=(), *, raises=None, result="ok"):
        self._specs = tuple(specs)
        self.calls: list[tuple[str, str, dict]] = []
        self.searches: list[str] = []
        self._raises = raises
        self._result = result

    def select(self, agent, task, *, task_type="", limit=8):  # noqa: ARG002
        return FakeSelection(self._specs[:limit])

    def tool_search(self, agent, query, *, budget, limit=5):  # noqa: ARG002
        self.searches.append(query)
        budget.spend()
        return FakeSelection(self._specs[:limit])

    def call(self, agent, capability, arguments=None, **_):
        self.calls.append((agent, capability, dict(arguments or {})))
        if self._raises is not None:
            raise self._raises
        return _Result(self._result)


class _Result:
    def __init__(self, content):
        self.content = content


def spec(capability: str, *, mutating: bool = False) -> ToolSpec:
    return ToolSpec(
        id=f"srv.{capability}",
        server="srv",
        name=capability,
        capability=capability,
        description=f"does {capability}",
        input_schema={"type": "object", "properties": {"symbol": {"type": "string"}}},
        trust=Trust.UNTRUSTED,
        mutating=mutating,
    )


# --------------------------------------------------------------------------
# Name mapping
# --------------------------------------------------------------------------


def test_wire_name_is_legal_for_the_api() -> None:
    """The API allows [a-zA-Z0-9_-]; capabilities are written with dots."""
    assert wire_name("market-data.ohlcv") == "market_data__ohlcv"
    assert wire_name("time.now") == "time__now"


def test_wire_name_does_not_collide_across_separators() -> None:
    """Collapsing '-' and '.' to one character would make the reverse lookup a
    coin flip between two real capabilities."""
    assert wire_name("market-data.ohlcv") != wire_name("market.data.ohlcv")


def test_schema_marks_read_only_tools() -> None:
    assert schema_for(spec("market-data.quote")).get("description", "").startswith(
        "[read-only]"
    )
    assert not schema_for(spec("vault.create", mutating=True))[
        "description"
    ].startswith("[read-only]")


def test_schema_survives_a_tool_with_no_input_schema() -> None:
    bare = ToolSpec(id="s.t", server="s", name="t", capability="time.now")
    assert schema_for(bare)["input_schema"]["type"] == "object"


# --------------------------------------------------------------------------
# The surface offered per utterance
# --------------------------------------------------------------------------


def test_surface_is_capped_and_carries_the_escape_hatch() -> None:
    gw = FakeGateway([spec(f"cap.{i}") for i in range(50)])
    bridge = ToolBridge(gw, limit=8)
    tools = bridge.tools_for_utterance("what is nvda doing")
    assert len(tools) == 9  # 8 selected + find_more_tools
    assert tools[-1]["name"] == SEARCH_TOOL_NAME


def test_empty_catalogue_offers_nothing_at_all() -> None:
    """Not even the search tool: there is nothing to search past, and offering
    one tool that can only fail is worse than saying the surface is empty."""
    assert ToolBridge(FakeGateway([])).tools_for_utterance("anything") == []


def test_a_new_utterance_resets_the_previous_surface() -> None:
    gw = FakeGateway([spec("time.now")])
    bridge = ToolBridge(gw)
    bridge.tools_for_utterance("what time is it")
    bridge.gateway = FakeGateway([spec("news.headlines")])
    bridge.tools_for_utterance("any news")
    # The tool from the first turn must no longer resolve.
    _, is_error = bridge.execute(ToolCall("1", "time__now", {}))
    assert is_error


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------


def test_a_call_reaches_the_gateway_with_the_real_capability() -> None:
    gw = FakeGateway([spec("market-data.quote")])
    bridge = ToolBridge(gw, agent="orchestrator")
    bridge.tools_for_utterance("quote nvda")
    content, is_error = bridge.execute(
        ToolCall("1", "market_data__quote", {"symbol": "NVDA"})
    )
    assert not is_error
    assert gw.calls == [("orchestrator", "market-data.quote", {"symbol": "NVDA"})]
    assert content == "ok"


def test_an_unoffered_tool_is_refused_and_never_reaches_the_gateway() -> None:
    """The safety property: the model naming a capability does not grant it.
    A tool that was not selected this turn is not callable, full stop."""
    gw = FakeGateway([spec("time.now")])
    bridge = ToolBridge(gw)
    bridge.tools_for_utterance("what time is it")
    content, is_error = bridge.execute(ToolCall("1", "place__order", {"qty": 100}))
    assert is_error
    assert "No tool named" in content
    assert gw.calls == []


def test_the_refusal_names_what_is_available_so_the_model_can_recover() -> None:
    gw = FakeGateway([spec("time.now")])
    bridge = ToolBridge(gw)
    bridge.tools_for_utterance("hello")
    content, _ = bridge.execute(ToolCall("1", "nonsense", {}))
    assert "time__now" in content


def test_a_gateway_failure_comes_back_as_a_result_not_an_exception() -> None:
    """A tool_use block with no tool_result is an API error and a model that
    starts guessing. Every path must produce content."""
    gw = FakeGateway([spec("news.headlines")], raises=DegradedError("server is down"))
    bridge = ToolBridge(gw)
    bridge.tools_for_utterance("any news")
    content, is_error = bridge.execute(ToolCall("1", "news__headlines", {}))
    assert is_error
    assert "server is down" in content


# --------------------------------------------------------------------------
# The escape hatch
# --------------------------------------------------------------------------


def test_search_makes_the_found_tools_callable() -> None:
    gw = FakeGateway([spec("macro.series")])
    bridge = ToolBridge(gw)
    bridge.tools_for_utterance("unrelated")
    content, is_error = bridge.execute(
        ToolCall("1", SEARCH_TOOL_NAME, {"query": "cpi"})
    )
    assert not is_error
    assert "macro__series" in content
    # And is now genuinely callable, not merely described.
    _, failed = bridge.execute(ToolCall("2", "macro__series", {}))
    assert not failed


def test_search_budget_is_per_turn_and_enforced() -> None:
    gw = FakeGateway([spec("macro.series")])
    bridge = ToolBridge(gw, search_budget=2)
    bridge.tools_for_utterance("something")
    for _ in range(2):
        _, is_error = bridge.execute(ToolCall("x", SEARCH_TOOL_NAME, {"query": "q"}))
        assert not is_error
    content, is_error = bridge.execute(
        ToolCall("x", SEARCH_TOOL_NAME, {"query": "q"})
    )
    assert is_error
    assert "No searches left" in content


def test_search_budget_resets_on_the_next_utterance() -> None:
    gw = FakeGateway([spec("macro.series")])
    bridge = ToolBridge(gw, search_budget=1)
    bridge.tools_for_utterance("first")
    bridge.execute(ToolCall("x", SEARCH_TOOL_NAME, {"query": "q"}))
    bridge.tools_for_utterance("second")
    _, is_error = bridge.execute(ToolCall("x", SEARCH_TOOL_NAME, {"query": "q"}))
    assert not is_error


@pytest.mark.parametrize("query", ["", "   "])
def test_search_needs_a_query(query: str) -> None:
    bridge = ToolBridge(FakeGateway([spec("a.b")]))
    bridge.tools_for_utterance("x")
    _, is_error = bridge.execute(ToolCall("1", SEARCH_TOOL_NAME, {"query": query}))
    assert is_error
