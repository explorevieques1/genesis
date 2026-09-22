# Spec: Genesis Markdown/10-Architecture/Company Data Model.md
"""yfinance, used fully and distrusted carefully.

**Fully**, because the breadth is the reason it is the spine here: one
``Ticker`` object yields 189 ``info`` fields and 35 working endpoints --
identity, classification, size, valuation, margins, growth, balance-sheet
health, dividends, analyst targets and revisions, upgrade history, institutional
and insider ownership, short interest, earnings dates, corporate actions,
filings index and news. Measured against NVDA on 2026-09-04. Nothing else free
comes close, and most of it is not in any filing, so EDGAR cannot supply it.

**Distrusted**, because it scrapes unofficial endpoints. Three concrete
behaviours this module is built around, all observed rather than assumed:

1. **A non-existent ticker returns a truthy dict.** ``ZZZZNOTREAL`` yields
   ``{"trailingPegRatio": None}``. Handled by
   :func:`genesis.company.symbols.is_populated_identity`, and it is the first
   thing :meth:`YFinanceProvider.fetch` checks -- everything after depends on
   the symbol being real.

2. **It fails silently, per endpoint.** During the same NVDA fetch that
   returned 35 working endpoints, a ``404`` for one sub-resource was printed to
   stderr and swallowed; the call returned normally. So an endpoint raising is
   not the failure mode to design for -- an endpoint quietly returning nothing
   is. Every section here records *why* it is absent rather than leaving a gap
   that reads like "this company has no institutional holders".

3. **Everything after the first call is free.** Endpoint timings within one
   ``Ticker`` were 2.2s for the first and 0.0s for most of the rest: yfinance
   memoises on the object. So this provider builds **one Ticker per fetch** and
   pulls every section from it. Constructing a Ticker per section would turn
   one request into a dozen and is the obvious mistake.

Retry shape adapted from
``TradingAgents/tradingagents/dataflows/stockstats_utils.py`` -- back off on
rate limiting *only*, let everything else propagate immediately, because
retrying a 404 is just a slower 404.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable

from genesis.company.schema import (
    CompanyProfile,
    FieldGroup,
    FinancialStatement,
    Sourced,
    StatementLine,
)
from genesis.company.symbols import UnknownSymbol, is_populated_identity, to_yahoo
from genesis.errors import DegradedError, TransientError

__all__ = ["INFO_FIELDS", "STATEMENT_CONCEPTS", "YFinanceProvider"]

log = logging.getLogger(__name__)

#: yfinance's ``info`` key -> our name, with the field group that sets its cache
#: TTL and a flag for values the vendor computed rather than the company
#: reported.
#:
#: Curated rather than exhaustive: ``info`` carries 189 keys and many are
#: presentation junk (``maxAge``, ``gmtOffSetMilliseconds``, address lines). The
#: long tail stays reachable through ``profile.get("raw:<key>")`` -- see
#: :meth:`YFinanceProvider._apply_info` -- so nothing is lost, but the named
#: fields are the ones anything downstream should rely on.
INFO_FIELDS: dict[str, tuple[str, FieldGroup, bool]] = {
    # identity ------------------------------------------------------------
    "symbol": ("symbol", "identity", False),
    "longName": ("long_name", "identity", False),
    "shortName": ("short_name", "identity", False),
    "quoteType": ("quote_type", "identity", False),
    "exchange": ("exchange", "identity", False),
    "fullExchangeName": ("exchange_name", "identity", False),
    "currency": ("currency", "identity", False),
    "financialCurrency": ("financial_currency", "identity", False),
    "sector": ("sector", "identity", False),
    "industry": ("industry", "identity", False),
    "country": ("country", "identity", False),
    "website": ("website", "identity", False),
    "longBusinessSummary": ("business_summary", "identity", False),
    "fullTimeEmployees": ("employees", "identity", False),
    "city": ("city", "identity", False),
    "state": ("state", "identity", False),
    "lastFiscalYearEnd": ("fiscal_year_end_date", "identity", False),
    # size ----------------------------------------------------------------
    "marketCap": ("market_cap", "market", False),
    "enterpriseValue": ("enterprise_value", "market", True),
    "sharesOutstanding": ("shares_outstanding", "market", False),
    "floatShares": ("float_shares", "market", False),
    # price ---------------------------------------------------------------
    "currentPrice": ("price", "market", False),
    "regularMarketPrice": ("price_regular", "market", False),
    "previousClose": ("previous_close", "market", False),
    "regularMarketVolume": ("volume", "market", False),
    "regularMarketTime": ("quote_date", "market", False),
    "fiftyTwoWeekHigh": ("week52_high", "market", False),
    "fiftyTwoWeekLow": ("week52_low", "market", False),
    "fiftyDayAverage": ("ma50", "market", True),
    "twoHundredDayAverage": ("ma200", "market", True),
    "beta": ("beta", "market", True),
    "averageVolume": ("avg_volume", "market", True),
    # valuation -- every one of these is the vendor dividing two numbers ---
    "trailingPE": ("pe_trailing", "market", True),
    "forwardPE": ("pe_forward", "market", True),
    "priceToBook": ("price_to_book", "market", True),
    "priceToSalesTrailing12Months": ("price_to_sales", "market", True),
    "enterpriseToRevenue": ("ev_to_revenue", "market", True),
    "enterpriseToEbitda": ("ev_to_ebitda", "market", True),
    "bookValue": ("book_value", "market", True),
    # margins and returns -------------------------------------------------
    "profitMargins": ("margin_profit", "statements", True),
    "grossMargins": ("margin_gross", "statements", True),
    "operatingMargins": ("margin_operating", "statements", True),
    "ebitdaMargins": ("margin_ebitda", "statements", True),
    "returnOnEquity": ("return_on_equity", "statements", True),
    "returnOnAssets": ("return_on_assets", "statements", True),
    # growth --------------------------------------------------------------
    "revenueGrowth": ("growth_revenue", "statements", True),
    "earningsGrowth": ("growth_earnings", "statements", True),
    "earningsQuarterlyGrowth": ("growth_earnings_q", "statements", True),
    # balance-sheet health ------------------------------------------------
    "totalCash": ("total_cash", "statements", False),
    "totalDebt": ("total_debt", "statements", False),
    "debtToEquity": ("debt_to_equity", "statements", True),
    "currentRatio": ("current_ratio", "statements", True),
    "quickRatio": ("quick_ratio", "statements", True),
    "freeCashflow": ("free_cash_flow", "statements", True),
    "operatingCashflow": ("operating_cash_flow", "statements", False),
    "totalRevenue": ("revenue_ttm", "statements", False),
    "ebitda": ("ebitda", "statements", True),
    "trailingEps": ("eps_trailing", "statements", False),
    "forwardEps": ("eps_forward", "analyst", True),
    # dividends -----------------------------------------------------------
    "dividendRate": ("dividend_rate", "actions", False),
    "dividendYield": ("dividend_yield", "actions", True),
    "payoutRatio": ("payout_ratio", "actions", True),
    "exDividendDate": ("ex_dividend_date", "actions", False),
    "dividendDate": ("dividend_date", "actions", False),
    # Units differ by key, observed on NTAP 2026-09-13: `dividendYield` and
    # `fiveYearAvgDividendYield` arrive in percent (1.04), the trailing one as a
    # fraction (0.0113). Stored as sent; `describe` normalises for display.
    "trailingAnnualDividendYield": ("dividend_yield_trailing", "actions", True),
    "fiveYearAvgDividendYield": ("dividend_yield_5y", "actions", True),
    # analyst -------------------------------------------------------------
    "targetMeanPrice": ("target_mean", "analyst", False),
    "targetHighPrice": ("target_high", "analyst", False),
    "targetLowPrice": ("target_low", "analyst", False),
    "recommendationKey": ("recommendation", "analyst", False),
    "recommendationMean": ("recommendation_score", "analyst", True),
    "numberOfAnalystOpinions": ("analyst_count", "analyst", False),
    # ownership and positioning -------------------------------------------
    "heldPercentInsiders": ("held_insiders", "ownership", False),
    "heldPercentInstitutions": ("held_institutions", "ownership", False),
    "shortRatio": ("short_ratio", "ownership", False),
    "shortPercentOfFloat": ("short_percent_float", "ownership", False),
    "sharesShort": ("shares_short", "ownership", False),
    "dateShortInterest": ("short_interest_date", "ownership", False),
}

#: yfinance's statement row labels -> our concept names. yfinance uses Title
#: Case with spaces and the exact wording drifts between releases, so this is
#: matched case-insensitively and a miss is recorded rather than fatal.
STATEMENT_CONCEPTS = {
    "total revenue": "revenue",
    "cost of revenue": "cost_of_revenue",
    "gross profit": "gross_profit",
    "operating income": "operating_income",
    "operating expense": "operating_expense",
    "net income": "net_income",
    "basic eps": "eps_basic",
    "diluted eps": "eps_diluted",
    "ebitda": "ebitda",
    "research and development": "research_development",
    "total assets": "total_assets",
    "total liabilities net minority interest": "total_liabilities",
    "stockholders equity": "stockholders_equity",
    "cash and cash equivalents": "cash",
    "total debt": "total_debt",
    "operating cash flow": "operating_cash_flow",
    "free cash flow": "free_cash_flow",
    "capital expenditure": "capital_expenditure",
}


@dataclass
class YFinanceProvider:
    """Everything yfinance knows about a company, in one pass.

    Tier 3. Free public data per [[Market Data Sources]], and honest about it.
    """

    name: str = "yfinance"
    tier: int = 3
    max_retries: int = 3
    backoff: float = 2.0
    #: Sections to pull. Narrowing this is how a caller asks for a cheap
    #: partial profile without a second code path.
    sections: tuple[str, ...] = (
        "info", "statements", "analyst", "ownership", "actions", "calendar",
        "filings", "news",
    )
    requests: int = field(default=0, init=False)

    @property
    def available(self) -> bool:
        try:
            import yfinance  # noqa: F401
        except ImportError:
            return False
        return True

    # -- the one entry point -----------------------------------------------

    def fetch(self, symbol: str) -> CompanyProfile:
        """Build a profile. One Ticker, every section, guards throughout."""
        try:
            import yfinance as yf
        except ImportError as exc:
            raise DegradedError(
                "the `yfinance` package is not installed; "
                "`uv pip install yfinance`"
            ) from exc

        vendor_symbol = to_yahoo(symbol)
        # ONE Ticker for the whole fetch: yfinance memoises on the object, so
        # every section after the first is effectively free. A Ticker per
        # section would turn one request into a dozen.
        ticker = yf.Ticker(vendor_symbol)
        self.requests += 1

        info = self._retry(lambda: ticker.info) or {}
        # Hazard 1. This must come before anything else reads `info`, because
        # every later guard assumes the symbol is real.
        if not is_populated_identity(info):
            raise UnknownSymbol(
                f"{symbol}: no company found. yfinance answered, but with no "
                f"identity fields -- which is what it returns for a symbol "
                f"that does not exist.",
                spoken_summary=f"I couldn't find a company called {symbol}.",
            )

        profile = CompanyProfile(symbol=symbol)
        now = datetime.now(UTC)

        runners: dict[str, Callable[[], None]] = {
            "info": lambda: self._apply_info(profile, info, now),
            "statements": lambda: self._apply_statements(profile, ticker, now),
            "analyst": lambda: self._apply_analyst(profile, ticker, now),
            "ownership": lambda: self._apply_ownership(profile, ticker, now),
            "actions": lambda: self._apply_actions(profile, ticker, now),
            "calendar": lambda: self._apply_calendar(profile, ticker, now),
            "filings": lambda: self._apply_filings(profile, ticker, now),
            "news": lambda: self._apply_news(profile, ticker, now),
        }
        def run(section: str) -> None:
            try:
                runners[section]()
            except Exception as exc:  # noqa: BLE001
                # Hazard 2: yfinance fails per endpoint, often silently. One
                # dead section must not lose the other seven -- but it must
                # also not vanish, or a missing section reads like a company
                # with no institutional holders rather than a failed fetch.
                profile.missing.append((section, f"{type(exc).__name__}: {exc}"))
                log.debug("yfinance section %s failed for %s: %s", section, symbol, exc)

        wanted = [s for s in self.sections if s in runners]
        # `info` first: `statements` reads the currency it sets. The rest are
        # one HTTP round trip each and share nothing, so they run together --
        # sequentially they were ~4.5s of a cold `CO` load, in parallel ~2s.
        # Every section writes its own keys; dict sets and list appends are
        # atomic under the GIL.
        if "info" in wanted:
            run("info")
        rest = [s for s in wanted if s != "info"]
        with ThreadPoolExecutor(max_workers=max(1, len(rest))) as pool:
            list(pool.map(run, rest))

        return profile

    # -- sections ----------------------------------------------------------

    def _apply_info(
        self, profile: CompanyProfile, info: dict[str, Any], now: datetime
    ) -> None:
        for raw_key, (name, group, derived) in INFO_FIELDS.items():
            value = info.get(raw_key)
            if value in (None, "", "N/A"):
                continue
            profile.set(
                name,
                Sourced(
                    value=self._coerce(name, value),
                    source=self.name,
                    tier=self.tier,
                    as_of=now,
                    group=group,
                    derived=derived,
                ),
            )
        # Officers are a list, so the scalar long tail below would drop them.
        officers = info.get("companyOfficers") or []
        ceo = next((o for o in officers if "CEO" in str(o.get("title", ""))), None)
        if ceo and ceo.get("name"):
            profile.set(
                "ceo",
                Sourced(" ".join(str(ceo["name"]).split()), self.name, self.tier, now, "identity"),
            )
        # The long tail, kept reachable but namespaced so nothing downstream
        # depends on a vendor key by accident.
        named = {k for k in INFO_FIELDS}
        for key, value in info.items():
            if key in named or value in (None, "", "N/A"):
                continue
            if isinstance(value, (str, int, float, bool)):
                profile.set(
                    f"raw:{key}",
                    Sourced(value, self.name, self.tier, now, "identity", True),
                )

    def _apply_statements(
        self, profile: CompanyProfile, ticker: Any, now: datetime
    ) -> None:
        """Income, balance and cash flow, annual and quarterly.

        Every line lands with ``filed_date=None``, and that is correct rather
        than lazy: yfinance genuinely does not report when a statement became
        public, only the period it covers. The EDGAR provider fills the dates
        in afterwards. Until it does, ``StatementLine.known_by`` returns False
        for every row -- fail closed, so a backtest gets nothing rather than
        getting lookahead.
        """
        currency = profile.get("financial_currency") or profile.get("currency") or "USD"
        frames = {
            ("income", "annual"): "income_stmt",
            ("income", "quarterly"): "quarterly_income_stmt",
            ("income", "ttm"): "ttm_income_stmt",
            ("balance", "annual"): "balance_sheet",
            ("balance", "quarterly"): "quarterly_balance_sheet",
            ("cash_flow", "annual"): "cash_flow",
            ("cash_flow", "quarterly"): "quarterly_cash_flow",
        }
        for (statement, frequency), attribute in frames.items():
            frame = self._retry(lambda a=attribute: getattr(ticker, a, None))
            if frame is None or getattr(frame, "empty", True):
                continue
            lines: list[StatementLine] = []
            for label, row in frame.iterrows():
                concept = STATEMENT_CONCEPTS.get(str(label).strip().lower())
                if concept is None:
                    continue
                for column, value in row.items():
                    amount = self._decimal(value)
                    if amount is None:
                        continue
                    lines.append(
                        StatementLine(
                            concept=concept,
                            value=amount,
                            fiscal_period_end=self._as_date(column),
                            # Hazard 2: yfinance has no filed date. EDGAR
                            # supplies it; until then this row is invisible to
                            # any as-of query, which is the safe default.
                            filed_date=None,
                            period_type="instant" if statement == "balance" else "duration",
                            frequency=frequency,
                            currency=str(currency),
                            source=self.name,
                        )
                    )
            if lines:
                profile.statements[(statement, frequency)] = FinancialStatement(
                    statement=statement,  # type: ignore[arg-type]
                    frequency=frequency,
                    lines=tuple(lines),
                    source=self.name,
                    as_of=now,
                )

    def _apply_analyst(
        self, profile: CompanyProfile, ticker: Any, now: datetime
    ) -> None:
        """Targets, estimates, revisions and the upgrade record.

        yfinance is the *only* free source for most of this -- it is not in a
        filing and EDGAR will never have it. Tier 3 and derived: these are
        opinions, and an opinion stored as a fact is how a survey becomes a
        forecast somewhere downstream.
        """
        for attribute, key in (
            ("analyst_price_targets", "analyst_targets"),
            ("earnings_estimate", "earnings_estimate"),
            ("revenue_estimate", "revenue_estimate"),
            ("eps_trend", "eps_trend"),
            ("eps_revisions", "eps_revisions"),
            ("growth_estimates", "growth_estimates"),
            ("recommendations_summary", "recommendations"),
        ):
            value = self._retry(lambda a=attribute: getattr(ticker, a, None))
            payload = self._records(value)
            if payload:
                profile.set(
                    key,
                    Sourced(payload, self.name, self.tier, now, "analyst", True),
                )
        upgrades = self._retry(lambda: getattr(ticker, "upgrades_downgrades", None))
        records = self._records(upgrades, limit=25)
        if records:
            profile.set(
                "upgrades_downgrades",
                Sourced(records, self.name, self.tier, now, "analyst", False),
            )

    def _apply_ownership(
        self, profile: CompanyProfile, ticker: Any, now: datetime
    ) -> None:
        for attribute, key in (
            ("major_holders", "major_holders"),
            ("institutional_holders", "institutional_holders"),
            ("mutualfund_holders", "mutualfund_holders"),
            ("insider_roster_holders", "insider_roster"),
            ("insider_transactions", "insider_transactions"),
            ("insider_purchases", "insider_purchases"),
        ):
            value = self._retry(lambda a=attribute: getattr(ticker, a, None))
            records = self._records(value, limit=25)
            if records:
                profile.set(
                    key, Sourced(records, self.name, self.tier, now, "ownership", False)
                )

    def _apply_actions(
        self, profile: CompanyProfile, ticker: Any, now: datetime
    ) -> None:
        for attribute, key in (("dividends", "dividends"), ("splits", "splits")):
            series = self._retry(lambda a=attribute: getattr(ticker, a, None))
            if series is None or getattr(series, "empty", True):
                continue
            records = [
                {"date": self._as_date(idx).isoformat(), "value": str(self._decimal(v))}
                for idx, v in list(series.items())[-25:]
            ]
            profile.set(
                key, Sourced(records, self.name, self.tier, now, "actions", False)
            )

    def _apply_calendar(
        self, profile: CompanyProfile, ticker: Any, now: datetime
    ) -> None:
        calendar = self._retry(lambda: getattr(ticker, "calendar", None))
        if isinstance(calendar, dict) and calendar:
            profile.set(
                "calendar",
                Sourced(
                    {k: str(v) for k, v in calendar.items()},
                    self.name, self.tier, now, "analyst", False,
                ),
            )
        dates = self._retry(lambda: getattr(ticker, "earnings_dates", None))
        records = self._records(dates, limit=8)
        if records:
            profile.set(
                "earnings_dates",
                Sourced(records, self.name, self.tier, now, "analyst", False),
            )

    def _apply_filings(
        self, profile: CompanyProfile, ticker: Any, now: datetime
    ) -> None:
        filings = self._retry(lambda: getattr(ticker, "sec_filings", None))
        records = self._records(filings, limit=20)
        if records:
            profile.set(
                "filings", Sourced(records, self.name, self.tier, now, "filings", False)
            )

    def _apply_news(self, profile: CompanyProfile, ticker: Any, now: datetime) -> None:
        """Headlines as METADATA, never as fact.

        [[Market Data Sources]] tier 4: news is untrusted text. What is stored
        is that an article exists, its title, publisher and time -- structured
        facts about a document. The document's *claims* are never stored and
        never treated as data; that is [[Agent — News And Catalyst]]'s problem
        and it fences them per [[MCP Gateway]].
        """
        news = self._retry(lambda: getattr(ticker, "news", None))
        if not isinstance(news, Iterable):
            return
        items = []
        for entry in list(news)[:15]:
            content = entry.get("content", entry) if isinstance(entry, dict) else {}
            title = content.get("title") or entry.get("title")
            if not title:
                continue
            items.append(
                {
                    "title": str(title),
                    "publisher": str(
                        (content.get("provider") or {}).get("displayName")
                        or entry.get("publisher")
                        or "unknown"
                    ),
                    "published": str(
                        content.get("pubDate") or entry.get("providerPublishTime") or ""
                    ),
                    "link": str(
                        (content.get("canonicalUrl") or {}).get("url")
                        or entry.get("link")
                        or ""
                    ),
                }
            )
        if items:
            profile.set(
                "news",
                # Tier 4, explicitly, and the only tier-4 field in the profile.
                Sourced(items, self.name, 4, now, "identity", False),
            )

    # -- plumbing ----------------------------------------------------------

    def _retry(self, call: Callable[[], Any]) -> Any:
        """Back off on rate limiting only; everything else propagates.

        The distinction is the point, and it comes from
        ``TradingAgents/.../stockstats_utils.py``: retrying a rate limit works,
        and retrying a 404 is just a slower 404. Collapsing the two turns a
        missing symbol into thirty seconds of pointless waiting.
        """
        delay = self.backoff
        for attempt in range(self.max_retries):
            try:
                return call()
            except Exception as exc:  # noqa: BLE001
                text = str(exc).lower()
                rate_limited = (
                    "rate" in text
                    or "too many" in text
                    or type(exc).__name__ == "YFRateLimitError"
                )
                if not rate_limited or attempt == self.max_retries - 1:
                    if rate_limited:
                        raise TransientError(
                            f"yfinance rate limited after {self.max_retries} "
                            f"attempts: {exc}"
                        ) from exc
                    raise
                time.sleep(delay)
                delay *= 2
        return None

    def _coerce(self, name: str, value: Any) -> Any:
        """Numbers to Decimal, epochs to dates, everything else through.

        Money is Decimal per Conventions.md, and via ``str`` so float noise
        never enters -- the same rule and the same reason as
        :mod:`genesis.marketdata.normalize`.
        """
        if name.endswith("_date") and isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=UTC).date()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value
        return self._decimal(value)

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            out = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        # NaN is how pandas spells "absent". Storing it would put a value that
        # compares false to itself into a field something will later format.
        return out if out.is_finite() else None

    @staticmethod
    def _as_date(value: Any) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if hasattr(value, "to_pydatetime"):
            return value.to_pydatetime().date()
        return datetime.fromisoformat(str(value)[:10]).date()

    @staticmethod
    def _records(frame: Any, *, limit: int = 12) -> list[dict[str, Any]] | None:
        """A DataFrame as plain JSON-able rows, truncated.

        Truncated because these feed an LLM's context eventually, and
        ``upgrades_downgrades`` alone returned 985 rows for NVDA. The whole
        history is in the store if anything wants it; what travels is a
        summary, per Orchestrator Tools' *ids and summaries, never rows*.
        """
        if frame is None or getattr(frame, "empty", True):
            return None
        try:
            trimmed = frame.head(limit)
            out = []
            for index, row in trimmed.iterrows():
                record = {"_index": str(index)}
                for column, value in row.items():
                    record[str(column)] = None if value is None else str(value)
                out.append(record)
            return out
        except Exception:  # noqa: BLE001
            return None
