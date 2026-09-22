# Spec: Genesis Markdown/10-Architecture/Company Data Model.md
"""Providers, without the vendors.

No network. What is tested is the logic that is wrong or right before a request
goes out, plus the parsing of payloads shaped like the real ones -- because
those are the parts a live smoke test checks least carefully. A live test tends
to prove only that something came back.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from genesis.company.providers.edgar import CONCEPTS, EdgarProvider
from genesis.company.providers.yfinance import INFO_FIELDS, YFinanceProvider
from genesis.company.schema import CompanyProfile, Sourced


# -- EDGAR: the tag-change trap ---------------------------------------------


def companyfacts(entries: dict[str, list[dict]]) -> dict:
    """A companyfacts payload shaped like SEC's, with the tags given."""
    return {
        "entityName": "NVIDIA CORP",
        "facts": {
            "us-gaap": {
                tag: {"units": {"USD": rows}} for tag, rows in entries.items()
            }
        },
    }


def fact(end: str, filed: str, value: int, form: str = "10-K") -> dict:
    return {"end": end, "filed": filed, "val": value, "form": form}


def test_an_issuer_that_changed_tags_keeps_a_current_revenue():
    """The bug this test exists for was real and silent.

    NVDA reported revenue as `RevenueFromContractWithCustomerExcludingAssessedTax`
    through FY2022 and as `Revenues` after. A first-tag-wins reader returns a
    company whose revenue stops in 2022 while every other field is current.
    Nothing raises; the number is simply four years stale.
    """
    payload = companyfacts(
        {
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                fact("2022-01-30", "2022-03-18", 26_914_000_000)
            ],
            "Revenues": [
                fact("2026-01-25", "2026-02-25", 215_938_000_000)
            ],
        }
    )
    lines = EdgarProvider()._statement_lines(payload)
    revenue = [line for line in lines if line.concept == "revenue"]

    assert len(revenue) == 2, "both tags must be read, not just the first"
    latest = max(revenue, key=lambda line: line.fiscal_period_end)
    assert latest.value == Decimal("215938000000")
    assert latest.fiscal_period_end == date(2026, 1, 25)


def test_the_earliest_filing_wins_for_the_same_period():
    """A 10-K restates the prior two years as comparatives, so FY2023 appears
    in the FY2023, FY2024 and FY2025 filings. Preferring the LATEST tags every
    historical period with a recent filed date, and every as-of query then
    truncates to almost nothing -- observed: a query for 2024-01-01 returned
    FY2021."""
    payload = companyfacts(
        {
            "Revenues": [
                fact("2023-01-29", "2023-02-24", 26_974_000_000),
                fact("2023-01-29", "2026-02-25", 26_974_000_000),  # comparative
            ]
        }
    )
    (line,) = [
        l for l in EdgarProvider()._statement_lines(payload) if l.concept == "revenue"
    ]
    assert line.filed_date == date(2023, 2, 24), "when it FIRST became public"
    assert line.known_by(date(2024, 1, 1)) is True


def test_annual_and_quarterly_are_told_apart_by_actual_duration():
    """By duration, NOT by form -- a 10-Q carries both a three-month figure
    and a cumulative one under the same tag. See
    `test_a_year_to_date_cumulative_figure_is_dropped`."""
    payload = companyfacts(
        {
            "Revenues": [
                {"start": "2025-01-27", "end": "2026-01-25",
                 "filed": "2026-02-25", "val": 1, "form": "10-K"},
                {"start": "2025-07-28", "end": "2025-10-26",
                 "filed": "2025-11-19", "val": 2, "form": "10-Q"},
            ]
        }
    )
    lines = EdgarProvider()._statement_lines(payload)
    assert {l.frequency for l in lines} == {"annual", "quarterly"}


