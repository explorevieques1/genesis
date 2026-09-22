# Spec: Genesis Markdown/10-Architecture/Company Data Model.md
"""The two hazards the Company Data Model exists to prevent.

Both were measured against live yfinance on 2026-09-04 before being written
into the note, and both are the kind of bug that produces a *plausible* wrong
answer rather than an error. That is what makes them worth a test file of their
own: nothing else in the system would notice either one.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from genesis.company.schema import CompanyProfile, FinancialStatement, Sourced, StatementLine
from genesis.company.symbols import UnknownSymbol, is_populated_identity, normalise, to_yahoo


# -- hazard 1: a fake ticker returns a truthy dict --------------------------


def test_the_exact_payload_yfinance_returns_for_a_fake_ticker_is_rejected():
    """Measured: yf.Ticker("ZZZZNOTREAL").info -> {"trailingPegRatio": None}.

    Truthy. Length 1. A reasonable `if info:` admits it, and Genesis then
    answers questions about a company that does not exist -- a Safety
    Invariants §10 confabulation entering through a truthiness check.
    """
    assert bool({"trailingPegRatio": None}) is True, "the trap: it IS truthy"
    assert is_populated_identity({"trailingPegRatio": None}) is False


def test_a_name_alone_is_not_enough():
    """A name can be an echo of the query string. Two independent facts
    cannot be."""
    assert is_populated_identity({"longName": "Some Corp"}) is False
    assert is_populated_identity({"longName": "Some Corp", "sector": "Tech"}) is True


@pytest.mark.parametrize(
    "payload",
    [None, {}, [], "NVDA", {"sector": "Tech"}, {"longName": "  "}, {"longName": ""}],
)
def test_non_company_payloads_are_all_rejected(payload):
    assert is_populated_identity(payload) is False


def test_a_real_payload_is_accepted():
    assert is_populated_identity(
        {"longName": "NVIDIA Corporation", "sector": "Technology", "marketCap": 5.5e12}
    )


def test_the_profile_makes_the_same_check():
    """The guard lives in two places on purpose -- at the vendor boundary and
    on the assembled object -- because a profile can also be built from a
    cache, and a cache can hold junk written before the guard existed."""
    empty = CompanyProfile("X")
    assert empty.is_identified is False

    named_only = CompanyProfile("X")
    named_only.set("long_name", Sourced("Some Corp", "yfinance"))
    assert named_only.is_identified is False, "a name alone could be an echo"

    real = CompanyProfile("X")
    real.set("long_name", Sourced("Some Corp", "yfinance"))
    real.set("sector", Sourced("Technology", "yfinance"))
    assert real.is_identified is True


# -- hazard 2: statements are keyed by fiscal period, not filed date --------


def revenue(period: str, filed: str | None, value: str = "100") -> StatementLine:
    return StatementLine(
        concept="revenue",
        value=Decimal(value),
        fiscal_period_end=date.fromisoformat(period),
        filed_date=date.fromisoformat(filed) if filed else None,
        frequency="annual",
    )


def test_a_figure_is_not_known_on_the_day_its_period_closed():
    """The bug in one line. NVDA's FY ending 2026-01-25 was filed 2026-02-25;
    a backtest joining on the period end knows the revenue a month early, and
    produces BETTER results, which is why it never gets investigated."""
    line = revenue("2026-01-25", "2026-02-25")
    assert line.known_by(date(2026, 1, 25)) is False
    assert line.known_by(date(2026, 2, 24)) is False
    assert line.known_by(date(2026, 2, 25)) is True


def test_an_unknown_filed_date_fails_closed():
    """yfinance supplies no filed date. Rather than assume availability, the
    row is invisible to every as-of query -- Safety Invariants §3."""
    assert revenue("2026-01-25", None).known_by(date(2099, 1, 1)) is False


def test_an_as_of_query_returns_the_period_that_was_actually_public():
    statement = FinancialStatement(
        statement="income",
        frequency="annual",
        lines=(
            revenue("2023-01-29", "2023-02-24", "27000"),
            revenue("2025-01-26", "2025-02-26", "130500"),
            revenue("2026-01-25", "2026-02-25", "215938"),
        ),
    )
    # Without a date: the latest known figure. Right for "tell me about NVDA".
    assert statement.concept("revenue").value == Decimal("215938")
    # With one: what a person could have known that day.
    assert statement.concept("revenue", as_of=date(2024, 1, 1)).value == Decimal("27000")
    assert statement.concept("revenue", as_of=date(2025, 6, 1)).value == Decimal("130500")
    # And before anything was filed: nothing, rather than the oldest row.
    assert statement.concept("revenue", as_of=date(2020, 1, 1)) is None


def test_as_known_on_drops_the_future_entirely():
    statement = FinancialStatement(
        statement="income",
        frequency="annual",
        lines=(
            revenue("2023-01-29", "2023-02-24"),
            revenue("2026-01-25", "2026-02-25"),
        ),
    )
    restricted = statement.as_known_on(date(2024, 1, 1))
    assert len(restricted.lines) == 1
    assert restricted.periods() == [date(2023, 1, 29)]


def test_balance_and_income_lines_are_distinguishable():
    """A balance sheet is an instant, an income statement is a duration.
    Conflating them sums a quarterly revenue with a period-end cash balance."""
    assert revenue("2026-01-25", "2026-02-25").period_type == "duration"
    cash = StatementLine(
        concept="cash", value=Decimal("1"), fiscal_period_end=date(2026, 1, 25),
        period_type="instant",
    )
    assert cash.period_type == "instant"


# -- hazard 3: currency is silently mixed -----------------------------------


def test_an_adr_with_mismatched_currencies_is_flagged():
    """yfinance carries `currency` and `financialCurrency` and for ADRs they
    differ: price in USD, books in the home currency. A margin computed across
    the two is meaningless and looks entirely normal. Nothing in the trading
    corpus guards this."""
    adr = CompanyProfile("X")
    adr.set("currency", Sourced("USD", "yfinance"))
    adr.set("financial_currency", Sourced("EUR", "yfinance"))
    assert adr.currency_mismatch is True

    domestic = CompanyProfile("Y")
    domestic.set("currency", Sourced("USD", "yfinance"))
    domestic.set("financial_currency", Sourced("USD", "yfinance"))
    assert domestic.currency_mismatch is False


def test_an_unknown_currency_is_not_a_mismatch():
    """Absent is not conflicting. Flagging it would cry wolf on every profile
    where yfinance simply omitted the field."""
    partial = CompanyProfile("Z")
    partial.set("currency", Sourced("USD", "yfinance"))
    assert partial.currency_mismatch is False


# -- symbols ----------------------------------------------------------------


def test_symbols_are_rejected_not_repaired():
    """A ticker 'fixed' into validity is a request for a different company,
    and it will be answered with a straight face."""
    for bad in ("", "   ", "NVDA; DROP", "../etc/passwd", "N" * 40):
        with pytest.raises(UnknownSymbol):
            normalise(bad)


def test_class_shares_reach_yahoo_in_its_own_spelling():
    assert to_yahoo("BRK.B") == "BRK-B"
    assert to_yahoo("brk b") == "BRK-B"
    assert to_yahoo("NVDA") == "NVDA"


def test_index_aliases_resolve():
    assert to_yahoo("SPX") == "^GSPC"
    assert to_yahoo("VIX") == "^VIX"


# -- provenance -------------------------------------------------------------


def test_untrusted_text_does_not_set_the_profiles_tier():
    """Otherwise every company with news attached reads as tier 4, and the
    tier stops measuring trust and starts measuring whether we fetched
    headlines."""
    profile = CompanyProfile("X")
    profile.set("sector", Sourced("Technology", "yfinance", tier=3))
    profile.set("news", Sourced([{"title": "x"}], "yfinance", tier=4))
    assert profile.worst_tier == 3
    assert profile.has_untrusted is True


def test_a_derived_value_says_so():
    """A PE is a vendor dividing two numbers it holds. If either input is
    stale the ratio is wrong in a way no care about the ratio would catch."""
    pe = Sourced(Decimal("29.16"), "yfinance", derived=True)
    assert "derived" in pe.label()
    assert "derived" not in Sourced("Technology", "yfinance").label()


def test_a_disputed_value_says_so_loudly():
    disputed = Sourced(Decimal("1"), "yfinance", conflict="edgar says 2")
    assert "DISPUTED" in disputed.label()
