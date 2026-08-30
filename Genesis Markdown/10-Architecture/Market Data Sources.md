---
title: Market Data Sources
tags: [architecture, data, risk]
status: spec
implemented_by: []
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
| **1 — Execution truth** | The broker's own feed and account state | Sizing, stops, [[Pre-Trade Risk Engine]] checks, [[Trade Ledger]] reconciliation | — |
| **2 — Live subscription** | TradingView Desktop, read via [[genesis-tradingview-mcp]] | Quotes, session H/L, bars for level computation, answering questions aloud | Anything that sizes or places an order |
| **3 — Public / third-party** | `tradingview-mcp` (hosted), `mcp-market-data-server`, StockMCP, yfinance | Research, screening, backtests, closed-market work | Intraday execution decisions |
| **4 — Untrusted text** | News, social, web ([[MCP Gateway]] fenced) | Context and catalysts, always labelled | Any numeric claim |

**The rule that matters:** [[Pre-Trade Risk Engine]] reads tier 1 and nothing else.
A price scraped from a GUI is fine for *"what's the high of day on NQ"* and wrong
for *"size this position"*. ([[Safety Invariants]] §11)

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
| [[Agent — Level Watcher]] | broker feed → TradingView → market-data MCP | 3 |
| [[Agent — Chart Markup]] | TradingView → market-data MCP → yfinance | 3 |
| [[Agent — Screener]] | market-data MCP → tradingview-mcp hosted | 3 |
| Voice quote lookup | TradingView → broker feed → market-data MCP | 3 |
| Backtests | stored bars only | — |

There is no fallback below tier 1 for the risk engine. Fail closed
([[Safety Invariants]] §3).

## Caching

Bars are immutable once closed, so cache them permanently and never re-fetch.
Quotes are cached for seconds. The cache key includes the source tier — a tier-3
bar must never satisfy a tier-2 request silently.

Store closed bars locally on first sight, from any source. Over months this
accumulates into a private history that makes backtests free and removes a
recurring cost. It also means [[Agent — Backtest Runner]] never depends on a live
subscription.

## Open decisions

[[Open Questions]] §6 — whether to buy a real-time feed (Polygon / Databento /
Alpaca SIP) on top of the TradingView subscription. The answer depends on
[[Open Questions]] §1: a broker feed is tier 1 and may make a separate
subscription unnecessary.

## Related

[[genesis-tradingview-mcp]] · [[genesis-charting-mcp]] · [[MCP Server Catalog]] ·
[[Pre-Trade Risk Engine]] · [[Safety Invariants]] · [[Agent — Level Watcher]] ·
[[Error Handling And Degradation]] · [[Open Questions]]
