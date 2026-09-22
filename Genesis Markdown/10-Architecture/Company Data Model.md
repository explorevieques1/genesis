---
title: Company Data Model
tags: [architecture, data, fundamentals]
status: built
implemented_by: [src/genesis/company/schema.py, src/genesis/company/symbols.py, src/genesis/company/profile.py, src/genesis/company/store.py, src/genesis/company/providers/yfinance.py, src/genesis/company/providers/edgar.py, tests/company/, src/genesis/company/__init__.py, src/genesis/company/providers/__init__.py, tests/company/__init__.py, tests/company/test_hazards.py, tests/company/test_providers.py, tests/company/test_store.py]
---

# 🏢 Company Data Model

What Genesis knows about a company when you type `NVDA`, where each field came
from, and how much of it to believe.

[[Market Data Plane]] answers *how bars enter the system*. This note answers the
other half: **everything about an issuer that is not a bar** — identity, sector,
size, valuation, financial statements, ownership, analyst views, corporate
actions, earnings dates, filings.

The bar plane and this share a spine on purpose. Same provenance columns, same
trust tiers from [[Market Data Sources]], same store, same fail-honestly rule.
A company fact and a price are different in every way except the ones that
matter here: both are things the world did, both must name their source and
age, and neither may ever be invented.

> [!important] This is afferent, and it is not real-time
> Read-only, retryable, no approval, no model in the path — same as the bar
> plane. But unlike [[Market Data Plane]]'s IBKR path, **nothing here needs to
> be fast.** A company's sector does not change intraday, and its last 10-Q
> will not be restated while you look at it. That single fact is what licenses
> the design below to be cheap, cached hard, and batch-first.

## Why yfinance is the spine, against the earlier note

[[Market Data Catalog]] §1 says yfinance is a *"gap-filler only… must never be
a scheduled dependency"*, and §12 names SEC EDGAR XBRL `companyfacts` as the
primary fundamentals source. That was right for **bars and as-filed financials**
and it stays right for those. It was too narrow for the question this note
answers.

**Decision (2026-09-04): yfinance is primary for breadth; EDGAR is
authoritative for the numbers it has.** Both, not either.

The reason is coverage, and it is not close. One `yfinance.Ticker` gives
**189 `info` fields and 35 working endpoints** — sector, market cap, float,
short interest, institutional and insider ownership, analyst targets and
revisions, upgrade history, earnings dates, option expiries. EDGAR has none of
that, because none of it is in a filing. EDGAR has the statements, as filed,
which is the one thing yfinance only has second-hand.

So the split is by *what each source actually is*:

| Field group | Source | Why |
|---|---|---|
| Identity, sector, industry, exchange, ISIN | yfinance | Not in a filing |
| Price, market cap, float, 52w range, beta | yfinance | Market data, not filed |
| Valuation multiples, margins, growth ratios | yfinance | Derived; recomputable from EDGAR |
| Analyst targets, recommendations, revisions | yfinance | **Only source** |
| Ownership — institutional, insider, short interest | yfinance | Aggregated from 13F/Form 4 |
| Dividends, splits, capital gains | yfinance | Corroborated by EDGAR |
| **Income statement, balance sheet, cash flow** | **EDGAR, verified against yfinance** | It is the filing itself |
| Filing index and metadata | EDGAR | Primary by mandate |

**When the two disagree, EDGAR wins and the delta is recorded** — never silently
resolved. A disagreement on revenue is a fact about our data quality and it is
worth more than the number itself. Same rule as a restated bar in
[[Market Data Plane]]: the history changed, and it changed loudly.

`Market Data Catalog` §1's warning is not repealed. It is scoped: yfinance must
never be a scheduled dependency **for bars**, where a broker feed exists and the
number moves money. For company reference data there is no better free source,
the data is not time-critical, and the mitigation is caching plus the guards
below rather than abstinence.

## Two hazards, both verified, both non-obvious

These are the reason this note exists rather than a docstring.

### 1. A non-existent ticker returns a truthy dict

Measured 2026-09-04:

```python
yf.Ticker("ZZZZNOTREAL").info   # -> {"trailingPegRatio": None}
                                #    bool() is True. len() is 1.
```

A reasonable `if info:` treats a symbol that does not exist as a valid company.
Genesis would then answer questions about it — confidently, at length, and
about nothing. That is a [[Safety Invariants]] §10 confabulation arriving
through a truthiness check.

