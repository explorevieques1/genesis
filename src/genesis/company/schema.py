# Spec: Genesis Markdown/10-Architecture/Company Data Model.md
"""What Genesis knows about a company, and where each part of it came from.

The shape here follows one decision from the note, and everything else falls
out of it: **provenance is per field, not per profile.**

A :class:`CompanyProfile` is assembled from two providers and a dozen
endpoints. Some fields are as-filed truth, some are a vendor's derived ratio,
some are an analyst's opinion. Stamping the object with one source would make
the whole thing as weak as its weakest field -- and a profile whose revenue came
from a filing but whose price target came from a survey is not uniformly
trustworthy, so it must not claim to be.

The cost is that every value is a :class:`Sourced` wrapper rather than a bare
float. The benefit is that *"NVDA's PE is 51"* can always be followed by
*"...per yfinance, four minutes ago, derived"* -- which is what
[[Safety Invariants]] §10 requires of anything spoken aloud.

**Money is Decimal**, per Conventions.md §Money, and here that is not
ceremonial: a market cap is a large number and a margin is a ratio of two large
numbers, and float error compounds through exactly that arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Generic, Iterator, Literal, TypeVar

__all__ = [
    "CompanyProfile",
    "FieldGroup",
    "FinancialStatement",
    "PERIOD_TTL",
    "Sourced",
    "StatementLine",
    "StatementType",
    "TTL",
]

T = TypeVar("T")

#: Which cache bucket a field belongs to. Company data changes at wildly
#: different rates -- a sector is effectively permanent, a market cap is live --
#: and one TTL for all of it would either re-fetch identity every 15 minutes or
#: serve a day-old price. See the note's caching table.
FieldGroup = Literal[
    "identity", "statements", "ownership", "analyst", "market", "actions", "filings"
]

#: Per-group cache lifetimes. The whole reason a second `genesis company NVDA`
#: inside these windows makes no network call.
TTL: dict[str, timedelta] = {
    "identity": timedelta(days=30),
    "statements": timedelta(days=1),
    "ownership": timedelta(days=1),
    "analyst": timedelta(days=1),
    "actions": timedelta(days=1),
    "filings": timedelta(days=1),
    # The only genuinely live group, and still not real-time: nothing here
    # feeds Pre-Trade Risk Engine, which reads tier 1 and nothing else.
    "market": timedelta(minutes=15),
}

#: Fallback for a group nobody classified. Deliberately short -- an unknown
#: field is one we have not reasoned about, so it should not be cached for a
#: month on the strength of an omission.
PERIOD_TTL = timedelta(hours=1)

StatementType = Literal["income", "balance", "cash_flow"]


@dataclass(frozen=True)
class Sourced(Generic[T]):
    """One value, with everything needed to judge it later.

    ``derived`` matters more than it looks. A PE ratio from yfinance is not a
    reported figure -- it is yfinance dividing a price it holds by an EPS it
    holds, and if either input is stale or wrong the ratio is wrong in a way
    that no amount of care about *this* number would catch. Marking it lets an
    answer distinguish "the company reported this" from "a vendor computed
    this", which is the difference between a fact and an inference.
    """

    value: T
    source: str
    #: Market Data Sources' trust tier. Everything in this module is 3 -- free
    #: public data. EDGAR is also 3, but "uniquely so": it is the filing
    #: itself rather than somebody's summary of it.
    tier: int = 3
    as_of: datetime | None = None
    group: FieldGroup = "identity"
    derived: bool = False
    #: Set when a second source disagreed. Never silently resolved -- a
    #: disagreement is a fact about our data quality, and it is often worth
    #: more than the number.
    conflict: str | None = None

    def __post_init__(self) -> None:
        if self.as_of is None:
            object.__setattr__(self, "as_of", datetime.now(UTC))

    @property
    def age(self) -> timedelta:
        return datetime.now(UTC) - (self.as_of or datetime.now(UTC))

    @property
    def is_stale(self) -> bool:
        return self.age > TTL.get(self.group, PERIOD_TTL)

    def label(self) -> str:
        """How to attribute this value out loud."""
        parts = [self.source]
        if self.derived:
            parts.append("derived")
        if self.conflict:
            parts.append("DISPUTED")
        return " · ".join(parts)

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class StatementLine:
    """One reported figure, keyed so it cannot be read before it existed.

    The two dates are the whole point, and the note's hazard 2 is why:
    yfinance keys financials by ``fiscal_period_end`` alone, so a backtest that
    joins on it knows a quarter's revenue on the day the quarter closed --
    weeks before anyone did. The bug produces *better* backtest results, which
    is precisely why it never gets investigated.

    ``filed_date`` is therefore not optional metadata. It is the field that
    makes an as-of query honest, and it comes from EDGAR because yfinance does
    not have it.
    """

    concept: str
    value: Decimal
    #: The period the figure describes. NOT when it became public.
    fiscal_period_end: date
    #: When it became public. ``None`` means unknown, and an as-of query must
    #: then **exclude** the row rather than assume it was available -- fail
    #: closed, per Safety Invariants §3.
    filed_date: date | None = None
    #: An income statement covers a duration; a balance sheet is an instant.
    #: XBRL distinguishes these and so must we, or a quarterly revenue and a
    #: period-end cash balance get summed.
    period_type: Literal["duration", "instant"] = "duration"
    #: "quarterly" | "annual" | "ttm"
    frequency: str = "quarterly"
    currency: str = "USD"
    source: str = "unknown"

    def known_by(self, when: date) -> bool:
        """Was this figure public on ``when``? Unknown filing date means no."""
        return self.filed_date is not None and self.filed_date <= when


@dataclass(frozen=True)
class FinancialStatement:
    """One statement, one frequency, many periods."""

    statement: StatementType
    frequency: str
    lines: tuple[StatementLine, ...] = ()
    source: str = "unknown"
    as_of: datetime | None = None

    def periods(self) -> list[date]:
        return sorted({line.fiscal_period_end for line in self.lines}, reverse=True)

    def concept(self, name: str, *, as_of: date | None = None) -> StatementLine | None:
        """Most recent value of one concept, optionally as known on a date.

        Passing ``as_of`` filters on ``filed_date``, which is the lookahead
        guard. Omitting it returns the latest known figure, which is right for
        "tell me about NVDA" and wrong for a backtest -- so a backtest must
        pass it, and :meth:`as_known_on` makes that the easier thing to do.
        """
        candidates = [
            line
            for line in self.lines
            if line.concept == name and (as_of is None or line.known_by(as_of))
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda line: line.fiscal_period_end)

    def as_known_on(self, when: date) -> "FinancialStatement":
        """This statement, restricted to what was public on ``when``."""
        return FinancialStatement(
            statement=self.statement,
            frequency=self.frequency,
            lines=tuple(line for line in self.lines if line.known_by(when)),
            source=self.source,
            as_of=self.as_of,
        )


@dataclass
class CompanyProfile:
    """Everything Genesis knows about one issuer.

    Fields live in ``values`` rather than as attributes, deliberately. The set
    of things yfinance reports is large (189 in ``info`` alone), vendor-defined,
    and changes without notice; pinning each to a dataclass attribute would mean
    a schema migration every time Yahoo renames something, and would quietly
    drop whatever did not have a slot. A mapping keeps the long tail reachable
    while :meth:`get` and the named accessors keep the common path readable.
    """

    symbol: str
    values: dict[str, Sourced[Any]] = field(default_factory=dict)
    statements: dict[tuple[str, str], FinancialStatement] = field(default_factory=dict)
    #: Populated when providers disagreed. Surfaced, never resolved silently.
    conflicts: list[str] = field(default_factory=list)
    #: Providers that were asked and could not answer, with the reason. A
    #: profile that is thin because EDGAR was down should say so rather than
    #: look like a company with no financials.
    missing: list[tuple[str, str]] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # -- access ------------------------------------------------------------

    def set(self, key: str, sourced: Sourced[Any]) -> None:
        self.values[key] = sourced

    def get(self, key: str, default: Any = None) -> Any:
        """The bare value. For display and arithmetic."""
        entry = self.values.get(key)
        return entry.value if entry is not None else default

    def sourced(self, key: str) -> Sourced[Any] | None:
        """The value *with* its provenance. For anything that speaks."""
        return self.values.get(key)

    def group(self, name: FieldGroup) -> dict[str, Sourced[Any]]:
        return {k: v for k, v in self.values.items() if v.group == name}

    def statement(
        self, statement: StatementType, frequency: str = "quarterly"
    ) -> FinancialStatement | None:
        return self.statements.get((statement, frequency))

    # -- identity ----------------------------------------------------------

    @property
    def name(self) -> str | None:
        return self.get("long_name") or self.get("short_name")

    @property
    def is_identified(self) -> bool:
        """Does this describe a real company?

        Hazard 1 from the note, enforced. ``yf.Ticker("ZZZZNOTREAL").info``
        returns ``{"trailingPegRatio": None}`` -- truthy, length 1 -- so a
        ``if info:`` check admits a symbol that does not exist and Genesis then
        answers questions about nothing.

        A real profile has a name AND at least one independent corroborating
        fact. One field could be an echo of the query; two could not.
        """
        if not self.name:
            return False
        return any(
            self.get(k) for k in ("exchange", "sector", "industry", "market_cap", "cik")
        )

    # -- currency ----------------------------------------------------------

    @property
    def currency(self) -> str | None:
        """What prices are quoted in."""
        return self.get("currency")

    @property
    def financial_currency(self) -> str | None:
        """What the statements are reported in. Often NOT the same."""
        return self.get("financial_currency")

    @property
    def currency_mismatch(self) -> bool:
        """True for ADRs and foreign issuers: price in one currency, books in
        another. Nothing in the trading corpus guards this, and a margin
        computed across the two is a number with no meaning that looks entirely
        normal. See Open Questions §14."""
        price_ccy, book_ccy = self.currency, self.financial_currency
        return bool(price_ccy and book_ccy and price_ccy != book_ccy)

    # -- reporting ---------------------------------------------------------

    @property
    def sources(self) -> set[str]:
        return {v.source for v in self.values.values()}

    @property
    def worst_tier(self) -> int:
        """The weakest *factual* field's tier.

        Tier 4 is excluded, and the exclusion is the point rather than a
        convenience. Tier 4 is untrusted text -- headlines -- and
        [[Market Data Sources]] says it is "never stored as fact, never a
        numeric claim". Letting it set the profile's tier would mark every
        company tier 4 merely for having news attached, which inverts the
        meaning: the tier would then measure whether we fetched headlines
        rather than how much to trust the numbers.

        News is still on the profile and still labelled tier 4 on its own
        field. It just does not vote on the trustworthiness of revenue.
        """
        factual = [v.tier for v in self.values.values() if v.tier < 4]
        return max(factual, default=3)

    @property
    def has_untrusted(self) -> bool:
        """True when tier-4 text is attached. Fenced, never a numeric claim."""
        return any(v.tier >= 4 for v in self.values.values())

    def stale_fields(self) -> list[str]:
        return [k for k, v in self.values.items() if v.is_stale]

    def __iter__(self) -> Iterator[tuple[str, Sourced[Any]]]:
        return iter(self.values.items())

    def __len__(self) -> int:
        return len(self.values)
