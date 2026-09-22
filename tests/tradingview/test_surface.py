# Spec: Genesis Markdown/30-MCP/genesis-tradingview-mcp.md
"""Read-back verification, degradation, and the tool surface.

None of this needs Electron, which is the point of splitting `surface.py` out
of `server.py`: the behaviour that must hold when TradingView breaks is the
behaviour you cannot test by having TradingView working.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from genesis.tradingview.cdp import CDPUnavailable
from genesis.tradingview.surface import ChartSurface, Selectors, load_selectors


class FakeSession:
    """Answers page expressions from a script, and records what it was asked."""

    def __init__(self, **answers: object) -> None:
        self.answers = answers
        self.seen: list[str] = []
        self.unavailable = False

    def evaluate(self, expression: str):
        self.seen.append(expression)
        if self.unavailable:
            raise CDPUnavailable("TradingView is closed")
        for key, value in self.answers.items():
            if key in expression:
                return value() if callable(value) else value
        return None

    def screenshot(self) -> bytes:
        if self.unavailable:
            raise CDPUnavailable("TradingView is closed")
        return b"\x89PNG"


SELECTORS = Selectors(
    entries={
        "symbol": {
            "probe": "PROBE_symbol",
            "read": "READ_symbol",
            "write": "WRITE_symbol({value})",
        },
        "timeframe": {
            "probe": "PROBE_timeframe",
            "read": "READ_timeframe",
            "write": "WRITE_timeframe({value})",
        },
        "watchlist": {"probe": "PROBE_watchlist", "read": "READ_watchlist"},
    }
)


# ----------------------------------------------------------------------
# The shipped file
# ----------------------------------------------------------------------


def test_the_shipped_selectors_load_and_every_probe_is_present() -> None:
    """One file is the whole surface, and self_test depends on the probes."""
    selectors = load_selectors()
    assert selectors.names()
    for name in selectors.names():
        assert "probe" in selectors.entries[name], f"{name} has no probe"


def test_no_shipped_expression_reaches_the_trade_surface() -> None:
    """The file is data, and the reflex in cdp.py holds over it.

    Asserted here as well so a careless edit to selectors.yaml fails a test
    rather than a call.
    """
    from genesis.tradingview.cdp import _denied

    for name, entry in load_selectors().entries.items():
        for kind, expression in entry.items():
            assert _denied(expression) is None, f"{name}.{kind} touches the trade panel"


# ----------------------------------------------------------------------
# Values reaching JavaScript
# ----------------------------------------------------------------------


def test_a_value_reaches_javascript_as_json_not_as_text() -> None:
    """A symbol is user-supplied, and it lands in an evaluator."""
    expression = SELECTORS.expression("symbol", "write", '"; alert(1); "')
    assert json.loads(expression[len("WRITE_symbol(") : -1]) == '"; alert(1); "'


def test_a_missing_expression_names_the_file_to_fix() -> None:
    with pytest.raises(KeyError, match="selectors.yaml"):
        SELECTORS.expression("watchlist", "write", "x")


# ----------------------------------------------------------------------
# Hard rule 2 — verify every mutation by reading back
# ----------------------------------------------------------------------


def test_a_write_is_confirmed_by_a_read() -> None:
    session = FakeSession(WRITE_symbol=True, READ_symbol="NASDAQ:NVDA")
    verified = ChartSurface(session, SELECTORS).set_symbol("NVDA")
    assert verified.ok and not verified.degraded
    assert "READ_symbol" in session.seen, "the read-back is not optional"


def test_a_write_the_app_ignored_is_degraded_not_success() -> None:
    """The command completing is not evidence it took effect."""
    session = FakeSession(WRITE_symbol=True, READ_symbol="AAPL")
    verified = ChartSurface(session, SELECTORS).set_symbol("NVDA")
    assert not verified.ok
    assert verified.degraded
    assert "AAPL" in verified.detail


def test_an_exchange_prefix_is_not_a_mismatch() -> None:
    """TradingView answers NASDAQ:AAPL when asked for AAPL.

    Reporting that as degraded would set the flag on every successful call,
    and a flag that is always on is a flag nobody reads.
    """
    session = FakeSession(WRITE_symbol=True, READ_symbol="NASDAQ:AAPL")
    assert ChartSurface(session, SELECTORS).set_symbol("aapl").ok


@pytest.mark.parametrize("observed,wanted", [("1D", "D"), ("D", "1D"), ("60", "60")])
def test_timeframe_spellings_are_one_timeframe(observed: str, wanted: str) -> None:
    session = FakeSession(WRITE_timeframe=True, READ_timeframe=observed)
    assert ChartSurface(session, SELECTORS).set_timeframe(wanted).ok


def test_a_chart_api_that_refuses_is_reported_as_degraded() -> None:
    session = FakeSession(WRITE_symbol=False)
    verified = ChartSurface(session, SELECTORS).set_symbol("NVDA")
    assert not verified.ok and verified.degraded
    assert "selectors.yaml" in verified.detail


# ----------------------------------------------------------------------
# Hard rule 4 — degrade, never block
# ----------------------------------------------------------------------


def test_a_closed_app_degrades_rather_than_raising() -> None:
    session = FakeSession()
    session.unavailable = True
    verified = ChartSurface(session, SELECTORS).set_symbol("NVDA")
    assert not verified.ok and verified.degraded


# ----------------------------------------------------------------------
# The fragility budget
# ----------------------------------------------------------------------


def test_self_test_names_the_surface_that_broke() -> None:
    """*"self_test detects a deliberately renamed selector."*

    Per-surface, not pass/fail: "the chart is broken" sends a person to read
    the whole file; "watchlist no longer resolves" sends them to one line.
    """
    session = FakeSession(
        PROBE_symbol=True, PROBE_timeframe=True, PROBE_watchlist=False
    )
    report = ChartSurface(session, SELECTORS).self_test()
    assert not report["ok"]
    assert report["broken"] == ["watchlist"]
    assert "watchlist" in report["detail"]


def test_self_test_passes_when_everything_resolves() -> None:
    session = FakeSession(PROBE_symbol=True, PROBE_timeframe=True, PROBE_watchlist=True)
    assert ChartSurface(session, SELECTORS).self_test()["ok"]


# ----------------------------------------------------------------------
# Hard rule 1, at the tool surface
# ----------------------------------------------------------------------


def test_no_defined_tool_can_reach_an_order_path() -> None:
    """The note's acceptance criterion, enumerated rather than asserted in prose.

    Two properties: no tool is named for trading, and no tool takes an
    order-shaped argument. The second is the one that matters — a tool called
    `apply_markup` that accepted a `side` would pass a name check.
    """
    from genesis.tradingview.server import build_server

    tools = asyncio.run(build_server().list_tools())
    names = {tool.name for tool in tools}
    assert names == {
        "open_symbol",
        "set_timeframe",
        "quote",
        "watchlist",
        "screenshot",
        # The markup half. `apply_markup` is the exact case the docstring
        # names: it is an actuator, and the reason it is safe is not its name
        # but its argument shape — a spec id and a boolean, no side, no size.
        "apply_markup",
        "clear_markup",
        # The general-purpose script half. `write_pine` takes words and turns
        # them into an indicator; it takes no side and no size, and the
        # strategy reflex in surface.py stops the one kind of Pine that could
        # reach a broker.
        "write_pine",
        "add_to_chart",
        "read_pine",
        "ohlcv",
        "self_test",
        "status",
    }

    forbidden_words = ("order", "buy", "sell", "trade", "position", "size", "qty")
    for tool in tools:
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", {})
        # `args`/`kwargs` here means the guard decorator ate the signature, and
        # a tool whose schema is `*args` cannot be called by anything. It also
        # makes the check below vacuous, which is worse: the argument-shape
        # assertion is the half of hard rule 1 that actually matters.
        assert set((schema or {}).get("properties", {})) != {"args", "kwargs"}, (
            f"{tool.name} exposes no real arguments"
        )
        assert not any(word in tool.name.lower() for word in forbidden_words)
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", {})
        for argument in (schema or {}).get("properties", {}):
            assert not any(word in argument.lower() for word in forbidden_words), (
                f"{tool.name} takes an order-shaped argument: {argument}"
            )


# ----------------------------------------------------------------------
# Latency — the readout a person waits for is one round trip
# ----------------------------------------------------------------------


def test_the_quote_readout_is_one_round_trip_not_three() -> None:
    """Symbol, timeframe and quote used to be three socket round trips.

    A person is sitting in front of this one waiting for an answer, so the
    test is on the call count, not on the values: a refactor that reads them
    back apart again would still return the right thing and would silently
    cost three times the latency.
    """
    from genesis.tradingview.server import build_server

    session = FakeSession(READ_snapshot={"symbol": "NQ1!", "timeframe": "5", "quote": {}})
    selectors = Selectors(entries={"snapshot": {"probe": "P", "read": "READ_snapshot"}})
    surface = ChartSurface(session, selectors)

    assert surface.snapshot()["symbol"] == "NQ1!"
    assert len(session.seen) == 1

    del build_server  # imported only to keep the tool and the surface in one file


def test_a_dead_session_reconnects_instead_of_spending_the_call() -> None:
    """The app restarts during a day; the call after it must not be the casualty.

    Without the retry the first tool call after a restart reports
    ``unavailable`` — the person asks, gets nothing, asks again, gets an
    answer. That reads as flakiness and it is really a stale socket.
    """
    import asyncio

    from genesis.tradingview.server import build_server

    class StaleOnce:
        port = 9222

        def __init__(self) -> None:
            self.calls = 0
            self.dropped = 0

        def surface(self):
            self.calls += 1
            if self.calls == 1:
                raise CDPUnavailable("the app closed the CDP socket")
            return ChartSurface(
                FakeSession(READ_watchlist=["NQ1!"]),
                Selectors(entries={"watchlist": {"probe": "P", "read": "READ_watchlist"}}),
            )

        def drop(self) -> None:
            self.dropped += 1

    conn = StaleOnce()
    result = asyncio.run(build_server(conn).call_tool("watchlist", {}))
    assert conn.dropped == 1
    assert "NQ1!" in str(result)


# ----------------------------------------------------------------------
# The script tools — and the second door to a broker
# ----------------------------------------------------------------------


PINE = Selectors(
    entries={
        "pine_editor": {"probe": "P", "write": "OPEN_editor"},
        "pine_source": {"probe": "P", "read": "READ_src", "write": "WRITE_src({value})"},
        "pine_apply": {"probe": "P", "write": "APPLY"},
        "pine_save": {"probe": "P", "write": "SAVE({value})"},
        "pine_add_saved": {"probe": "P", "write": "ADD({value})"},
        "pine_indicator": {"probe": "P", "read": "READ_legend"},
    }
)


@pytest.mark.parametrize(
    "source",
    [
        'strategy("mine", overlay=true)',
        "strategy.entry('long', strategy.long)",
        "STRATEGY . ENTRY(x)",
        "//@version=5\nstrategy.close_all()",
    ],
)
def test_a_pine_strategy_is_refused_before_it_reaches_the_socket(source: str) -> None:
    """A strategy script is an order path, not a drawing.

    TradingView connects strategies to broker integrations and trades them —
    which is a way around the pre-trade risk engine that the Trade panel rule
    never covered, because until the script tools existed the panel was the
    only door. This is the reflex on the other one.
    """
    from genesis.tradingview.cdp import ForbiddenSurface

    session = FakeSession(WRITE_src=True)
    with pytest.raises(ForbiddenSurface):
        ChartSurface(session, PINE).write_pine_source(source)
    assert session.seen == [], "the refusal must happen before the expression is sent"


def test_an_indicator_that_merely_mentions_a_strategy_still_compiles() -> None:
    """The reflex may not fire on prose, or nobody will be able to write a script."""
    session = FakeSession(WRITE_src=True)
    source = '//@version=5\nindicator("trend strategy notes", overlay=true)\nplot(close)'
    assert ChartSurface(session, PINE).write_pine_source(source)


def test_a_script_that_never_reaches_the_legend_is_degraded_not_ok() -> None:
    """Hard rule 2 over the script path: the chart's legend is the read-back."""
    from genesis.tradingview import markup

    session = FakeSession(READ_legend=[])
    surface = ChartSurface(session, PINE)
    assert markup.wait_for_legend(surface, "My Script", timeout=0.0) is None
    assert markup.wait_for_legend(
        ChartSurface(FakeSession(READ_legend=["My Script"]), PINE), "my script", timeout=0.0
    ) == ["My Script"]