**Rule: never trust a non-empty response. Check for populated identity fields.**
A profile without a `symbol`, a name, and at least one of exchange or sector is
not a thin profile — it is not a company, and the answer is a typed failure.

Pattern adapted from `TradingAgents/tradingagents/dataflows/symbol_utils.py`,
which hit the same wall and answered it with a `NoMarketDataError` taxonomy
rather than a truthiness test.

### 2. Financial statements are keyed by fiscal period, not filed date

Measured 2026-09-04 — `NVDA.quarterly_income_stmt` columns:

```
2026-04-30   2026-01-31   2025-10-31   2025-07-31   2025-04-30
```

Those are **fiscal period ends**. The quarter ending 2026-04-30 was not public
on 2026-04-30; it was filed weeks later. Any backtest that joins on the column
date knows the quarter's revenue before anyone did — a lookahead bug that
produces *better* results and therefore never gets investigated.

**Rule: every statement row carries both `fiscal_period_end` and `filed_date`,
and any as-of query filters on `filed_date`.** yfinance does not supply the
filed date, so it comes from EDGAR — which is a second, independent reason
EDGAR is in this design rather than optional.

Keying adapted from
`machine-learning-for-trading/data/equities/fundamentals/xbrl_download.py`,
which separates XBRL instant vs duration periods from the Submissions API's
filing dates and joins them deliberately.

### 3. Currency is silently mixed — an open gap

yfinance's `info` carries both `currency` and `financialCurrency`, and for ADRs
and foreign issuers **they differ**: price in USD, statements in the home
currency. Nothing in the trading corpus guards this. A margin computed across
the two is a number with no meaning, and it looks completely normal.

Genesis stores both and **refuses to compute a cross-currency ratio** rather
than converting with a rate it does not have. See [[Open Questions]] §14.

## Nobody knows the ticker

`symbols.py` `normalise()` takes a symbol and validates it. That is the wrong
front door for the system described in [[Operating Model]] §7: traders speak in
**names**, and *"why is Nvidia down today?"* dies at the first hop today because
`NVIDIA` is not a valid symbol.

**Resolution belongs here**, in front of `normalise`, and it is a reflex rather
than judgement ([[Biological Design]]):

- **A lookup against a real source**, not a model call. EDGAR's
  `company_tickers.json` already maps name → ticker → CIK, and EDGAR is already
  a provider in this module for the filed dates. Asking a language model *"what
  is Nvidia's ticker"* is the wrong tier and will one day answer `NVDIA` with
  complete confidence and no way to tell.
- **Ambiguity is surfaced, never resolved.** Multiple matches ask; zero matches
  say so. A silently wrong ticker produces a chart of a different company that
  looks entirely normal — the same failure class as [[Market Data Sources]]'
  stale quote, and equally quiet.
- **What was resolved is returned and displayed** — `NVDA — NVIDIA Corp` — so a
  mis-resolution costs one glance rather than one trade.
- **Classify before looking up.** *"Gann"* is a research subject, *"semis"* a
  sector, *"my worst week"* a journal query. "This is not a symbol" is a common
  and valid answer, and a resolver that always returns a ticker is a resolver
  that invents one.

Caller: [[Orchestrator]] §entity resolution. Not built.

## The shape

```
   genesis company NVDA
            │
            ▼
   symbols.py ──── normalise + validate. A ticker that fails the
            │      populated-identity check stops here.
            ▼
   ┌─────────────── PROVIDERS (afferent, chain-ordered) ────────────┐
   │  yfinance.py            edgar.py                               │
   │  ├─ profile             ├─ companyfacts   (as-filed, XBRL)     │
   │  ├─ statements          ├─ submissions    (filed dates, CIK)   │
   │  ├─ analyst             └─ User-Agent REQUIRED — SEC 403s      │
   │  ├─ ownership              an anonymous client                 │
   │  ├─ actions                                                    │
   │  └─ retry + staleness + emptiness guards at the boundary       │
   └────────────────────────────┬───────────────────────────────────┘
                                ▼
   profile.py ──── assemble. Per-FIELD provenance, not per-object.
            │      EDGAR wins on statements; deltas recorded.
            ▼
   store.py ─────── DuckDB, beside the bars. Company facts change
            │       slowly, so the cache TTL is days, not seconds.
            ▼
   CompanyProfile ── one object, every field carrying source + as_of
```

