# Spec: Genesis Markdown/10-Architecture/Company Data Model.md
"""SEC EDGAR. The filing itself, and the only source of a filed date.

Two jobs, and the second is the one that makes this module non-optional.

**Authoritative financials.** ``companyfacts`` returns every XBRL fact every US
issuer has ever reported, as filed, free, no key. Commercial fundamentals APIs
resell this. When it disagrees with yfinance, it wins -- not because it is more
accurate in some general sense, but because it *is* the filing and yfinance is
a summary of one.

**The filed date.** This is hazard 2 from the note, and it cannot be solved
anywhere else. yfinance keys financials by fiscal period end alone, so NVDA's
quarter ending 2026-04-30 appears under that date -- weeks before the 10-Q was
public. Any as-of query joining on it looks ahead. EDGAR reports ``filed`` on
every fact, so this provider is what lets
:meth:`~genesis.company.schema.StatementLine.known_by` ever return True.

A backtest without EDGAR does not get slightly worse data. It gets *no*
statement data, by design -- :class:`StatementLine` fails closed when the filed
date is unknown, per [[Safety Invariants]] §3.

## The User-Agent is not optional

SEC blocks anonymous clients with a ``403`` that reads like an outage. Their
fair-access policy requires a real contact string:

    SEC_EDGAR_USER_AGENT="Your Name your@email.com"

Already in ``SECRET_ENV_VARS`` -- not a credential, but this is the one channel
the config layer reads environment from. Without it this provider reports
itself unavailable rather than hammering the SEC and getting the host banned.

Endpoint and header shape adapted from
``machine-learning-for-trading/data/equities/fundamentals/xbrl_download.py``,
which is also where the fiscal-period-versus-filed-date keying comes from.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from genesis.company.schema import (
    CompanyProfile,
    FinancialStatement,
    Sourced,
    StatementLine,
)
from genesis.company.symbols import UnknownSymbol, normalise
from genesis.errors import DegradedError, TransientError

__all__ = ["CONCEPTS", "EdgarProvider"]

log = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

#: US-GAAP XBRL concept -> our name, in preference order.
#:
#: All tags are read, not just the first present -- see `_statement_lines`. An
#: issuer can change tags mid-life (NVDA moved off
#: `RevenueFromContractWithCustomerExcludingAssessedTax` after FY2022), so
#: first-tag-wins yields revenue that silently stops years ago. The ordering
#: here breaks ties for the same period, nothing more.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "cost_of_revenue": ("CostOfRevenue", "CostOfGoodsAndServicesSold"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "eps_basic": ("EarningsPerShareBasic",),
    "eps_diluted": ("EarningsPerShareDiluted",),
    "research_development": ("ResearchAndDevelopmentExpense",),
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "stockholders_equity": ("StockholdersEquity",),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
    ),
    "capital_expenditure": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "shares_outstanding": ("CommonStockSharesOutstanding", "dei:EntityCommonStockSharesOutstanding"),
}

#: Concepts XBRL reports as a POSITIVE payment where the cash flow statement
#: convention is a negative outflow. EDGAR's
#: `PaymentsToAcquirePropertyPlantAndEquipment` is +10.96B for AAPL FY2023;
#: yfinance reports -10.96B. Same fact, opposite sign.
#:
#: Left alone, the reconciler flags these as "200% apart" -- a false positive
#: on every filer with capex, which is every filer. A reconciler that cries
#: wolf is worse than none, because it trains everyone to skip the warnings
#: that matter. So the sign is normalised to the cash flow convention
#: (outflows negative) at ingestion, and the comparison then works.
_OUTFLOW_CONCEPTS = frozenset({"capital_expenditure"})

#: Which statement each concept belongs to, and whether it is a point-in-time
#: balance or a figure covering a period. Getting this wrong sums a quarterly
#: revenue with a period-end cash balance.
_STATEMENT_OF = {
    "revenue": ("income", "duration"),
    "cost_of_revenue": ("income", "duration"),
    "gross_profit": ("income", "duration"),
    "operating_income": ("income", "duration"),
    "net_income": ("income", "duration"),
    "eps_basic": ("income", "duration"),
    "eps_diluted": ("income", "duration"),
    "research_development": ("income", "duration"),
    "total_assets": ("balance", "instant"),
    "total_liabilities": ("balance", "instant"),
    "stockholders_equity": ("balance", "instant"),
    "cash": ("balance", "instant"),
    "shares_outstanding": ("balance", "instant"),
    "operating_cash_flow": ("cash_flow", "duration"),
    "capital_expenditure": ("cash_flow", "duration"),
}


@dataclass
class EdgarProvider:
    """As-filed financials and filing metadata.

    Tier 3, "but uniquely so" in [[Market Data Catalog]]'s phrase: free public
    data by the same classification as yfinance, yet it is the primary document
    rather than a summary of one. The tier ranks *authority to move money*, and
    nothing free is tier 1 -- but within tier 3 this is the source that wins a
    disagreement.
    """

    name: str = "edgar"
    tier: int = 3
    user_agent: str | None = None
    #: SEC asks for no more than ~10 requests/second. This provider makes three
    #: per company, so the gap is politeness rather than a real constraint --
    #: and getting the host IP banned would be an expensive way to save 300ms.
    min_interval: float = 0.15
    timeout: float = 20.0
    #: The ticker->CIK map is 10k+ entries and changes rarely. Cached on disk
    #: because re-downloading it per lookup would be the single most wasteful
    #: thing this module could do.
    cache_dir: Path = field(default_factory=lambda: Path("~/.genesis/market/edgar"))
    _last_call: float = field(default=0.0, init=False, repr=False)
    _cik_map: dict[str, int] | None = field(default=None, init=False, repr=False)
    requests: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.user_agent is None:
            self.user_agent = os.environ.get("SEC_EDGAR_USER_AGENT")
        self.cache_dir = Path(self.cache_dir).expanduser()

    @property
    def available(self) -> bool:
        """Requires a contact User-Agent. SEC 403s anonymous clients."""
        return bool(self.user_agent and "@" in str(self.user_agent))

    # -- entry point -------------------------------------------------------

    def enrich(self, profile: CompanyProfile) -> CompanyProfile:
        """Add as-filed statements and filed dates to an existing profile.

        Deliberately *enriches* rather than building a profile from scratch.
        EDGAR has no sector, no market cap, no analyst view -- a profile built
        from it alone would be a set of financial statements with no company
        attached. yfinance establishes what the company is; this establishes
        what it reported and when.
        """
        if not self.available:
            profile.missing.append(
                (
                    "edgar",
                    "SEC_EDGAR_USER_AGENT is not set (needs a contact string "
                    "like 'Name email@example.com'); see .env.example",
                )
            )
            return profile

        try:
            cik = self.cik_for(profile.symbol)
        except (UnknownSymbol, DegradedError) as exc:
            # Not every symbol is a US issuer. An ADR, an ETF or a foreign
            # listing legitimately has no CIK, and that is a fact rather than
            # a failure -- but it must be recorded, or the absence of
            # statements looks like a company that files nothing.
            profile.missing.append(("edgar", str(exc)))
            return profile

        now = datetime.now(UTC)
        profile.set("cik", Sourced(cik, self.name, self.tier, now, "identity", False))

        try:
            facts = self._get(_FACTS_URL.format(cik=cik))
        except TransientError as exc:
            profile.missing.append(("edgar", str(exc)))
            return profile

        entity = facts.get("entityName")
        if entity:
            profile.set(
                "edgar_name",
                Sourced(str(entity), self.name, self.tier, now, "identity", False),
            )

        lines = self._statement_lines(facts)
        if not lines:
            profile.missing.append(("edgar", "companyfacts held no mapped concepts"))
            return profile

        # Reconcile BEFORE merging: the comparison needs yfinance's statements,
        # and `_merge_statements` replaces them.
        self._reconcile(profile, lines)
        self._merge_statements(profile, lines, now)
        return profile

    # -- CIK ---------------------------------------------------------------

    def cik_for(self, symbol: str) -> int:
        """Ticker -> CIK, via SEC's own mapping file. Cached on disk."""
        ticker = normalise(symbol)
        if self._cik_map is None:
            self._cik_map = self._load_cik_map()
        # SEC spells class shares with a dash (BRK-B), the exchange with a dot
        # (BRK.B). Trying only the canonical form reports Berkshire as "not a
        # US filer", which is both false and confidently stated.
        cik = self._cik_map.get(ticker) or self._cik_map.get(ticker.replace(".", "-"))
        if cik is None:
            raise UnknownSymbol(
                f"{symbol} has no SEC CIK -- not a US filer (an ADR, an ETF, "
                f"or a foreign listing). yfinance data stands alone for it."
            )
        return cik

    def _load_cik_map(self) -> dict[str, int]:
        cache = self.cache_dir / "company_tickers.json"
        if cache.exists():
            age = time.time() - cache.stat().st_mtime
            if age < 30 * 86_400:  # identity group TTL
                try:
                    return {
                        k: int(v) for k, v in json.loads(cache.read_text()).items()
                    }
                except (json.JSONDecodeError, ValueError):
                    log.debug("edgar cik cache unreadable; refetching")

        payload = self._get(_TICKERS_URL)
        mapping = {
            str(row["ticker"]).upper(): int(row["cik_str"])
            for row in payload.values()
            if row.get("ticker") and row.get("cik_str") is not None
        }
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(mapping))
        return mapping

    # -- facts -------------------------------------------------------------

    def _statement_lines(self, facts: dict[str, Any]) -> list[StatementLine]:
        """XBRL companyfacts -> our statement lines, with filed dates.

        The structure is ``facts[taxonomy][concept]["units"][unit][...]``, and
        each entry carries ``end`` (period), ``filed`` (when it became public),
        ``fp``/``form``, and ``val``. Those two dates being separate fields is
        the entire reason this provider exists.
        """
        taxonomies = facts.get("facts", {})
        #: (concept, period end, frequency) -> line. Keyed so that the same
        #: economic figure reported under two tags collapses to one row.
        merged: dict[tuple[str, date, str], tuple[int, StatementLine]] = {}

        for name, tags in CONCEPTS.items():
            statement, period_type = _STATEMENT_OF.get(name, ("income", "duration"))
            # EVERY tag, not the first one that exists.
            #
            # An issuer can change tags mid-life: NVDA reported revenue as
            # `RevenueFromContractWithCustomerExcludingAssessedTax` through
            # FY2022 and as `Revenues` after. Taking the first tag present and
            # stopping -- which is what a "preferred tag" reading of CONCEPTS
            # suggests -- yields a company whose revenue silently stops four
            # years ago while every other field is current. Nothing raises.
            #
            # So all tags are read and merged on (concept, period, frequency).
            # Preference still applies, but only to break a genuine tie: where
            # two tags report the SAME period, the earlier-listed tag wins.
            for rank, tag in enumerate(tags):
                taxonomy = "dei" if tag.startswith("dei:") else "us-gaap"
                key = tag.split(":", 1)[-1]
                node = taxonomies.get(taxonomy, {}).get(key)
                if not node:
                    continue
                for unit, entries in node.get("units", {}).items():
                    currency = unit if unit.isalpha() and len(unit) == 3 else "USD"
                    for entry in entries:
                        line = self._line(
                            name, entry, statement, period_type, currency
                        )
                        if line is None:
                            continue
                        slot = (name, line.fiscal_period_end, line.frequency)
                        held = merged.get(slot)
                        if held is None or self._prefer(rank, line, held):
                            merged[slot] = (rank, line)
        return [line for _, line in merged.values()]

    @staticmethod
    def _prefer(
        rank: int, candidate: StatementLine, held: tuple[int, StatementLine]
    ) -> bool:
        """Should ``candidate`` displace the line already held for this slot?

        **The EARLIEST filing wins**, and that is the opposite of what a first
        instinct suggests -- so it is worth saying why.

        A 10-K restates the prior two years as comparatives. So FY2023 revenue
        appears in the FY2023 filing (filed 2023-02) and again in the FY2024,
        FY2025 and FY2026 filings. Preferring the latest filing tags every
        historical period with a 2026 filed date, and then
        ``known_by(2024-01-01)`` says the FY2023 figure was not yet public --
        which is false, and it silently truncates every as-of query to almost
        nothing. Observed: an as-of query for 2024-01-01 returned FY2021.

        ``filed_date`` answers *"when did this become public"*, and the honest
        answer is the first time it was filed. Restatements are a real and
        separate concern -- the amended value differs from the original -- but
        they are rare, and getting the availability date wrong breaks every
        query while a stale restatement breaks a few. See Open Questions §15.

        Failing a date comparison, the **preferred tag wins**, which is all
        CONCEPTS' ordering is for.
        """
        held_rank, held_line = held
        if candidate.filed_date and held_line.filed_date:
            if candidate.filed_date != held_line.filed_date:
                return candidate.filed_date < held_line.filed_date
        return rank < held_rank

    def _line(
        self,
        concept: str,
        entry: dict[str, Any],
        statement: str,
        period_type: str,
        currency: str,
    ) -> StatementLine | None:
        value = self._decimal(entry.get("val"))
        end = self._date(entry.get("end"))
        if value is None or end is None:
            return None
        if concept in _OUTFLOW_CONCEPTS and value > 0:
            # Normalise to the cash flow convention: money leaving is negative.
            value = -value
        form = str(entry.get("form", ""))
        frequency = self._frequency(entry, form, period_type)
        if frequency is None:
            # A year-to-date cumulative figure. Dropped rather than stored.
            #
            # This is the XBRL trap that classifying by FORM alone walks into:
            # cash flow and income facts in a 10-Q are cumulative from the
            # fiscal year start, so a Q3 filing reports NINE months. Stored as
            # "quarterly" they are 2-3x the real quarter, and every margin,
            # growth rate and per-quarter comparison computed from them is
            # wrong by a factor that changes with the quarter.
            #
            # Observed on BRK.B: EDGAR operating cash flow 21.6B against
            # yfinance's 11.2B for the same "quarter" -- the six-month total
            # versus the three-month one.
            return None
        return StatementLine(
            concept=concept,
            value=value,
            fiscal_period_end=end,
            # The field yfinance cannot supply, and the reason this provider
            # is required rather than optional.
            filed_date=self._date(entry.get("filed")),
            period_type=period_type,  # type: ignore[arg-type]
            frequency=frequency,
            currency=currency,
            source=self.name,
        )

    @staticmethod
    def _frequency(entry: dict[str, Any], form: str, period_type: str) -> str | None:
        """Annual, quarterly, or None for a year-to-date cumulative figure.

        Classified by the fact's ACTUAL duration rather than by the form it
        appeared in, because a 10-Q carries both: a three-month income figure
        and a nine-month cumulative one, under the same tag, in the same
        filing. Only ``start`` tells them apart.

        Instant facts (balance sheet) have no duration and take the form's
        word for it -- a balance is a balance whenever it was measured.
        """
        if period_type == "instant":
            return "annual" if form.startswith("10-K") else "quarterly"

        start = entry.get("start")
        end = entry.get("end")
        if not start or not end:
            # No duration to check. Trust the form rather than discard a fact,
            # but only for 10-K, where cumulative and annual coincide.
            return "annual" if form.startswith("10-K") else None

        try:
            days = (
                datetime.fromisoformat(str(end)[:10])
                - datetime.fromisoformat(str(start)[:10])
            ).days
        except ValueError:
            return None

        # Fiscal quarters and years are ragged -- 52/53-week calendars, 13-week
        # quarters, period-end drift -- so these are ranges rather than exact
        # counts.
        if 80 <= days <= 100:
            return "quarterly"
        if 350 <= days <= 380:
            return "annual"
        # 6- and 9-month cumulatives land here, and are the reason this
        # function exists.
        return None

    def _merge_statements(
        self, profile: CompanyProfile, lines: list[StatementLine], now: datetime
    ) -> None:
        """Install EDGAR statements, replacing yfinance's for the same slot.

        EDGAR wins on statements -- it is the filing. yfinance's version is not
        discarded silently though: :meth:`_reconcile` compares them first and
        records any disagreement on the profile.
        """
        buckets: dict[tuple[str, str], list[StatementLine]] = {}
        for line in lines:
            statement, _ = _STATEMENT_OF.get(line.concept, ("income", "duration"))
            buckets.setdefault((statement, line.frequency), []).append(line)
        for (statement, frequency), rows in buckets.items():
            profile.statements[(statement, frequency)] = FinancialStatement(
                statement=statement,  # type: ignore[arg-type]
                frequency=frequency,
                lines=tuple(sorted(rows, key=lambda r: r.fiscal_period_end)),
                source=self.name,
                as_of=now,
            )

    def _reconcile(
        self, profile: CompanyProfile, lines: list[StatementLine]
    ) -> None:
        """Compare EDGAR against yfinance for the SAME period, and record gaps.

        Like-for-like is the whole difficulty. The obvious comparison --
        EDGAR's fiscal-year revenue against yfinance's ``totalRevenue`` -- is
        wrong, because ``totalRevenue`` is **trailing twelve months**. For NVDA
        in 2026 those differ by 40%, entirely legitimately, and a reconciler
        that flags it teaches everyone to ignore reconciler output.

        So this matches on ``(concept, fiscal_period_end, frequency)`` and
        compares only where both sources describe the same window. Anything
        without a counterpart is skipped rather than guessed at.

        Disagreements are recorded, never silently resolved. A gap between the
        filing and the vendor's summary is a fact about our data quality, and
        it is frequently worth more than the number -- the same argument
        [[Market Data Plane]] makes for keeping a restated bar rather than
        overwriting it.

        The tolerance is 1%. Tighter would flag rounding and tag choice as
        errors; looser would miss a genuinely wrong number.
        """
        edgar_by_slot = {
            (line.concept, line.fiscal_period_end, line.frequency): line
            for line in lines
        }
        # Grouped by concept, not listed per period. A tag-definition
        # difference -- yfinance's "cash" excluding something EDGAR's
        # `CashAndCashEquivalentsAtCarryingValue` includes -- is ONE finding
        # that recurs, not fifteen findings. Listing each period buries the
        # single 40% outlier that matters under fourteen 1.5% ones that do not,
        # which is how a warning list stops being read.
        seen: dict[str, list[tuple[Decimal, Any]]] = {}
        for (statement, frequency), reported in list(profile.statements.items()):
            if reported.source == self.name:
                continue  # already ours; nothing to compare against
            for line in reported.lines:
                slot = (line.concept, line.fiscal_period_end, line.frequency)
                theirs = edgar_by_slot.get(slot)
                if theirs is None or theirs.value == 0:
                    continue
                drift = abs(theirs.value - line.value) / abs(theirs.value)
                if drift > Decimal("0.01"):
                    seen.setdefault(line.concept, []).append(
                        (drift, line.fiscal_period_end)
                    )

        for concept, hits in sorted(seen.items()):
            worst, when = max(hits, key=lambda h: h[0])
            periods = f"{len(hits)} period{'s' if len(hits) > 1 else ''}"
            profile.conflicts.append(
                f"{concept}: edgar and yfinance disagree across {periods}, "
                f"worst {worst:.1%} at {when} — edgar wins. "
                + (
                    "Consistent and small: likely a tag-definition difference."
                    if worst < Decimal("0.05")
                    else "Large enough to investigate."
                )
            )

    # -- HTTP --------------------------------------------------------------

    def _get(self, url: str) -> dict[str, Any]:
        import httpx

        gap = time.monotonic() - self._last_call
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last_call = time.monotonic()
        self.requests += 1

        try:
            response = httpx.get(
                url,
                headers={
                    # Required. SEC 403s an anonymous client with a message
                    # that reads like an outage rather than a policy.
                    "User-Agent": str(self.user_agent),
                    "Accept-Encoding": "gzip, deflate",
                },
                timeout=self.timeout,
                follow_redirects=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise TransientError(f"EDGAR request failed: {exc}") from exc

        if response.status_code == 403:
            raise DegradedError(
                "SEC returned 403 — the User-Agent is missing or lacks a "
                "contact address. Set SEC_EDGAR_USER_AGENT='Name email@host'."
            )
        if response.status_code == 404:
            raise DegradedError(f"EDGAR has nothing at {url}")
        if response.status_code == 429:
            raise TransientError("SEC rate limited this client; back off")
        if response.status_code >= 400:
            raise TransientError(f"EDGAR returned {response.status_code}")
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise DegradedError(f"EDGAR returned non-JSON from {url}") from exc

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            out = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return out if out.is_finite() else None

    @staticmethod
    def _date(value: Any) -> date | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value)[:10]).date()
        except ValueError:
            return None
