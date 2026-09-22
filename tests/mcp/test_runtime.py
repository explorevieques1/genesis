# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Session lifecycle, driven synchronously from threads.

MCP Gateway.md asks for four behaviours, and three of them are failure
behaviours that a real server will not perform on request. Hence the fake.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from genesis.errors import TransientError
from genesis.mcp.errors import MCPServerSessionError
from genesis.mcp.runtime import GatewayRuntime, ToolCallError
from helpers_mcp import FakeServer


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture
def runtime(server: FakeServer):
    with GatewayRuntime() as rt:
        rt.add("fake", server.factory())
        yield rt


def test_a_session_is_opened_lazily_and_then_reused(runtime, server) -> None:
    """One long-lived session per server, not per call."""
    assert server.opens == 0, "registering a server must not connect to it"

    for _ in range(5):
        runtime.call("fake", "get_quote", {"symbol": "NVDA"})

    assert server.opens == 1
    assert len(server.calls) == 5


def test_calls_to_one_server_serialize(runtime, server) -> None:
    """Queue-based dispatch: one server, one call at a time."""
    server.latency_sec = 0.05
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: runtime.call("fake", f"t{i}"), range(8)))

    assert server.max_concurrent == 1
    assert len(server.calls) == 8


def test_calls_to_different_servers_do_not_interact() -> None:
    """Serialization is per server, not a global bottleneck."""
    a, b = FakeServer(latency_sec=0.1), FakeServer(latency_sec=0.1)
    with GatewayRuntime() as rt:
        rt.add("a", a.factory())
        rt.add("b", b.factory())
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(rt.call, "a", "t")
            f2 = pool.submit(rt.call, "b", "t")
            f1.result(), f2.result()
        elapsed = time.perf_counter() - started

    assert elapsed < 0.19, "two servers ran back-to-back instead of in parallel"


def test_one_dropped_session_reconnects_silently(runtime, server) -> None:
    """A single dropped socket is not news. The caller should not hear about it."""
    server.drop_next = 1
    result = runtime.call("fake", "get_quote")

    assert result.content == "get_quote:ok"
    assert server.opens == 2, "expected exactly one reconnect"


def test_a_second_failure_is_a_typed_error(runtime, server) -> None:
    """...and the second failure is news."""
    server.drop_next = 2
    with pytest.raises(MCPServerSessionError) as exc:
        runtime.call("fake", "get_quote")

    assert exc.value.failure_class == "transient"
    assert exc.value.retryable is True
    assert "get_quote" in str(exc.value)


def test_a_tool_error_does_not_touch_the_session(runtime, server) -> None:
    """The server answered. Reconnecting would discard a healthy session."""
    server.error_next = 1
    with pytest.raises(ToolCallError) as exc:
        runtime.call("fake", "get_quote", {"symbol": "NOT A SYMBOL"})

    assert exc.value.failure_class == "degraded"
    assert server.opens == 1, "a bad argument must not reconnect"


def test_a_slow_tool_does_not_reconnect(runtime, server) -> None:
    """A slow tool is not a dead socket, and the queue behind it still matters."""
    server.latency_sec = 1.0
    with pytest.raises(TransientError) as exc:
        runtime.call("fake", "slow", timeout=0.1)

    assert not isinstance(exc.value, MCPServerSessionError)
    assert "timed out" in str(exc.value)
    assert server.opens == 1


def test_a_server_that_will_not_start_fails_typed(runtime, server) -> None:
    server.connect_fails = 5
    with pytest.raises(MCPServerSessionError):
        runtime.call("fake", "anything")


def test_a_dead_server_does_not_stop_the_others() -> None:
    """One dead news server must not take the system down with it."""
    dead, alive = FakeServer(connect_fails=99), FakeServer()
    with GatewayRuntime() as rt:
        rt.add("dead", dead.factory())
        rt.add("alive", alive.factory())
        with pytest.raises(MCPServerSessionError):
            rt.call("dead", "t")
        assert rt.call("alive", "t").content == "t:ok"


def test_health_is_cheap_and_honest(runtime, server) -> None:
    assert runtime.health("fake") is False, "not connected is not healthy"
    runtime.call("fake", "t")
    assert runtime.health("fake") is True
    server.ping_fails = True
    assert runtime.health("fake") is False


def test_an_idle_stateless_server_is_reaped_and_reopens_on_demand() -> None:
    server = FakeServer()
    with GatewayRuntime() as rt:
        rt.add("fake", server.factory(), idle_timeout_sec=0.05)
        rt.call("fake", "t")
        assert rt.reap_idle() == ()  # not idle yet

        time.sleep(0.08)
        assert rt.reap_idle() == ("fake",)
        assert server.closes == 1

        rt.call("fake", "t")  # and it comes back without anyone intervening
        assert server.opens == 2


def test_a_server_with_no_idle_timeout_stays_open() -> None:
    server = FakeServer()
    with GatewayRuntime() as rt:
        rt.add("fake", server.factory())
        rt.call("fake", "t")
        time.sleep(0.05)
        assert rt.reap_idle() == ()
        assert server.closes == 0


def test_an_unknown_server_is_a_typed_failure(runtime) -> None:
    with pytest.raises(MCPServerSessionError, match="no session configured"):
        runtime.call("nobody", "t")


def test_stop_closes_every_session() -> None:
    server = FakeServer()
    rt = GatewayRuntime()
    rt.start()
    rt.add("fake", server.factory())
    rt.call("fake", "t")
    rt.stop()
    assert server.closes == 1
    assert rt.servers == ()


def test_a_protocol_error_does_not_reconnect(runtime, server) -> None:
    """"Invalid params" is a bad argument, not a dead socket.

    The server answered — it just said no. Reconnecting would tear down a
    healthy session and abandon everything queued behind it, to fix nothing.
    """
    server.protocol_error_next = 1
    with pytest.raises(ToolCallError) as exc:
        runtime.call("fake", "get_quote", {"wrong": "shape"})

    assert exc.value.failure_class == "degraded"
    assert server.opens == 1, "a rejected argument must not reconnect"
    assert runtime.call("fake", "get_quote").content == "get_quote:ok"


def test_a_transport_failure_still_reconnects(runtime, server) -> None:
    """The distinction is by shape, so check the other branch still works."""
    server.drop_next = 1
    assert runtime.call("fake", "t").content == "t:ok"
    assert server.opens == 2


@pytest.mark.parametrize(
    "text",
    [
        'MCP error -32602: Input validation error: Invalid arguments for tool web_fetch_exa',
        "Failed to fetch https://www.investopedia.com/terms/m/market_cycles.asp - status code 403",
    ],
)
def test_an_error_reported_as_ordinary_text_is_still_an_error(runtime, server, text) -> None:
    """Exa and mcp-server-fetch both answer a failure with isError unset.

    Left alone, the error string becomes the page a research agent reads and
    cites — a fetch that lied about having worked.
    """
    server.reply = [SimpleNamespace(text=text)]
    with pytest.raises(ToolCallError):
        runtime.call("fake", "fetch", {"url": "https://example.com"})

    server.reply = [SimpleNamespace(text="Contents of https://example.com/:\nreal page")]
    assert runtime.call("fake", "fetch", {"url": "https://example.com"}).content