def test_a_duration_fact_with_no_start_is_kept_only_for_an_annual_filing():
    """Real companyfacts always carry `start` on a duration fact, so this is a
    malformed-payload path. A 10-K figure is unambiguous enough to keep; a
    10-Q one could be the quarter or the cumulative, and guessing wrong is the
    2-3x error this classifier exists to prevent -- so it is dropped."""
    kept = EdgarProvider()._statement_lines(
        companyfacts({"Revenues": [fact("2026-01-25", "2026-02-25", 1, "10-K")]})
    )
    assert len(kept) == 1 and kept[0].frequency == "annual"

    dropped = EdgarProvider()._statement_lines(
        companyfacts({"Revenues": [fact("2025-10-26", "2025-11-19", 2, "10-Q")]})
    )
    assert dropped == []


def test_an_amended_filing_still_counts_as_its_base_form():
    """A 10-K/A is a restatement, and it is still an annual figure. Treating
    it as quarterly would silently prefer the superseded original."""
    payload = companyfacts(
        {
            "Revenues": [
                {"start": "2025-01-27", "end": "2026-01-25",
                 "filed": "2026-03-01", "val": 1, "form": "10-K/A"},
            ]
        }
    )
    (line,) = EdgarProvider()._statement_lines(payload)
    assert line.frequency == "annual"


def test_balance_concepts_are_instants_and_income_concepts_are_durations():
    payload = companyfacts(
        {
            "Revenues": [fact("2026-01-25", "2026-02-25", 1)],
            "Assets": [fact("2026-01-25", "2026-02-25", 2)],
        }
    )
    by_concept = {l.concept: l for l in EdgarProvider()._statement_lines(payload)}
    assert by_concept["revenue"].period_type == "duration"
    assert by_concept["total_assets"].period_type == "instant"


def test_edgar_without_a_contact_user_agent_is_unavailable():
    """SEC 403s an anonymous client with a message that reads like an outage.
    Reporting unavailable is better than getting the host IP banned."""
    assert EdgarProvider(user_agent=None).available is False
    assert EdgarProvider(user_agent="Genesis").available is False, "needs a contact"
    assert EdgarProvider(user_agent="Me me@example.com").available is True


def test_an_unavailable_edgar_records_why_and_returns_the_profile():
    """EDGAR being down costs the filed dates. It must not cost the profile."""
    p = CompanyProfile("NVDA")
    p.set("sector", Sourced("Technology", "yfinance"))
    out = EdgarProvider(user_agent=None).enrich(p)
    assert out.get("sector") == "Technology"
    assert any(name == "edgar" for name, _ in out.missing)


def test_reconciliation_compares_the_same_period_only():
    """yfinance's totalRevenue is TTM; EDGAR's is the fiscal year. For NVDA
    those differ by 40% entirely legitimately, and a reconciler that flags it
    teaches everyone to ignore reconciler output."""
    from genesis.company.schema import FinancialStatement, StatementLine

    profile = CompanyProfile("NVDA")
    profile.statements[("income", "annual")] = FinancialStatement(
        statement="income",
        frequency="annual",
        lines=(
            StatementLine(
                concept="revenue", value=Decimal("215938000000"),
                fiscal_period_end=date(2026, 1, 25), frequency="annual",
                source="yfinance",
            ),
        ),
        source="yfinance",
    )
    edgar_lines = [
        StatementLine(
            concept="revenue", value=Decimal("215938000000"),
            fiscal_period_end=date(2026, 1, 25), filed_date=date(2026, 2, 25),
            frequency="annual", source="edgar",
        ),
        # A different period entirely -- must not be compared against the above.
        StatementLine(
            concept="revenue", value=Decimal("130497000000"),
            fiscal_period_end=date(2025, 1, 26), filed_date=date(2025, 2, 26),
            frequency="annual", source="edgar",
        ),
    ]
    EdgarProvider(user_agent="Me me@example.com")._reconcile(profile, edgar_lines)
    assert profile.conflicts == []


