# Spec: Genesis Markdown/20-Agents/Research/Agent — Fundamental.md §On-demand company analysis
"""The arithmetic under a company analysis. ``tier: none`` -- no model here.

Safety Invariants §3: a language model never computes a number. The Fundamental
agent's model reads what this module returns and writes judgement around it;
every figure in the note comes from here, with the inputs that produced it.

Three blocks, each honest about what it could not compute:

* :func:`fair_value` -- Graham number, Graham growth formula, a two-stage FCF
  DCF, and the analyst mean target, each with its inputs and assumptions. A
  model that lacks an input is *absent*, never zero.
* :func:`value_checklist` -- Graham's defensive-investor tests plus three
  quality proxies. ``None`` means unknown, which is not a fail.
* :func:`earnings` -- reported vs estimate, the next report, the annual trend
  and the forward consensus.

yfinance quirks handled here, not downstream: ``debt_to_equity`` and
``dividend_yield`` arrive as percents; every other ratio is a fraction.
"""

from __future__ import annotations

import math
from datetime import date
from statistics import median
from typing import Any

from genesis.company.schema import CompanyProfile

__all__ = ["analyse", "earnings", "fair_value", "value_checklist"]

#: Stage-one growth is clamped: an analyst's +1y for a hypergrowth year
#: compounded for five years produces a number nobody should read.
MAX_GROWTH = 0.25
MIN_GROWTH = -0.10


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _row(records: Any, index: str, column: str) -> float | None:
    for r in records or []:
        if str(r.get("_index")) == index:
            return _f(r.get(column))
    return None


def _growth(profile: CompanyProfile) -> tuple[float | None, str]:
    """The growth rate the models use, and where it came from."""
    for value, source in (
        (_row(profile.get("growth_estimates"), "+1y", "stockTrend"), "analyst EPS growth, next year"),
        (_f(profile.get("growth_earnings")), "trailing earnings growth"),
        (_f(profile.get("growth_revenue")), "trailing revenue growth"),
    ):
        if value is not None:
            return value, source
    return None, "none available"


def _series(profile: CompanyProfile, statement: str, concept: str) -> list[tuple[date, float]]:
    stmt = profile.statement(statement, "annual")
    if stmt is None:
        return []
    by_period = {l.fiscal_period_end: _f(l.value) for l in stmt.lines if l.concept == concept}
    return sorted((d, v) for d, v in by_period.items() if v is not None)


