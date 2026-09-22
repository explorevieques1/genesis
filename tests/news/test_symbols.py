# Spec: Genesis Markdown/10-Architecture/Operating Model.md §4
"""Which symbols a brief is about — and the ones it must refuse to see.

Operating Model §4: nobody knows the ticker. Every test here is about the
*refusals*, because the extraction itself is a dictionary lookup and the whole
difficulty is what it declines to match: English words that are tickers, index
names that are also companies, and a symbol the brief argues both ways on.
"""

from __future__ import annotations

import types

from genesis.news.symbols import extract


def universe(*symbols: str, names: dict[str, str] | None = None):
    return types.SimpleNamespace(symbols=tuple(symbols), names=names or {})


def brief(**kwargs):
    return {"overview": "", "stories": [], "themes": [], "watch": [], "risks": [], **kwargs}


def story(headline: str, direction: str = "neutral", symbols=(), body: str = ""):
    return {"headline": headline, "direction": direction, "symbols": list(symbols),
            "what_happened": body, "why_it_matters": ""}


# ----------------------------------------------------------------------
# Finding
# ----------------------------------------------------------------------


def test_a_tagged_symbol_outranks_one_merely_mentioned() -> None:
    """Tagging involved no inference, so nothing about it can be wrong."""
    found = extract(
        brief(stories=[story("Chevron beats", "bullish", ["CVX"], "Chevron beat estimates.")],
              overview="Exxon also rose."),
        universe=universe("CVX", "XOM", names={"CVX": "CHEVRON CORP", "XOM": "EXXON MOBIL CORP"}),
    )
    assert [m.symbol for m in found][0] == "CVX"
    assert found[0].tagged and found[0].direction == "long"


def test_a_company_name_resolves_to_its_ticker() -> None:
    """"Chevron" is CVX by lookup against the holdings file — never by a model.

    Scored without the threshold, because resolution and *worth acting on* are
    two different questions and the test below asks the second one.
    """
    found = extract(brief(overview="Chevron led the tape all week."),
                    universe=universe("CVX", names={"CVX": "CHEVRON CORP"}),
                    min_score=0)
    assert [m.symbol for m in found] == ["CVX"]
    assert "chevron" in found[0].why[0]


def test_a_company_named_once_in_passing_is_not_a_trade_idea() -> None:
    """One sentence about Chevron in a market wrap is not an idea about Chevron.

    Without this the board fills with every company anyone mentioned, which is
    the failure mode of extracting from prose at all.
    """
    once = extract(brief(overview="Chevron led the tape all week."),
                   universe=universe("CVX", names={"CVX": "CHEVRON CORP"}))
    assert once == []

    twice = extract(
        brief(overview="Chevron led the tape. Chevron's buyback is the reason."),
        universe=universe("CVX", names={"CVX": "CHEVRON CORP"}),
    )
    assert [m.symbol for m in twice] == ["CVX"]


def test_a_cashtag_is_always_taken() -> None:
    found = extract(brief(overview="Watching $IT into the print."),
                    universe=universe("IT", names={}))
    assert [m.symbol for m in found] == ["IT"]


# ----------------------------------------------------------------------
# Refusing — the part that earns its keep
# ----------------------------------------------------------------------


def test_english_words_that_are_tickers_are_not_symbols() -> None:
    """"ALL EYES ON THE FED" would otherwise be three trade ideas."""
    found = extract(brief(overview="ALL EYES ON THE FED AS KEY DATA IS DUE NOW."),
                    universe=universe("ALL", "ON", "KEY", "IT", "NOW", "IS", "A"))
    assert found == []


def test_an_index_reference_is_not_the_exchange_that_runs_it() -> None:
    """"Nasdaq 100 rebalance" is not a story about NDAQ's shares."""
    found = extract(
        brief(overview="SpaceX's Nasdaq 100 weight jumps in the quarterly rebalance."),
        universe=universe("NDAQ", names={"NDAQ": "NASDAQ INC"}),
    )
    assert [m.symbol for m in found] == []


def test_a_symbol_outside_the_universe_is_never_extracted() -> None:
    """An idea about something this desk cannot trade is noise on the board."""
    found = extract(brief(stories=[story("Toyota recalls", "bearish", ["TM"])]),
                    universe=universe("SPY"))
    assert found == []


def test_a_symbol_the_brief_argues_both_ways_on_is_watch() -> None:
    """Ambiguity is surfaced, never picked — and it stays surfaced.

    A third story agreeing with one side does not break the tie: the brief is
    not of one mind about this symbol, and that is the finding.
    """
    found = extract(
        brief(stories=[
            story("Rebalance lifts it", "bullish", ["QQQ"]),
            story("Yields press it", "bearish", ["QQQ"]),
            story("And lifts it again", "bullish", ["QQQ"]),
        ]),
        universe=universe("QQQ"),
    )
    assert [m.symbol for m in found] == ["QQQ"]
    assert found[0].direction == "watch" and found[0].conflicted


def test_a_passing_mention_does_not_clear_the_bar() -> None:
    found = extract(brief(risks=["A stronger dollar"]),
                    universe=universe("UUP", names={"UUP": "INVESCO DB US DOLLAR INDEX"}))
    assert found == []


def test_every_mention_carries_the_evidence_that_found_it() -> None:
    """An extracted idea has to be able to say why it exists."""
    found = extract(brief(stories=[story("Dow slides", "bearish", ["DIA", "SPY"])]),
                    universe=universe("DIA", "SPY"))
    assert all(m.why and m.stories == ["Dow slides"] for m in found)
    assert all(m.direction == "short" for m in found)
