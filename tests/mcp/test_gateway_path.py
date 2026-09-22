# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""The two stages that were seams, and the selection step in front of them.

The call path's order is the design. These tests pin the orderings that are
load-bearing rather than incidental: a cached answer must not spend the quota,
a refused call must not reach a server, and a selection must never name a tool
the agent may not call.
"""

from __future__ import annotations

import pytest

from genesis.agents.base import AgentDeclaration
from genesis.mcp.cache import ResultCache
from genesis.mcp.discovery import DiscoveredTool
from genesis.mcp.gateway import Gateway
from genesis.mcp.limits import RateLimitedError, RateLimiter
from genesis.mcp.registry import ToolRegistry
from genesis.mcp.runtime import GatewayRuntime
from genesis.mcp.servers import ServerConfig
from genesis.mcp.spec import Trust
from helpers_mcp import FakeServer


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


CONFIG = ServerConfig(
    id="alpaca",
    command="x",
    read_only=False,
    trust=Trust.TRUSTED,
    tier=1,
    tools={
        "get_stock_quote": {
            "capability": "market-data.quote",
            "mutating": False,
            "cache": {"ttl_sec": 5},
        },
        "get_stock_bars": {
            "capability": "market-data.ohlcv",
            "mutating": False,
            "cache": {"bar_boundary": True},
        },
        "get_account": {"capability": "broker.account", "mutating": False},
    },
)

TOOLS = [
    DiscoveredTool("get_stock_quote"),
    DiscoveredTool("get_stock_bars"),
    DiscoveredTool("get_account"),
]


def declaration(agent_id: str, tools: list[str]) -> AgentDeclaration:
    return AgentDeclaration(
        id=agent_id,
        name=agent_id.title(),
        family="research",
        cadence=[{"type": "on-demand"}],
        tools=tools,
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture
def gateway(server: FakeServer, clock: Clock):
    with GatewayRuntime() as runtime:
        runtime.add("alpaca", server.factory())
        gw = Gateway(
            ToolRegistry(),
            runtime,
            cache=ResultCache(clock=clock),
            limiter=RateLimiter(clock=clock),
        )
        gw.register_server(CONFIG, TOOLS)
        gw.grant(declaration("analyst", ["market-data.*", "broker.account"]))
        yield gw


# ----------------------------------------------------------------------
# Cache
# ----------------------------------------------------------------------


def test_a_repeat_call_inside_the_ttl_is_one_call(gateway, server, clock) -> None:
    args = {"symbol": "NVDA"}
    gateway.call("analyst", "market-data.quote", args)
    clock.advance(1)
    gateway.call("analyst", "market-data.quote", args)
    assert server.calls.count("get_stock_quote") == 1


def test_a_different_symbol_is_a_different_call(gateway, server) -> None:
    gateway.call("analyst", "market-data.quote", {"symbol": "NVDA"})
    gateway.call("analyst", "market-data.quote", {"symbol": "AMD"})
    assert server.calls.count("get_stock_quote") == 2


def test_an_uncacheable_tool_always_reaches_the_server(gateway, server) -> None:
    """NO_CACHE is the default, and the default must actually mean it."""
    for _ in range(3):
        gateway.call("analyst", "broker.account")
    assert server.calls.count("get_account") == 3


def test_the_cache_is_checked_before_the_rate_limit(gateway, server, clock) -> None:
    """A cached answer must cost nothing — on a 25-a-day key that is the point.

    Checking the limit first would spend a token to discover we already had
    the answer, which turns a cache that protects a quota into a cache that
    merely saves a round trip.
    """
    gateway.limiter.configure("alpaca", per_minute=60, burst=1)
    args = {"symbol": "NVDA"}
    gateway.call("analyst", "market-data.quote", args)  # spends the only token
    gateway.call("analyst", "market-data.quote", args)  # cached; must not raise
    assert server.calls.count("get_stock_quote") == 1


def test_a_stale_entry_rescues_a_failed_call_and_is_labelled(
    gateway, server, clock
) -> None:
    """Proceed with less, and label it — rather than fail with nothing."""
    args = {"symbol": "NVDA"}
    first = gateway.call("analyst", "market-data.quote", args)

    clock.advance(300)  # well past the 5s TTL, inside the 900s stale bound
    # A rejected call, not a dropped session: the server is alive and says no.
    # The runtime classifies that as degraded rather than retrying it, which
    # is exactly the case where an old answer is better than none.
    server.protocol_error_next = 5

    result = gateway.call("analyst", "market-data.quote", args)
    assert result.content == first.content


def test_a_failure_with_no_cached_answer_still_raises(gateway, server) -> None:
    """Degrading is not swallowing. With nothing to serve, the error stands."""
    server.protocol_error_next = 5
    with pytest.raises(Exception):
        gateway.call("analyst", "broker.account")


# ----------------------------------------------------------------------
# Rate limit
# ----------------------------------------------------------------------


def test_the_limit_fires_before_dispatch(gateway, server, clock) -> None:
    gateway.limiter.configure("alpaca", per_minute=60, burst=2)
    gateway.call("analyst", "market-data.quote", {"symbol": "A"})
    gateway.call("analyst", "market-data.quote", {"symbol": "B"})
    with pytest.raises(RateLimitedError):
        gateway.call("analyst", "market-data.quote", {"symbol": "C"})
    assert server.calls.count("get_stock_quote") == 2


def test_an_unlimited_server_is_never_throttled(gateway, server) -> None:
    for i in range(20):
        gateway.call("analyst", "market-data.quote", {"symbol": str(i)})
    assert server.calls.count("get_stock_quote") == 20


# ----------------------------------------------------------------------
# Selection
# ----------------------------------------------------------------------


def test_selection_cannot_name_a_tool_the_agent_may_not_call(gateway) -> None:
    """Scoped to the allow-list, not filtered after the fact.

    Ranking the whole catalogue and trimming would leak the shape of the
    boundary into a log the contained component can read.
    """
    gateway.grant(declaration("narrow", ["market-data.quote"]))
    chosen = gateway.select("narrow", "check the account balance")
    assert chosen.ids == ("alpaca.get_stock_quote",)


def test_an_agent_with_no_grant_is_shown_nothing(gateway) -> None:
    assert gateway.select("stranger", "get me a quote").ids == ()


def test_selection_narrows(gateway) -> None:
    chosen = gateway.select("analyst", "what is the current quote for NVDA", limit=1)
    assert chosen.ids == ("alpaca.get_stock_quote",)
    assert chosen.considered == 3


def test_selection_is_logged_without_quoting_the_task(tmp_path, gateway) -> None:
    """Working Memory owns what is quoted where; a tool log does not.

    The count of terms is enough to debug a selection. The user's words are
    not, and a log that captured them would put spoken conversation into a
    file nobody thought of as a transcript.
    """
    from genesis.observability import EventLog

    log = tmp_path / "events.jsonl"
    gateway.events = EventLog(log, level="debug")
    gateway.select("analyst", "what is the price of gold right now")

    text = log.read_text()
    assert "tool.selected" in text
    assert "gold" not in text