def fair_value(
    profile: CompanyProfile, *, discount: float = 0.10, terminal: float = 0.025
) -> dict[str, Any]:
    g = profile.get
    price = _f(g("price") or g("price_regular"))
    eps, bvps = _f(g("eps_trailing")), _f(g("book_value"))
    # Reported FCF (operating cash flow − capex) from the latest annual filing;
    # yfinance's info `freeCashflow` is a levered estimate and can be half of it.
    reported = _series(profile, "cash_flow", "free_cash_flow")
    shares = _f(g("shares_outstanding"))
    fcf, fcf_source = (reported[-1][1], f"annual cash flow statement, FY ending {reported[-1][0]}") if reported \
        else (_f(g("free_cash_flow")), "yfinance levered free cash flow")
    cash, debt = _f(g("total_cash")) or 0.0, _f(g("total_debt")) or 0.0
    growth, growth_source = _growth(profile)
    models: list[dict[str, Any]] = []
    skipped: list[str] = []

    if eps and bvps and eps > 0 and bvps > 0:
        models.append({
            "model": "Graham number", "value": math.sqrt(22.5 * eps * bvps),
            "inputs": {"eps_trailing": eps, "book_value_per_share": bvps},
            "assumes": "√(22.5 × EPS × book/share) — P/E 15 × P/B 1.5, a defensive ceiling",
        })
    else:
        skipped.append("Graham number: needs positive EPS and book value")

    if eps and eps > 0 and growth is not None:
        pct = min(max(growth, 0.0), 0.15) * 100
        models.append({
            "model": "Graham growth formula", "value": eps * (8.5 + 2 * pct),
            "inputs": {"eps_trailing": eps, "growth_pct_used": pct, "growth_source": growth_source},
            "assumes": "EPS × (8.5 + 2g), g capped 0–15%, no bond-yield adjustment",
        })
    else:
        skipped.append("Graham growth formula: needs positive EPS and a growth rate")

    if fcf and fcf > 0 and shares and growth is not None:
        g1 = min(max(growth, MIN_GROWTH), MAX_GROWTH)
        flow, pv = fcf, 0.0
        for year in range(1, 11):
            # Five years at g1, then a straight fade to the terminal rate.
            rate = g1 if year <= 5 else g1 + (terminal - g1) * (year - 5) / 5
            flow *= 1 + rate
            pv += flow / (1 + discount) ** year
        pv += flow * (1 + terminal) / (discount - terminal) / (1 + discount) ** 10
        models.append({
            "model": "Discounted cash flow", "value": (pv + cash - debt) / shares,
            "inputs": {"free_cash_flow": fcf, "fcf_source": fcf_source, "growth_used": g1, "growth_source": growth_source,
                       "discount_rate": discount, "terminal_growth": terminal,
                       "net_cash": cash - debt, "shares": shares},
            "assumes": f"10y two-stage FCF: {g1:.0%} for 5y fading to {terminal:.1%}, "
                       f"discounted at {discount:.0%}, plus net cash",
        })
    else:
        skipped.append("DCF: needs positive free cash flow, shares and a growth rate")

    target = _f(g("target_mean"))
    if target:
        models.append({
            "model": "Analyst mean target", "value": target,
            "inputs": {"analysts": _f(g("analyst_count"))},
            "assumes": "consensus 12-month target — an opinion, not a valuation",
        })

    for m in models:
        m["upside_pct"] = (m["value"] / price - 1) * 100 if price else None

    values = [m["value"] for m in models]
    mid = median(values) if values else None
    mos = (mid - price) / mid * 100 if mid and price and mid > 0 else None
    band = None
    if mos is not None:
        band = "undervalued" if mos >= 20 else "overvalued" if mos <= -20 else "fairly valued"
    return {
        "price": price, "models": models, "skipped": skipped,
        "low": min(values) if values else None, "high": max(values) if values else None,
        "median": mid, "margin_of_safety_pct": mos, "band": band,
    }


def value_checklist(profile: CompanyProfile) -> dict[str, Any]:
    g = profile.get
    pe, pb = _f(g("pe_trailing")), _f(g("price_to_book"))
    de = _f(g("debt_to_equity"))
    eps_hist = _series(profile, "income", "eps_diluted")
    reported = _series(profile, "cash_flow", "free_cash_flow")
    fcf = reported[-1][1] if reported else _f(g("free_cash_flow"))

    def test(name: str, value: Any, threshold: str, ok: bool | None, unit: str = "x") -> dict[str, Any]:
        """``unit`` tells the renderer how to show ``value``: x, pct, money or years."""
        return {"test": name, "value": value, "threshold": threshold, "pass": ok, "unit": unit}

    tests = [
        test("P/E", pe, "≤ 15", None if pe is None else 0 < pe <= 15),
        test("P/B", pb, "≤ 1.5", None if pb is None else 0 < pb <= 1.5),
        test("P/E × P/B", pe * pb if pe and pb else None, "≤ 22.5",
             None if not (pe and pb) else 0 < pe * pb <= 22.5),
        test("Current ratio", _f(g("current_ratio")), "≥ 2", None if g("current_ratio") is None else _f(g("current_ratio")) >= 2),
        test("Debt / equity", de / 100 if de is not None else None, "≤ 0.5×", None if de is None else de <= 50),
        test("Positive EPS every reported year", len(eps_hist) or None, "all > 0",
             None if not eps_hist else all(v > 0 for _, v in eps_hist), "years"),
        test("EPS growth over reported years", eps_hist[-1][1] / eps_hist[0][1] - 1 if len(eps_hist) > 1 and eps_hist[0][1] > 0 else None,
             "> 33%", None if len(eps_hist) < 2 or eps_hist[0][1] <= 0 else eps_hist[-1][1] / eps_hist[0][1] > 1.33, "pct"),
        test("Pays a dividend", _f(g("dividend_rate")), "> 0", (_f(g("dividend_rate")) or 0) > 0, "money"),
        test("Return on equity", _f(g("return_on_equity")), "≥ 15%",
             None if g("return_on_equity") is None else _f(g("return_on_equity")) >= 0.15, "pct"),
        test("Free cash flow", fcf, "> 0", None if fcf is None else fcf > 0, "money"),
        test("Gross margin (pricing power)", _f(g("margin_gross")), "≥ 40%",
             None if g("margin_gross") is None else _f(g("margin_gross")) >= 0.40, "pct"),
    ]
    known = [t for t in tests if t["pass"] is not None]
    return {"tests": tests, "passed": sum(1 for t in known if t["pass"]), "known": len(known)}


