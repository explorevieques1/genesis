# Spec: Genesis Markdown/20-Agents/Research/Agent — Fundamental.md
from datetime import date
from decimal import Decimal

import pytest

from genesis.company.schema import CompanyProfile, FinancialStatement, Sourced, StatementLine
from genesis.company.valuation import analyse


def _profile(**over) -> CompanyProfile:
    p = CompanyProfile(symbol="KO")
    values = {
        "long_name": "Coca-Cola", "sector": "Consumer Defensive", "currency": "USD", "quote_type": "EQUITY",
        "price": "60", "eps_trailing": "3", "book_value": "8", "shares_outstanding": "4300000000",
        "free_cash_flow": "5000000000", "total_cash": "10000000000", "total_debt": "40000000000",
        "debt_to_equity": "150", "current_ratio": "1.1", "return_on_equity": "0.4",
        "margin_gross": "0.6", "dividend_rate": "2", "dividend_yield": "3.2", "pe_trailing": "20",
        "price_to_book": "7.5", "target_mean": "70",
        "growth_estimates": [{"_index": "+1y", "stockTrend": "0.07"}],
        "earnings_dates": [
            {"_index": "2026-10-21 08:00", "EPS Estimate": "0.8", "Reported EPS": "nan", "Surprise(%)": "nan"},
            {"_index": "2026-07-22 08:00", "EPS Estimate": "0.8", "Reported EPS": "0.84", "Surprise(%)": "5"},
            {"_index": "2026-04-22 08:00", "EPS Estimate": "0.7", "Reported EPS": "0.69", "Surprise(%)": "-1.4"},
        ],
        **over,
    }
    for k, v in values.items():
        p.set(k, Sourced(v if isinstance(v, list) or k in ("long_name", "sector", "currency", "financial_currency", "quote_type")
                         else Decimal(v), "t"))
    p.statements[("income", "annual")] = FinancialStatement("income", "annual", tuple(
        StatementLine(c, Decimal(v), date(y, 12, 31), frequency="annual")
        for y, c, v in [(2023, "eps_diluted", "2.47"), (2024, "eps_diluted", "2.46"), (2025, "eps_diluted", "3.04"),
                        (2023, "revenue", "45"), (2024, "revenue", "47"), (2025, "revenue", "48")]
    ))
    return p


def test_fair_value_models_and_margin_of_safety():
    fv = analyse(_profile())["fair_value"]
    by = {m["model"]: m["value"] for m in fv["models"]}
    assert by["Graham number"] == pytest.approx((22.5 * 3 * 8) ** 0.5)
    assert by["Graham growth formula"] == pytest.approx(3 * (8.5 + 2 * 7))
    assert by["Analyst mean target"] == 70
    assert "Discounted cash flow" in by
    mid = sum(sorted(by.values())[1:3]) / 2  # four models: median of the middle two
    assert fv["median"] == pytest.approx(mid)
    assert fv["margin_of_safety_pct"] == pytest.approx((mid - 60) / mid * 100)


def test_missing_inputs_skip_a_model_rather_than_zero_it():
    fv = analyse(_profile(eps_trailing="-1"))["fair_value"]
    names = [m["model"] for m in fv["models"]]
    assert "Graham number" not in names and "Graham growth formula" not in names
    assert any("Graham number" in s for s in fv["skipped"])


def test_checklist_reads_percent_quirks_and_unknown_is_not_a_fail():
    tests = {t["test"]: t for t in analyse(_profile())["checklist"]["tests"]}
    assert tests["Debt / equity"]["value"] == pytest.approx(1.5) and tests["Debt / equity"]["pass"] is False
    assert tests["Positive EPS every reported year"]["pass"] is True
    assert tests["EPS growth over reported years"]["pass"] is False  # 2.47 → 3.04 is 23%


def test_earnings_split_reported_from_upcoming():
    er = analyse(_profile())["earnings"]
    assert er["upcoming"] == {"date": "2026-10-21", "eps_estimate": 0.8}
    assert len(er["history"]) == 2 and er["beats"] == 1
    assert er["annual"]["revenue"][-1]["yoy"] == pytest.approx(48 / 47 - 1)


def test_an_adr_gets_no_per_share_fair_value():
    sheet = analyse(_profile(financial_currency="TWD"))
    assert sheet["fair_value"] is None and sheet["caveats"]


def test_the_agent_saves_a_note_and_degrades_without_a_model(tmp_path, monkeypatch):
    from genesis.agents.research.fundamental import FundamentalAgent, resolve_subject
    from genesis.errors import DegradedError
    from genesis.research.store import ResearchStore

    rows = [{"symbol": "KO", "name": "Coca-Cola Company"}, {"symbol": "AAPL", "name": "Apple Inc."},
            {"symbol": "GOOGL", "name": "Alphabet Inc. (Class A)"},
            {"symbol": "GOOG", "name": "Alphabet Inc. (Class C)"}]
    assert resolve_subject("coca-cola", rows) == ("KO", "coca-cola → KO (Coca-Cola Company)")
    assert resolve_subject("app", rows) == ("APP", None)  # not Apple: whole words only
    with pytest.raises(DegradedError):
        resolve_subject("alphabet", rows)

    store = ResearchStore(path=tmp_path / "r.db", vault=tmp_path / "vault")
    agent = FundamentalAgent(store, resolve=lambda _t: _profile())
    monkeypatch.setattr("genesis.agents.research.fundamental.resolve_subject", lambda s: ("KO", None))
    note, _ = agent.analyse("KO")
    assert note.degraded and "no large-tier model" in note.caveats[0]
    saved = (tmp_path / "vault" / note.vault_path()).read_text()
    assert "## Fair value" in saved and "Graham number" in saved and "## Earnings" in saved
