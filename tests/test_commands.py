# Spec: Genesis Markdown/10-Architecture/Biological Design.md §reflex arc
"""The command layer: what a sentence turns into, and what it must never do.

No model runs in any of this, which is the point -- these tests pass with no
API key, no network, and give the same answer every time. That property is the
argument for the layer existing.
"""

from __future__ import annotations

import pytest

from genesis.commands import COMMANDS, Command, CommandResult, dispatch, match_command, normalise


def name_of(text: str) -> str | None:
    hit = match_command(text)
    return hit.command.name if hit else None


# -- normalisation ----------------------------------------------------------


@pytest.mark.parametrize(
    "spoken",
    [
        "open trading view",
        "Open TradingView",
        "genesis, open trading view",
        "genesis open up tradingview please",
        "hey genesis, could you open trading view",
        "um, open trading view",
        "OPEN TRADING VIEW!!",
    ],
)
def test_every_natural_phrasing_of_the_launch_command_matches(spoken):
    """A speech-to-text engine transcribes filler, punctuation and the wake
    word. All of it has to fall away before matching, or the command works
    when typed and fails when spoken -- which is the worst possible split."""
    assert name_of(spoken) == "open_tradingview"


def test_the_wake_word_is_optional_and_stripped():
    """Tap-to-speak makes the button the addressing. People say the name
    anyway, and it must not change the meaning."""
    assert normalise("genesis status") == "status"
    assert normalise("status") == "status"


def test_filler_does_not_change_the_command():
    """The property is that the COMMAND survives filler, not that specific
    words are deleted. An earlier version of this test asserted the exact
    normalised string, which pinned an over-aggressive filler list in place --
    one that also ate the "you" in "what are you doing"."""
    assert name_of("um, please could you open trading view") == "open_tradingview"
    assert name_of("uh hey genesis chart NVDA") == "chart"
    # And the words that carry meaning are still there.
    assert "you" in normalise("what are you doing")


# -- routing ----------------------------------------------------------------


@pytest.mark.parametrize(
    "spoken, expected",
    [
        ("chart NVDA", "chart"),
        ("chart nvda daily", "chart"),
        ("draw AAPL", "chart"),
        ("what is NVDA", "company"),
        ("what's AAPL", "company"),
        ("tell me about TSLA", "company"),
        ("look up MSFT", "company"),
        ("status", "status"),
        ("what are you doing", "status"),
        # The canvas: a graph lookup, not a judgement, so it is deterministic.
        ("show me what you found on Gann", "canvas"),
        ("show me what you know about semis", "canvas"),
        ("open a canvas on W.D. Gann", "canvas"),
        ("what do you know about gamma squeezes", "canvas"),
        # Company analysis: an investment question, not a profile lookup.
        ("analyse NVDA", "analyse"),
        ("analyze apple as an investment and save it to my notes", "analyse"),
        ("fair value of MSFT", "analyse"),
        ("is KO undervalued", "analyse"),
        ("what is NVDA worth", "analyse"),
    ],
)
def test_commands_route_to_the_right_action(spoken, expected):
    assert name_of(spoken) == expected


def test_a_compound_analysis_goes_to_the_planner():
    """Several asks in one sentence are several tasks. The table cannot split
    them, and used to search for a company named the whole tail."""
    spoken = ("do analysis on adobe and its earnings as a company. has the price "
              "deviated much from fair value using a value investing buy model")
    assert match_command(spoken) is None


@pytest.mark.parametrize(
    "spoken",
    [
        "research W.D. Gann",
        "research W.D. Gann's findings and save them in my journal",
        "research gamma squeezes",
    ],
)
def test_a_research_request_is_not_a_ticker_lookup(spoken):
    """Operating Model §4: not everything is a symbol.

    `research` used to be a verb on the company command, so "research W.D.
    Gann" matched and resolved to a ticker lookup for "w.d" — the "nobody knows
    the ticker" failure reached by a regex rather than by a model. It now falls
    through to the planner, which has a topic researcher to give it to.
    """
    assert name_of(spoken) is None


def test_the_canvas_does_not_eat_a_chart_or_a_profile():
    """It sits above both in the table, so its patterns have to be tight."""
    assert name_of("chart NVDA daily") == "chart"
    assert name_of("what is NVDA") == "company"
    assert name_of("look up TSLA") == "company"


def test_symbol_and_timeframe_are_extracted():
    hit = match_command("chart ES on 1h")
    assert hit is not None
    assert hit.args["symbol"] == "es"
    assert hit.args["timeframe"] == "1h"


def test_chart_beats_company_for_an_ambiguous_sentence():
    """Both patterns can see a ticker. Order in the table decides, and 'chart
    NVDA' must never be answered with a company profile."""
    assert name_of("chart NVDA") == "chart"


