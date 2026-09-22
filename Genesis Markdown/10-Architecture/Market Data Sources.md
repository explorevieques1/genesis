---
title: Market Data Sources
tags: [architecture, data, risk]
status: built
implemented_by: [src/genesis/marketdata/staleness.py, src/genesis/marketdata/normalize.py, src/genesis/marketdata/reconcile.py, src/genesis/marketdata/adapters/ibkr.py, src/genesis/marketdata/store.py, src/genesis/config.py, tests/marketdata/test_open_store.py, src/genesis/marketdata/quotes.py, tests/marketdata/test_reconcile.py, src/genesis/marketdata/heatmap.py, src/genesis/marketdata/performance.py, ui/src/components/charts/PriceChart.tsx, ui/src/workspace/panels/charting.tsx, ui/src/workspace/panels/heatmap.tsx, ui/src/workspace/panels/performance.tsx, ui/src/workspace/panels/ranges.tsx, ui/src/workspace/panels/tradingview.tsx]
---

# Market Data Sources

Where numbers come from, and how much each source is trusted.

Real-time data is the most likely **cost** bottleneck in this project. It is not a
compute bottleneck — computing levels from an OHLCV frame takes milliseconds.
Getting the bars is what costs money. So the design principle is:

> **Buy the data once. Read it from wherever it already lives. Trust it according
> to how it arrived.**

## The trust tiers

Not all data is equal, and the difference matters most at the moment it would move
money.

| Tier | Source | Trusted for | Never used for |
|---|---|---|---|
| **1 — Execution truth** | **The IBKR feed** — IB Gateway, data and execution over one connection ([[Open Questions]] §1). **Target role; the adapter ships at tier 3** until the reconciliation below is measured and accepted — `marketdata.adapters.ibkr.tier` is the authority | Sizing, stops, [[Pre-Trade Risk Engine]] checks, [[Trade Ledger]] reconciliation | — |
| **2 — Live subscription** | TradingView Desktop, read via [[genesis-tradingview-mcp]] | Quotes, session H/L, bars for level computation, answering questions aloud | Anything that sizes or places an order |
| **3 — Public / third-party** | `tradingview-mcp` (hosted), `mcp-market-data-server`, StockMCP, yfinance, **the `TV` chart panel's embedded feed** ([[Charting Engine]]) | Research, screening, backtests, closed-market work | Intraday execution decisions |
| **4 — Untrusted text** | News, social, web ([[MCP Gateway]] fenced) | Context and catalysts, always labelled | Any numeric claim |

**The rule that matters:** [[Pre-Trade Risk Engine]] reads tier 1 and nothing else.
A price scraped from a GUI is fine for *"what's the high of day on NQ"* and wrong
for *"size this position"*. ([[Safety Invariants]] §11)

## One process, one handle on the store

The bar store is a DuckDB file, and DuckDB keys **one database instance per
file per process**. A second connection whose configuration differs from the
first is not opened — it is refused:

```
Can't open a connection to same database file with a different configuration
than existing connections
```

Three call sites in the daemon opened it independently: the read routes
read-only, `build_source` writable, and `CompanyStore` — whose tables live in
the same file — writable. The daemon therefore worked until the first chart
command followed the first read, then died. It is an *ordering* bug, which is
why it survived every test that opened the store once.

`open_store()` in `marketdata/store.py` is the fix, and the shape matters:

- **One handle per file per process.** Everyone shares it, so there is no
  second configuration to disagree with. `BarStore(...)` direct is still there
  for tests and one-shot CLI runs, which are their own process.
- **`read_only` is a floor, not a mode.** A read request is satisfied by a
  writable handle. A write request against a read-only handle **upgrades it in
  place** — the read connection is closed and reopened writable, because the
  two cannot coexist in one process.
- **The daemon starts read-only and stays that way until something writes.**
  That is what lets a separate `genesis ingest` process hold the write lock
  while the UI reads. When the upgrade cannot take the lock, it reopens
  read-only and raises rather than continuing against a connection that will
  reject every INSERT — fail closed, and say which process is holding it.
- **`close()` on a shared handle is a no-op.** Fifteen call sites close in a
  `finally`; one of them closing the process's store would leave every later
  read reporting "store not created yet" for the life of the daemon.

> [!warning] The path comes from config, not from a default
> The read routes opened `DEFAULT_STORE_PATH` while every writer opened
> `config.marketdata.store_path`. On a machine whose config leaves the default
> alone those are the same file — which is exactly why this surfaced as a
> *crash* rather than as silence. Point config elsewhere and it becomes the
> quiet version instead: agents write one file, the UI reports an empty store
> about another. Same bug as the memory stores had, same fix.

## Why TradingView is tier 2 and not tier 1

You already pay for a live feed and the app is open all day. Reading it costs
nothing extra and answers most questions instantly — that's real leverage, and
it's why [[genesis-tradingview-mcp]] has a read path at all.

But it arrives through UI automation. That means:

- It breaks silently when TradingView updates
- It requires a GUI session, so it is unavailable to the 3am [[Daemon And Cadence|market-closed loop]]
- It has no delivery guarantee, no sequence numbers, no gap detection

Good enough to answer a question. Not good enough to be the last number seen
before capital moves.

## Staleness is part of the value

Every quote carries its source tier and its age. [[Safety Invariants]] §10 forbids
confabulation, and an unlabelled stale price is a confabulation.

