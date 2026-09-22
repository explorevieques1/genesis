# Spec: Genesis Markdown/10-Architecture/Company Data Model.md
"""Assemble one company from every source. The entry point.

``resolve("NVDA")`` is the whole public surface: store first, providers only
for what is missing or stale, EDGAR layered over yfinance, result written back.

Two rules from the note are enforced here rather than trusted to callers.

**Cache before network.** Per-group TTLs mean a repeat call inside the window
touches nothing. This is the same property the bar store guarantees, and it
matters more here: one profile is a dozen HTTP requests to a vendor that rate
limits without warning.

**A thin profile explains itself.** If EDGAR was unreachable, the profile says
so in ``missing`` rather than looking like a company that files nothing. The
difference between "no data" and "no data *yet*" is the difference between a
fact and an outage, and only one of them should change what an agent concludes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from genesis.company.schema import CompanyProfile
from genesis.company.store import CompanyStore
from genesis.company.symbols import normalise
from genesis.errors import DegradedError, GenesisError

__all__ = ["REQUIRED_GROUPS", "Resolution", "describe", "eps_grid", "resolve", "summarise"]

#: Groups a complete answer needs. Missing any of these means a refetch, even
#: when the rest of the profile is cached and valid.
#:
#: `market` is here because it holds price, market cap and every valuation
#: multiple -- the numbers a person is usually asking for. `identity` is here
#: because without it there is no company. Statements, ownership and analyst
#: data are deliberately absent: they are a day old at worst, and refetching
#: the world because an insider filing aged out would defeat the cache.
REQUIRED_GROUPS = frozenset({"identity", "market"})


@dataclass
class Resolution:
    """A profile, plus how it was obtained. The second part is not decoration.

    ``from_cache`` is what a test asserts on to prove the second call made no
    network request, and what the CLI prints so a stale answer is visibly
    stale rather than quietly old.
    """

    profile: CompanyProfile
    from_cache: bool
    providers_used: list[str]
    network_calls: int


def resolve(
    symbol: str,
    *,
    store: CompanyStore | None = None,
    refresh: bool = False,
    use_edgar: bool = True,
) -> Resolution:
    """Everything known about ``symbol``.

    ``refresh=True`` bypasses the cache. ``use_edgar=False`` skips the
    authoritative pass -- faster, and it costs the filed dates, so anything
    doing as-of work must leave it on.
    """
    ticker = normalise(symbol)
    owns_store = store is None
    store = store or CompanyStore()

    try:
        if not refresh:
            cached = store.read(ticker)
            # Identity alone is NOT enough. `market` has a 15-minute TTL, so a
            # profile cached an hour ago is still "identified" while having no
            # price, no market cap and no valuation at all -- and the answer
            # comes back as a bare company name with no numbers in it.
            #
            # Observed: `what is AAPL` returning "Apple Inc.." sixteen minutes
            # after the first lookup. The store already reports which groups
            # are fresh and its docstring promises a caller can refresh the
            # stale ones; this is that caller.
            if (
                cached is not None
                and cached.is_identified
                and REQUIRED_GROUPS <= store.fresh_groups(ticker)
            ):
                return Resolution(cached, True, ["store"], 0)

        profile, used, calls = _fetch(ticker, use_edgar=use_edgar)
        store.write(profile)
        return Resolution(profile, False, used, calls)
    finally:
        if owns_store:
            store.close()


def _fetch(ticker: str, *, use_edgar: bool) -> tuple[CompanyProfile, list[str], int]:
    from genesis.company.providers.edgar import EdgarProvider
    from genesis.company.providers.yfinance import YFinanceProvider

    yahoo = YFinanceProvider()
    if not yahoo.available:
        raise DegradedError(
            "yfinance is not installed, and it is the only source of company "
            "identity — EDGAR has statements but no sector, price or analyst "
            "view. `uv pip install yfinance`."
        )

    # yfinance first, always. It establishes what the company IS; EDGAR
    # establishes what it reported. A profile from EDGAR alone would be
    # financial statements with no company attached.
    profile = yahoo.fetch(ticker)
    used = [yahoo.name]
    calls = yahoo.requests

    if use_edgar:
        edgar = EdgarProvider()
        if edgar.available:
            try:
                profile = edgar.enrich(profile)
                used.append(edgar.name)
                calls += edgar.requests
            except GenesisError as exc:
                # Never fatal. EDGAR being down costs the filed dates and the
                # as-filed numbers; it must not cost the whole profile.
                profile.missing.append(("edgar", exc.reason))
        else:
            profile.missing.append(
                ("edgar", "SEC_EDGAR_USER_AGENT not set — see .env.example")
            )
    return profile, used, calls


def _num(value: Any) -> Decimal | None:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return out if out.is_finite() else None


def _fiscal_quarter(period_end: date, fy_end_month: int) -> tuple[int, int]:
    """(fiscal year, quarter) for a period end. FY is named for the year it ends."""
    months_after = (period_end.month - fy_end_month) % 12
    quarter = 4 if months_after == 0 else -(-months_after // 3)
    year = period_end.year + (1 if period_end.month > fy_end_month else 0)
    return year, quarter


def _add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    return date(d.year + total // 12, total % 12 + 1, 1)


def eps_grid(profile: CompanyProfile, years: int = 3) -> dict[str, Any] | None:
    """Fiscal year x quarter EPS: reported diluted EPS where filed, the analyst
    mean where not. ``actual`` travels with every cell -- a consensus estimate
    shown in the same colour as a reported figure is a forecast posing as fact.

    Estimates are the vendor's consensus and usually non-GAAP; actuals are GAAP
    diluted. The annual cell is a sum only when all four quarters are actual.
    """
    fy_end = profile.get("fiscal_year_end_date")
    income = profile.statement("income", "quarterly")
    if not isinstance(fy_end, date) or income is None:
        return None
    actual_lines = [l for l in income.lines if l.concept == "eps_diluted"]
    if not actual_lines:
        return None

    cells: dict[tuple[int, int], dict[str, Any]] = {}
    for line in actual_lines:
        cells[_fiscal_quarter(line.fiscal_period_end, fy_end.month)] = {
            "value": line.value, "actual": True,
            "period_end": line.fiscal_period_end.isoformat(),
        }
    latest = max(l.fiscal_period_end for l in actual_lines)
    estimates = {
        str(r.get("_index")): _num(r.get("avg"))
        for r in (profile.get("earnings_estimate") or [])
    }
    for key, ahead in (("0q", 3), ("+1q", 6)):
        if estimates.get(key) is not None:
            end = _add_months(latest, ahead)
            cells.setdefault(_fiscal_quarter(end, fy_end.month), {
                "value": estimates[key], "actual": False, "period_end": None,
            })

    current_fy = _fiscal_quarter(_add_months(latest, 3), fy_end.month)[0]
    fys = sorted({fy for fy, _ in cells} | {current_fy, current_fy + 1})[-years:]
    annual: dict[int, dict[str, Any]] = {}
    for fy in fys:
        quarters = [cells.get((fy, q)) for q in (1, 2, 3, 4)]
        if all(c and c["actual"] for c in quarters):
            annual[fy] = {"value": sum(c["value"] for c in quarters), "actual": True}
        elif fy == current_fy and estimates.get("0y") is not None:
            annual[fy] = {"value": estimates["0y"], "actual": False}
        elif fy == current_fy + 1 and estimates.get("+1y") is not None:
            annual[fy] = {"value": estimates["+1y"], "actual": False}

    return {
        "years": fys,
        "quarters": [
            {
                "quarter": q,
                "cells": [cells.get((fy, q)) for fy in fys],
                # Month the quarter ends, e.g. "Jul" -- the label the column shows.
                "month": date(2000, (fy_end.month + 3 * q - 1) % 12 + 1, 1).strftime("%b"),
            }
            for q in (1, 2, 3, 4)
        ],
        "annual": [annual.get(fy) for fy in fys],
    }


def describe(profile: CompanyProfile) -> dict[str, Any]:
    """Everything the `CO` description page shows, shaped and computed here.

    The UI formats; it does not derive. Change, forward yield and the EPS grid
    are arithmetic, so they happen in Python on Decimals.
    """
    g = profile.get
    price, prev = _num(g("price") or g("price_regular")), _num(g("previous_close"))
    change = price - prev if price is not None and prev else None
    rate = _num(g("dividend_rate"))
    trailing = _num(g("dividend_yield_trailing"))

    holders = [
        {
            "holder": r.get("Holder"),
            "value": _num(r.get("Value")),
            "shares": _num(r.get("Shares")),
            "pct_held": _num(r.get("pctHeld")),
            "reported": r.get("Date Reported"),
        }
        for r in (g("institutional_holders") or [])[:20]
    ]
    priced = profile.sourced("price") or profile.sourced("price_regular")
    return {
        "symbol": profile.symbol,
        "name": profile.name,
        "exchange": g("exchange"),
        "sector": g("sector"),
        "industry": g("industry"),
        "website": g("website"),
        "summary": g("business_summary"),
        "quote_type": g("quote_type"),
        "currency": profile.currency,
        "price": price,
        "change": change,
        "change_pct": change / prev * 100 if change is not None else None,
        "volume": g("volume"),
        "quote_date": g("quote_date"),
        "stats": {
            "ceo": g("ceo"),
            "hq": ", ".join(str(x) for x in (g("city"), g("state") or g("country")) if x) or None,
            "employees": g("employees"),
            "sector": g("sector"),
            "industry": g("industry"),
            "price": price,
            "shares_outstanding": g("shares_outstanding"),
            "market_cap": g("market_cap"),
            "currency": profile.currency,
            "float_shares": g("float_shares"),
            "enterprise_value": g("enterprise_value"),
            "held_insiders_pct": _pct(g("held_insiders")),
            "held_institutions_pct": _pct(g("held_institutions")),
            "price_to_sales": g("price_to_sales"),
            "price_to_book": g("price_to_book"),
            "ev_to_ebitda": g("ev_to_ebitda"),
            "ev_to_revenue": g("ev_to_revenue"),
            "pe_trailing": g("pe_trailing"),
            "pe_forward": g("pe_forward"),
            "yield_trailing_pct": trailing * 100 if trailing is not None else None,
            "yield_forward_pct": rate / price * 100 if rate is not None and price else None,
            "yield_5y_pct": g("dividend_yield_5y"),  # already percent -- see provider
            "payout_ratio_pct": _pct(g("payout_ratio")),
            "ex_dividend_date": g("ex_dividend_date"),
            "dividend_date": g("dividend_date"),
            "beta": g("beta"),
            "shares_short": g("shares_short"),
            "short_ratio": g("short_ratio"),
        },
        "eps": eps_grid(profile),
        "holders": holders,
        "news": (g("news") or [])[:10],
        "filings": (g("filings") or [])[:10],
        # Customers, suppliers, competitors, partners: no free source has a
        # supply-chain graph. Said here so the page can say it, not invent it.
        "relations": None,
        "_sources": sorted(profile.sources),
        "_missing": [name for name, _ in profile.missing],
        "_market_as_of": priced.as_of if priced else None,
    }


def _pct(fraction: Any) -> Decimal | None:
    value = _num(fraction)
    return value * 100 if value is not None else None


def summarise(profile: CompanyProfile) -> dict[str, Any]:
    """The handful of facts worth speaking or putting on a card.

    Deliberately small. A profile carries 200+ fields; an answer that recites
    them is not an answer. This is the set that survives the question *"what
    would you say about NVDA in three seconds"* — and every value keeps its
    provenance, because [[Safety Invariants]] §10 applies to a summary exactly
    as it applies to a full report.
    """
    out: dict[str, Any] = {
        "symbol": profile.symbol,
        "name": profile.name,
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "exchange": profile.get("exchange_name") or profile.get("exchange"),
        "currency": profile.currency,
    }
    for key in (
        "price", "market_cap", "pe_trailing", "pe_forward", "margin_gross",
        "margin_profit", "growth_revenue", "target_mean", "recommendation",
        "analyst_count", "week52_high", "week52_low", "dividend_yield",
        "short_percent_float", "held_institutions",
    ):
        entry = profile.sourced(key)
        if entry is not None:
            out[key] = entry.value

    income = profile.statement("income", "annual")
    if income:
        latest = income.concept("revenue")
        if latest:
            out["revenue_fy"] = latest.value
            out["revenue_fy_end"] = latest.fiscal_period_end.isoformat()
            out["revenue_filed"] = (
                latest.filed_date.isoformat() if latest.filed_date else None
            )
        net = income.concept("net_income")
        if net:
            out["net_income_fy"] = net.value

    out["_sources"] = sorted(profile.sources)
    out["_tier"] = profile.worst_tier
    out["_conflicts"] = list(profile.conflicts)
    out["_missing"] = [name for name, _ in profile.missing]
    # The guard that stops a cross-currency ratio being computed from an ADR's
    # USD price and its home-currency books. See Open Questions §14.
    out["_currency_mismatch"] = profile.currency_mismatch
    return out