def test_a_genuine_disagreement_is_recorded_not_resolved():
    from genesis.company.schema import FinancialStatement, StatementLine

    profile = CompanyProfile("X")
    profile.statements[("income", "annual")] = FinancialStatement(
        statement="income", frequency="annual",
        lines=(
            StatementLine(
                concept="revenue", value=Decimal("100"),
                fiscal_period_end=date(2026, 1, 25), frequency="annual",
                source="yfinance",
            ),
        ),
        source="yfinance",
    )
    EdgarProvider(user_agent="Me me@example.com")._reconcile(
        profile,
        [
            StatementLine(
                concept="revenue", value=Decimal("200"),
                fiscal_period_end=date(2026, 1, 25), filed_date=date(2026, 2, 25),
                frequency="annual", source="edgar",
            )
        ],
    )
    assert len(profile.conflicts) == 1
    assert "edgar wins" in profile.conflicts[0]


# -- yfinance: mapping and coercion -----------------------------------------


def test_every_mapped_field_has_a_known_group():
    """A field in no group gets the short fallback TTL, which is safe but
    means it is re-fetched constantly. Catch it here instead."""
    from genesis.company.schema import TTL

    for raw, (name, group, _) in INFO_FIELDS.items():
        assert group in TTL, f"{raw} -> {name} has unknown group {group!r}"


def test_valuation_multiples_are_marked_derived():
    """A PE is the vendor dividing two numbers it holds. Marked so an answer
    can distinguish a reported figure from an inferred one."""
    for key in ("trailingPE", "forwardPE", "priceToBook", "enterpriseToEbitda"):
        assert INFO_FIELDS[key][2] is True, f"{key} should be derived"


def test_reported_figures_are_not_marked_derived():
    for key in ("marketCap", "sharesOutstanding", "totalCash", "trailingEps"):
        assert INFO_FIELDS[key][2] is False, f"{key} is reported, not derived"


def test_nan_never_becomes_a_value():
    """pandas spells absent as NaN. Storing it puts a value that compares
    false to itself into a field something will later format."""
    assert YFinanceProvider._decimal(float("nan")) is None
    assert YFinanceProvider._decimal(float("inf")) is None
    assert YFinanceProvider._decimal(None) is None
    assert YFinanceProvider._decimal("4512.25") == Decimal("4512.25")


def test_numbers_do_not_pass_through_float():
    provider = YFinanceProvider()
    assert provider._coerce("market_cap", 5562502742016) == Decimal("5562502742016")
    assert provider._coerce("sector", "Technology") == "Technology"


def test_epoch_date_fields_become_dates():
    got = YFinanceProvider()._coerce("ex_dividend_date", 1772668800)
    assert isinstance(got, date)


def test_the_concept_table_covers_all_three_statements():
    from genesis.company.providers.edgar import _STATEMENT_OF

    covered = {_STATEMENT_OF[c][0] for c in CONCEPTS if c in _STATEMENT_OF}
    assert covered == {"income", "balance", "cash_flow"}


# -- traps found by running it against real filers --------------------------


def fact_span(start: str, end: str, filed: str, value: int, form: str = "10-Q") -> dict:
    return {"start": start, "end": end, "filed": filed, "val": value, "form": form}


def test_a_year_to_date_cumulative_figure_is_dropped():
    """The XBRL trap that classifying by FORM alone walks into.

    A 10-Q carries a three-month figure AND a nine-month cumulative one, under
    the same tag, in the same filing. Stored as "quarterly" the cumulative is
    2-3x the real quarter, and every margin and growth rate computed from it is
    wrong by a factor that changes with the quarter.

    Observed on BRK.B: EDGAR operating cash flow 21.6B against yfinance's
    11.2B for the same quarter -- the six-month total versus the three-month.
    """
    payload = companyfacts(
        {
            "NetCashProvidedByUsedInOperatingActivities": [
                fact_span("2026-04-01", "2026-06-30", "2026-08-05", 11_215_000_000),
                fact_span("2026-01-01", "2026-06-30", "2026-08-05", 21_653_000_000),
            ]
        }
    )
    lines = EdgarProvider()._statement_lines(payload)
    assert len(lines) == 1, "the six-month cumulative must be dropped"
    assert lines[0].value == Decimal("11215000000")