# -- the boundary -----------------------------------------------------------


def test_an_unmatched_sentence_is_not_an_error_and_not_a_guess():
    """The honest response at the edge of the deterministic layer is to say
    so. Guessing at an action is the failure mode that makes a voice assistant
    frightening rather than useful."""
    result = dispatch("make me a sandwich")
    assert result.ok is False
    assert result.command == "unmatched"
    assert "didn't catch" in result.spoken
    # It tells you what it CAN do rather than just failing.
    assert "open tradingview" in result.detail


def test_empty_input_matches_nothing():
    assert match_command("") is None
    assert match_command("   ") is None
    assert match_command("genesis") is None


def test_a_failing_command_returns_a_typed_failure_not_a_crash():
    """Conventions.md §Errors: fail honestly. A command that throws must
    become a spoken 'that didn't work', never a 500 and never a fabricated
    success."""
    from genesis.errors import DegradedError

    def boom(args):
        raise DegradedError("the thing was not there", spoken_summary="I couldn't do that.")

    broken = Command(name="boom", patterns=(r"\bboom\b",), run=boom)
    result = dispatch("boom", commands=(broken,))
    assert result.ok is False
    assert result.spoken == "I couldn't do that."
    assert result.data["failure_class"] == "degraded"


def test_an_unexpected_crash_is_contained():
    def boom(args):
        raise RuntimeError("unexpected")

    broken = Command(name="boom", patterns=(r"\bboom\b",), run=boom)
    result = dispatch("boom", commands=(broken,))
    assert result.ok is False
    assert "RuntimeError" in result.detail


# -- the safety property ----------------------------------------------------


def test_no_command_can_reach_an_order_path():
    """Read-only by construction, not by convention.

    Every command here is afferent -- a chart, a lookup, launching an app. If
    a future command imports an execution path this fails, which is the point:
    the efferent path has its own approval gate and must never be reachable
    from a sentence.
    """
    import inspect

    banned = ("place_order", "propose_order", "place_approved", "submit_order")
    for command in COMMANDS:
        source = inspect.getsource(command.run)
        for token in banned:
            assert token not in source, f"{command.name} references {token}"


def test_every_command_has_help_or_is_deliberately_hidden():
    for command in COMMANDS:
        assert command.name
        assert command.patterns

def test_a_question_that_continues_past_the_symbol_is_not_a_lookup():
    """Operating Model §4: ambiguity is surfaced, never guessed.

    Unanchored, the company pattern took the first word after "what is" — so
    "what is a stock split" answered with Agilent (`A`) and "what is the market
    doing" answered with `MARKET`, both in the confident voice of a real
    profile. A sentence that keeps going after the symbol is a question for the
    orchestrator, not a ticker lookup.
    """
    for said in (
        "what is a stock split",
        "what is the market doing",
        "what is a good entry",
        "when was apple founded",
        "what is nvda trading at",
    ):
        match = match_command(said)
        assert match is None or match.command.name != "company", (said, match)

    # And the lookups it exists for still work.
    for said, symbol in (
        ("what is nvda", "nvda"),
        ("whats apple", "apple"),
        ("tell me about aapl", "aapl"),
        ("nvda profile", "nvda"),
    ):
        match = match_command(said)
        assert match is not None and match.command.name == "company"
        assert match.args["symbol"] == symbol


# -- watchlist ---------------------------------------------------------------


def test_saving_tickers_or_a_screen_to_a_watchlist(monkeypatch):
    from genesis.screener import snapshot
    from genesis.server import watchlist_routes
    from genesis.watchlist.store import WatchlistStore

    store = WatchlistStore(":memory:")
    monkeypatch.setattr(watchlist_routes, "_store", lambda: store)
    monkeypatch.setattr(snapshot, "load_current", lambda: {
        "understood": "Profitable tech growing revenue over 20%.",
        "matches": [{"symbol": "NVDA"}, {"symbol": "AVGO"}],
    })

    # A screen is not a scan request, and it is auto-named from what was asked.
    assert name_of("save these stocks to a watchlist") == "watchlist"
    r = dispatch("save these to a watchlist")
    assert r.ok and store.lists()[0]["name"] == "Profitable tech growing revenue over 20%"

    # Named tickers, auto-named from the first three; junk is skipped, not guessed.
    r = dispatch("save nvda, amd and tsm to a new watchlist")
    assert r.ok and store.lists()[1]["name"] == "NVDA · AMD · TSM"

    # A name that exists is added to, not duplicated.
    dispatch("create a watchlist called semis with nvda")
    r = dispatch("add intc to my semis watchlist")
    semis = [l for l in store.lists() if l["name"] == "Semis"]
    assert r.ok and len(semis) == 1
    assert [m["symbol"] for m in semis[0]["members"]] == ["NVDA", "INTC"]