```yaml
symbol: NQ1!
last: 20418.25
session_high: 20501.00
source: tradingview-desktop
tier: 2
as_of: 2026-08-29T14:32:07Z
age_ms: 340
```

Spoken answers say so when it matters: *"high of day is 20,501 as of a moment
ago"* — and, when the feed is stale, *"that's from four minutes ago, TradingView
isn't updating."*

## Fallback chain

Each consumer declares an ordered list, and takes the first available source at or
above its minimum tier:

| Consumer | Chain | Minimum tier |
|---|---|---|
| [[Pre-Trade Risk Engine]] | broker feed → **reject** | 1 |
| [[Agent — Level Watcher]] | IBKR only, subject to the freshness bound below (`chains.level_watcher`) | 3 |
| [[Agent — Chart Markup]] | IBKR → Databento → yfinance (`chains.chart_markup`) | 3 |
| [[Agent — Screener]] | market-data MCP → tradingview-mcp hosted | 3 |
| Voice quote lookup | TradingView → broker feed → market-data MCP | 3 |
| Backtests | stored bars only | — |

> [!warning] The Level Watcher needs a freshness bound, not just a chain
> A chain is an ordering, not a guarantee, and for this consumer the ordering
> alone is actively misleading. **Databento is historical-only** (`historical_only:
> true`) and **yfinance serves daily bars**. A level watcher that falls through to
> either is not watching anything — it is re-reading yesterday and reporting
> touches that happened before the session opened.
>
> So this consumer takes a bound rather than a fallback: **no source older than
> two bars of the watched timeframe may satisfy it**
> (`genesis.marketdata.staleness`, which already computes exactly this). When no
> source meets the bound, the watcher is **disabled and says so** — an honest
> silence, per [[Error Handling And Degradation]]. It never degrades to a
> slower feed, because a late level alert is worse than no level alert: it
> arrives looking timely.

There is no fallback below tier 1 for the risk engine. Fail closed
([[Safety Invariants]] §3).

## Real-time: still not the workload

[[Market Data Plane]]'s posture — *"v1 needs no live feed at all"* — **still
holds for research, and batch-first is unchanged.** Closed bars, filings and
calendars support every research agent, and the overnight pass is still the
product.

What §1 and §6 change is narrow: real-time is now *in scope*, and it is in scope
for exactly three things —

1. [[Agent — Level Watcher]],
2. intraday [[Agent — Screener]],
3. Phase 7 execution truth for [[Pre-Trade Risk Engine]].

Nothing else should acquire a live dependency. A research agent that needs a
live feed to do its job has been designed wrong.

## Caching

Bars are immutable once closed, so cache them permanently and never re-fetch.
Quotes are cached for seconds. The cache key includes the source tier — a tier-3
bar must never satisfy a tier-2 request silently.

Store closed bars locally on first sight, from any source. Over months this
accumulates into a private history that makes backtests free and removes a
recurring cost. It also means [[Agent — Backtest Runner]] never depends on a live
subscription.

## Tier 1 is the IBKR feed — and it is not tier 1 yet

[[Open Questions]] §1 and §6 are both **resolved as of 2026-09-04**. The broker
is Interactive Brokers, the asset class is CME futures, and its feed is tier 1:
data and execution arrive over one connection, so the chart and the fill cannot
disagree.

**Databento is bought as historical only**, on free credits, because IBKR cannot
serve backtests — expired contracts more than ~2 years past expiry are gone, and
its historical endpoint paces at 60 requests per 10 minutes. That split is the
constraint [[Market Data Plane]] is shaped around.

> [!warning] Promotion to tier 1 requires evidence, not a config flag
> The IBKR adapter arrives at **tier 3**. Tier 1 is the tier
> [[Pre-Trade Risk Engine]] reads in Phase 7 and nothing else, so promoting a
> source because it connected successfully is exactly the drift between believed
> and actual state that [[Biological Design]]'s *proprioception before ambition*
> warns about.
>
> **The cutover is a reconciliation.** Pull the same session of ES bars from
> Databento and from IBKR and diff them. They will not match exactly — different
> aggregation, different session handling. Decide the tolerance, **write the
> number into this note**, and make it a test. Measure once, record, then
> promote.
>
> **The harness exists**: `genesis ibkr reconcile <symbol> <timeframe>` pulls
> the same window from both adapters, aligns on timestamp, and reports the
> worst absolute and relative difference per OHLCV field — plus, importantly,
> any bars present in one feed and not the other. That last part is usually the
> real finding: a session-boundary convention, not a data-quality problem.
>
> The harness deliberately does **not** promote anything. Choosing how much
> disagreement is acceptable before a number sizes a position is a judgement,
> and it belongs to a person who then writes it here.
>
> Tolerance: _to be measured._ ← **this line is the gate.** While it reads
> "to be measured", `marketdata.adapters.ibkr.tier` must stay 3.

## What is still open

[[Open Questions]] §13 — futures symbol identity and roll policy. Until it is
answered the store holds **dated contracts only**, which is always correct and
never needs migrating.

## Related

[[Market Data Plane]] · [[Market Data Catalog]] · [[genesis-tradingview-mcp]] ·
[[genesis-charting-mcp]] · [[MCP Server Catalog]] ·
[[Pre-Trade Risk Engine]] · [[Safety Invariants]] · [[Agent — Level Watcher]] ·
[[Error Handling And Degradation]] · [[Open Questions]]