## Provenance is per field, not per profile

This is the design decision that costs the most and is worth it.

A `CompanyProfile` is assembled from two providers and a dozen endpoints. Some
fields are as-filed truth, some are a vendor's derived ratio, some are an
analyst's opinion. Stamping the *object* with one source would make the whole
thing as weak as its weakest field — and a profile whose revenue came from a
filing but whose price target came from a survey is not uniformly trustworthy,
so it must not claim to be.

So every field carries its own `source`, `tier` and `as_of`, and anything that
speaks a number can say where that one number came from. This is
[[Market Data Sources]]' staleness rule applied at field granularity, and it is
what makes *"NVDA's PE is 51"* answerable with *"…per yfinance, four minutes
ago, derived — the filed earnings behind it are from the quarter ended
2026-04-30, filed three weeks later."*

## Caching, and why it is aggressive

Company data is the opposite of a quote. Per-field TTLs:

| Group | TTL | Why |
|---|---|---|
| Identity, sector, ISIN, CIK | 30 days | Changes on a corporate event, not a schedule |
| Statements, filings | 1 day | New only when something is filed |
| Ownership, short interest | 1 day | 13F is quarterly; short interest twice monthly |
| Analyst targets, recommendations | 1 day | Moves on upgrades, which are not intraday facts |
| Price, market cap, valuation multiples | 15 min | The only genuinely live group |

The whole profile is one store row per symbol per group, so a second
`genesis company NVDA` inside the TTL makes **no network call at all** — the
same property the bar store guarantees, for the same reason.

## What this is not

- **Not real-time.** Explicitly. Futures execution truth comes from IBKR
  ([[Market Data Plane]]); nothing here is on that path, and no
  [[Pre-Trade Risk Engine]] input may come from this note's data. It is tier 3.
- **Not a news feed.** Headlines are tier 4, untrusted, fenced by
  [[MCP Gateway]], and belong to [[Agent — News And Catalyst]]. yfinance's
  `news` endpoint is stored as *metadata about* articles, never as fact.
- **Not an analyst.** This assembles data. Judging it is
  [[Agent — Fundamental]]'s job, and that agent reads this model rather than
  calling a vendor.

## Where it plugs in

| New | Attaches to |
|---|---|
| `src/genesis/company/schema.py` | [[70-Schemas]] — the profile shape |
| `src/genesis/company/symbols.py` | the identity guards above |
| `src/genesis/company/providers/*.py` | one per source, same shape as marketdata adapters |
| `src/genesis/company/profile.py` | assembly + EDGAR reconciliation |
| `src/genesis/company/store.py` | DuckDB, beside `marketdata/store.py` |
| `genesis company <SYMBOL>` | `src/genesis/cli.py` |
| later: `market-data.fundamentals` | `src/genesis/mcp/allowlist.py`, per [[Market Data Plane]] |
| later: a search view | [[UI Stack]], [[Dashboard]] — Phase 6, not open |

## Corpus lineage

Patterns adapted, per [[Trading Corpus Index]]:

- `TradingAgents/tradingagents/dataflows/interface.py` — vendor chain with typed
  per-vendor errors, walked in configured order, **no silent fallback to an
  unconfigured vendor**. Genesis improves on it by making provenance structured
  data rather than a text header.
- `TradingAgents/tradingagents/dataflows/stockstats_utils.py` — `yf_retry`:
  exponential backoff on rate-limit errors *only*, everything else propagates
  immediately. Plus a staleness assertion on a present-but-old frame.
- `TradingAgents/tradingagents/dataflows/symbol_utils.py` — symbol normalisation
  and the `NoMarketDataError` taxonomy behind hazard 1.
- `machine-learning-for-trading/data/equities/fundamentals/xbrl_download.py` —
  EDGAR endpoints, the mandatory contact `User-Agent`, CIK-keyed caching, and
  the fiscal-period-vs-filed-date keying behind hazard 2.
- `TradingAgents/tradingagents/dataflows/fred.py` — small clean client shape for
  a keyed free API; the model for a future FRED provider.

## Related

[[Market Data Plane]] · [[Market Data Sources]] · [[Market Data Catalog]] ·
[[Agent — Fundamental]] · [[Agent — Screener]] · [[Safety Invariants]] ·
[[Memory Fabric]] · [[Trading Corpus Index]] · [[Open Questions]]
