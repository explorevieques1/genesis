# Spec: Genesis Markdown/60-UI/Voice UX.md
"""The pronunciation table is an acceptance criterion, so it is a test.

Voice UX: *"Numbers are read per the table above, verified on a spoken eval
set."* Every row of that table appears here verbatim.
"""

from __future__ import annotations

import pytest

from genesis.voice.speech import (
    say_confidence,
    say_money,
    say_multiple,
    say_percent,
    say_price,
    say_r_multiple,
    say_ticker,
    say_time,
    speakable,
)


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        ("121.06", "one twenty-one oh six"),
        ("1642.00", "sixteen forty-two"),
        ("118.40", "one eighteen forty"),
        ("545", "five forty-five"),
        ("99.50", "ninety-nine fifty"),
    ],
)
def test_prices_use_trader_shorthand(written, spoken):
    assert say_price(written) == spoken


def test_money_uses_cardinals_not_price_shorthand():
    # "three twelve" would be mistakable for a price. Risk figures must not be.
    assert say_money("312") == "three hundred twelve dollars"


def test_percent_is_directional():
    assert say_percent("-2.1") == "down two point one percent"
    assert say_percent("1.2") == "up one point two percent"
    # A share of equity is not a move; "up" would be nonsense.
    assert say_percent("0.31", directional=False) == "point three one percent"


def test_r_multiple_always_states_sign():
    assert say_r_multiple("1.2") == "plus one point two R"
    assert say_r_multiple("-2") == "minus two R"


def test_confidence_is_a_decimal_not_a_percent():
    assert say_confidence("0.72") == "point seven two"


def test_multiple_and_time():
    assert say_multiple("2.4") == "two point four times"
    assert say_time("08:30") == "eight thirty"
    assert say_time("09:00") == "nine o'clock"


def test_tickers_are_spelled_unless_conventionally_pronounced():
    assert say_ticker("NVDA") == "N-V-D-A"  # never "nividia"
    assert say_ticker("SPY") == "spy"
    assert say_ticker("ES") == "E-S"
    assert say_ticker("NQ") == "N-Q"


def test_speakable_rewrites_a_whole_sentence():
    out = speakable("NVDA long from 121.06, stop 118.40, risk $312")
    assert "N-V-D-A" in out
    assert "one twenty-one oh six" in out
    assert "one eighteen forty" in out
    assert "three hundred twelve dollars" in out
    assert "121" not in out  # no digits survive to the voice


def test_speakable_is_idempotent():
    """The backends render defensively and the echo filter renders separately;
    double application must not corrupt the text."""
    once = speakable("NVDA long from 121.06, +1.2R by 15:45")
    assert speakable(once) == once


def test_speakable_never_raises_on_junk():
    # A malformed number must not silence the whole sentence.
    assert speakable("...") == "..."
    assert "hello" in speakable("hello 1.2.3.4 world")
