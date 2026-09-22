# Spec: Genesis Markdown/60-UI/Company Description.md
from datetime import date
from decimal import Decimal

from genesis.company.profile import _fiscal_quarter, describe
from genesis.company.schema import CompanyProfile, FinancialStatement, Sourced, StatementLine


def _profile() -> CompanyProfile:
    # NTAP's real shape: fiscal year ends in April, FY named for its end year.
    p = CompanyProfile(symbol="NTAP")
    p.set("fiscal_year_end_date", Sourced(date(2026, 4, 24), "t"))
    p.set("price", Sourced(Decimal("200"), "t", group="market"))
    p.set("previous_close", Sourced(Decimal("180"), "t", group="market"))
    p.set("dividend_rate", Sourced(Decimal("2"), "t", group="actions"))
    p.set("earnings_estimate", Sourced(
        [{"_index": "0q", "avg": "2.6"}, {"_index": "0y", "avg": "10"}, {"_index": "+1y", "avg": "11"}], "t",
    ))
    eps = [("2025-07-31", "1.15"), ("2025-10-31", "1.51"), ("2026-01-31", "1.67"),
           ("2026-04-30", "2.03"), ("2026-07-31", "1.88")]
    p.statements[("income", "quarterly")] = FinancialStatement("income", "quarterly", tuple(
        StatementLine("eps_diluted", Decimal(v), date.fromisoformat(d)) for d, v in eps
    ))
    return p


def test_fiscal_quarter_names_the_year_the_fiscal_year_ends():
    assert _fiscal_quarter(date(2025, 7, 31), 4) == (2026, 1)
    assert _fiscal_quarter(date(2026, 1, 31), 4) == (2026, 3)
    assert _fiscal_quarter(date(2026, 4, 30), 4) == (2026, 4)
    assert _fiscal_quarter(date(2026, 3, 31), 12) == (2026, 1)


def test_eps_grid_keeps_actuals_and_estimates_apart():
    d = describe(_profile())
    grid = d["eps"]
    assert grid["years"] == [2026, 2027, 2028]
    q1, q2 = grid["quarters"][0], grid["quarters"][1]
    assert q1["month"] == "Jul" and q1["cells"][1]["value"] == Decimal("1.88")
    assert q2["cells"][1] == {"value": Decimal("2.6"), "actual": False, "period_end": None}
    # All four FY2026 quarters reported -> a sum; FY2027 is only an estimate.
    assert grid["annual"][0] == {"value": Decimal("6.36"), "actual": True}
    assert grid["annual"][1] == {"value": Decimal("10"), "actual": False}
    assert d["change"] == Decimal("20") and d["stats"]["yield_forward_pct"] == Decimal("1")