def test_a_full_year_duration_is_annual():
    payload = companyfacts(
        {"Revenues": [fact_span("2025-01-26", "2026-01-25", "2026-02-25", 1, "10-K")]}
    )
    (line,) = EdgarProvider()._statement_lines(payload)
    assert line.frequency == "annual"


def test_a_thirteen_week_quarter_is_still_quarterly():
    """Fiscal calendars are ragged -- 52/53-week years, 13-week quarters --
    so the classifier uses ranges rather than exact day counts."""
    payload = companyfacts(
        {"Revenues": [fact_span("2025-10-27", "2026-01-25", "2026-02-25", 1)]}
    )
    (line,) = EdgarProvider()._statement_lines(payload)
    assert line.frequency == "quarterly"


def test_capex_sign_is_normalised_to_the_cash_flow_convention():
    """EDGAR's `PaymentsToAcquire...` is a positive PAYMENT; yfinance reports a
    negative OUTFLOW. Same fact. Left alone the reconciler calls it 200% apart
    on every filer with capex, which is every filer -- and a reconciler that
    cries wolf trains everyone to skip the warnings that matter."""
    payload = companyfacts(
        {
            "PaymentsToAcquirePropertyPlantAndEquipment": [
                fact_span("2022-09-25", "2023-09-30", "2023-11-03", 10_959_000_000, "10-K")
            ]
        }
    )
    (line,) = EdgarProvider()._statement_lines(payload)
    assert line.value == Decimal("-10959000000"), "outflows are negative"


def test_a_class_share_resolves_to_its_cik():
    """SEC spells class shares with a dash (BRK-B), the exchange with a dot
    (BRK.B). Trying only the canonical form reports Berkshire as 'not a US
    filer' -- false, and confidently stated."""
    provider = EdgarProvider(user_agent="Me me@example.com")
    provider._cik_map = {"BRK-B": 1067983, "AAPL": 320193}
    assert provider.cik_for("BRK.B") == 1067983
    assert provider.cik_for("AAPL") == 320193


def test_conflicts_are_grouped_by_concept_not_listed_per_period():
    """One tag-definition difference is ONE finding that recurs, not fifteen.
    Listing each period buries the single large outlier under the small ones."""
    from genesis.company.schema import FinancialStatement, StatementLine

    profile = CompanyProfile("X")
    yf_lines, edgar_lines = [], []
    for year in range(2019, 2027):
        period = date(year, 12, 31)
        yf_lines.append(
            StatementLine(
                concept="cash", value=Decimal("100"), fiscal_period_end=period,
                frequency="annual", source="yfinance",
            )
        )
        edgar_lines.append(
            StatementLine(
                concept="cash", value=Decimal("102"), fiscal_period_end=period,
                filed_date=period, frequency="annual", source="edgar",
            )
        )
    profile.statements[("balance", "annual")] = FinancialStatement(
        statement="balance", frequency="annual",
        lines=tuple(yf_lines), source="yfinance",
    )

    EdgarProvider(user_agent="Me me@example.com")._reconcile(profile, edgar_lines)
    assert len(profile.conflicts) == 1, "eight periods, one finding"
    assert "8 periods" in profile.conflicts[0]
    assert "tag-definition" in profile.conflicts[0], "small + consistent"


def test_a_large_disagreement_is_called_out_as_worth_investigating():
    from genesis.company.schema import FinancialStatement, StatementLine

    profile = CompanyProfile("X")
    profile.statements[("income", "annual")] = FinancialStatement(
        statement="income", frequency="annual",
        lines=(
            StatementLine(
                concept="revenue", value=Decimal("100"),
                fiscal_period_end=date(2026, 1, 1), frequency="annual",
                source="yfinance",
            ),
        ),
        source="yfinance",
    )
    EdgarProvider(user_agent="Me me@example.com")._reconcile(
        profile,
        [
            StatementLine(
                concept="revenue", value=Decimal("360"),
                fiscal_period_end=date(2026, 1, 1), filed_date=date(2026, 2, 1),
                frequency="annual", source="edgar",
            )
        ],
    )
    assert "investigate" in profile.conflicts[0]