def earnings(profile: CompanyProfile) -> dict[str, Any]:
    g = profile.get
    history, upcoming = [], None
    for r in g("earnings_dates") or []:
        est, rep = _f(r.get("EPS Estimate")), _f(r.get("Reported EPS"))
        when = str(r.get("_index"))[:10]
        if rep is None:
            upcoming = {"date": when, "eps_estimate": est}
        else:
            history.append({"date": when, "eps_estimate": est, "eps_reported": rep,
                            "surprise_pct": _f(r.get("Surprise(%)"))})

    def trend(statement: str, concept: str) -> list[dict[str, Any]]:
        rows = _series(profile, statement, concept)
        return [
            {"fiscal_year_end": d.isoformat(), "value": v,
             "yoy": (v / rows[i - 1][1] - 1) if i and rows[i - 1][1] > 0 else None}
            for i, (d, v) in enumerate(rows)
        ]

    return {
        "history": history,
        "beats": sum(1 for h in history if h["surprise_pct"] is not None and h["surprise_pct"] > 0),
        "upcoming": upcoming,
        "annual": {"revenue": trend("income", "revenue"), "eps_diluted": trend("income", "eps_diluted"),
                   "free_cash_flow": trend("cash_flow", "free_cash_flow")},
        "consensus": [
            {"period": r.get("_index"), "eps_avg": _f(r.get("avg")), "growth": _f(r.get("growth")),
             "analysts": _f(r.get("numberOfAnalysts"))}
            for r in g("earnings_estimate") or []
        ],
    }


def analyse(profile: CompanyProfile, **kwargs: Any) -> dict[str, Any]:
    """The full fact sheet the agent narrates. Refuses what it cannot compare."""
    g = profile.get
    caveats = []
    if profile.currency_mismatch:
        caveats.append(f"quote currency {profile.currency} differs from reporting currency "
                       f"{profile.financial_currency} — per-share fair values not computed")
    if g("quote_type") not in (None, "EQUITY"):
        caveats.append(f"{g('quote_type')} is not an operating company — fair value models do not apply")
    snapshot = {k: _f(g(k)) for k in (
        "market_cap", "enterprise_value", "pe_trailing", "pe_forward", "price_to_book", "ev_to_ebitda",
        "margin_gross", "margin_operating", "margin_profit", "return_on_equity", "growth_revenue",
        "growth_earnings", "total_cash", "total_debt", "free_cash_flow", "beta", "week52_high", "week52_low",
    )}
    reported = _series(profile, "cash_flow", "free_cash_flow")
    if reported:  # the filed figure over Yahoo's levered estimate, as the DCF uses
        snapshot["free_cash_flow"] = reported[-1][1]
    snapshot["dividend_yield"] = _f(g("dividend_yield")) / 100 if g("dividend_yield") is not None else None
    return {
        "symbol": profile.symbol, "name": profile.name, "sector": g("sector"), "industry": g("industry"),
        "currency": profile.currency, "snapshot": snapshot,
        "fair_value": None if caveats else fair_value(profile, **kwargs),
        "checklist": value_checklist(profile),
        "earnings": earnings(profile),
        "sources": sorted(profile.sources), "missing": [n for n, _ in profile.missing],
        "caveats": caveats,
    }
