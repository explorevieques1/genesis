# Spec: Genesis Markdown/60-UI/Voice UX.md
"""Dates, years and ordinals — and the numbers that must NOT become them.

Found live: asking Genesis when NVIDIA was founded produced *"April five one
thousand nine hundred ninety-three"*. Two bugs in one sentence — a day of the
month read as a count, and a year read as a cardinal.

The second half of this file matters more than the first. In a trading system
``1995`` is a year in one sentence and a share count in the next, and reading a
fill price as a year would be a far worse bug than the one being fixed.
"""

from __future__ import annotations

import pytest

from genesis.voice.speech import say_date, say_ordinal, say_year, speakable


class TestYears:
    @pytest.mark.parametrize(
        ("year", "spoken"),
        [
            (1993, "nineteen ninety-three"),
            (2026, "twenty twenty-six"),
            (2000, "two thousand"),
            (2005, "two thousand five"),
            (2010, "twenty ten"),
            (1900, "nineteen hundred"),
            (1905, "nineteen oh five"),
            (1642, "sixteen forty-two"),
        ],
    )
    def test_the_conventions_people_actually_use(self, year: int, spoken: str) -> None:
        assert say_year(year) == spoken

    def test_outside_the_plausible_range_it_stays_a_cardinal(self) -> None:
        """"three oh five" for 305 would answer a question nobody asked."""
        assert say_year(305) == "three hundred five"


class TestOrdinals:
    @pytest.mark.parametrize(
        ("n", "spoken"),
        [(1, "first"), (2, "second"), (3, "third"), (5, "fifth"), (11, "eleventh"),
         (12, "twelfth"), (20, "twentieth"), (21, "twenty-first"), (30, "thirtieth"),
         (31, "thirty-first")],
    )
    def test_days_of_the_month(self, n: int, spoken: str) -> None:
        assert say_ordinal(n) == spoken


class TestDatesInSentences:
    @pytest.mark.parametrize(
        ("written", "spoken"),
        [
            # The exact sentence that exposed the bug.
            ("NVIDIA was founded on April 5, 1993.",
             "NVIDIA was founded on April fifth, nineteen ninety-three."),
            ("NVIDIA was founded in 1993.",
             "NVIDIA was founded in nineteen ninety-three."),
            ("Earnings on 2026-09-02.", "Earnings on September second, twenty twenty-six."),
            ("Filed 5 April 1993.", "Filed April fifth, nineteen ninety-three."),
            ("Report due April 5.", "Report due April fifth."),
            ("Due Apr 5th.", "Due April fifth."),
        ],
    )
    def test_dates_are_read_as_dates(self, written: str, spoken: str) -> None:
        assert speakable(written) == spoken

    def test_a_date_and_a_time_coexist(self) -> None:
        assert speakable("9/2/2026 at 08:30") == (
            "September second, twenty twenty-six at eight thirty"
        )


class TestNumbersThatAreNotYears:
    """The regression that would cost money rather than dignity."""

    def test_a_share_count_stays_a_count(self) -> None:
        assert speakable("Sold 1995 shares.") == "Sold one thousand nine hundred ninety-five shares."

    def test_a_fill_price_stays_a_price(self) -> None:
        """"filled at 2000" is a price. Reading it as a year is the bad failure."""
        assert "two thousand" in speakable("Filled at 2000.")
        assert "twenty" not in speakable("Filled at 2000.")

    def test_prices_and_tickers_are_untouched(self) -> None:
        assert speakable("NVDA long from 121.06, stop 118.40, risk $312 (0.31%)") == (
            "N-V-D-A long from one twenty-one oh six, stop one eighteen forty, "
            "risk three hundred twelve dollars (point three one percent)"
        )

    def test_a_lowercase_word_is_not_a_ticker(self) -> None:
        """The month patterns need IGNORECASE; tickers must not inherit it."""
        assert speakable("may and can") == "may and can"
        assert speakable("SPY and NVDA") == "spy and N-V-D-A"
