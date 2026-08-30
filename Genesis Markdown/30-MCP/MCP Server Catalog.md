---
title: MCP Server Catalog
tags: [mcp, moc]
status: spec
implemented_by: []
---

# MCP Server Catalog

What to integrate, and what to study. **Not everything here runs as a live
dependency** — several are reference implementations for building our own.

All access goes through the [[MCP Gateway]].

## Broker / execution

| Server | Status | Notes |
|---|---|---|
| **alpaca-mcp-server** (official) | integrate + study | FastMCP + OpenAPI. Stocks/options/crypto data plus order placement. **The reference implementation** for tool schema, auth handling, and error shape — read `src/` before writing [[genesis-execution-mcp]]. |
| jesse-mcp | study | Bridge to the Jesse crypto framework. Relevant only if crypto is in scope ([[Open Questions]] §1). |

Execution tools are wrapped by [[genesis-execution-mcp]] so the risk gate is
unavoidable. No agent gets raw broker access.

## Market data / technical analysis

| Server | Status | Notes |
|---|---|---|
| **mcp-market-data-server** (fintools-ai) | integrate | Volume profile, 15+ indicators, ORB, fair-value-gap analysis. Built for AI trading agents. The structural-level workhorse for [[Agent — Chart Markup]] and [[Agent — Screener]]. |
| **tradingview-mcp** | integrate | Real-time data, technical analysis, screeners, backtesting via TradingView. |
| StockMCP | optional | Yahoo Finance real-time + basic analysis, FastAPI-based. Good free fallback. |

## Fundamentals / news

| Server | Status | Notes |
|---|---|---|
| **financial-datasets mcp-server** | integrate | Fundamentals, prices, news. Primary source for [[Agent — Fundamental]]. |
| News / calendar sources | integrate | Earnings and economic calendars for [[Agent — News And Catalyst]]. |

Everything from this category is fenced as untrusted ([[MCP Gateway]]).

## Knowledge

| Server | Status | Notes |
|---|---|---|
| **Obsidian MCP** | integrate | Read/write the vault — notes, links, Dataview. The bridge in [[Obsidian Vault Schema]]. |
| **Lithium MCP** | integrate | [[Repo — Lithium Codebase]] — hybrid search over the cloned corpus. Local, Rust, already built. See [[Open Questions]] §9. |

## Utility

filesystem · git · fetch · time · sqlite — housekeeping, and useful to
[[Agent — Watchdog]].

## Custom servers we build

| Server | Why it must be ours |
|---|---|
| [[genesis-execution-mcp]] | The risk gate is baked in. No agent can route around it. |
| [[genesis-charting-mcp]] | Level computation + [[Markup Spec]] rendering are core to the system. |
| [[genesis-memory-mcp]] | Query and write [[Memory Fabric]] from any agent — and from Claude Code. |
| [[genesis-backtest-mcp]] | One call runs vectorbt / backtesting.py / freqtrade and returns a complete result. |

## Integration checklist

For each server added:

- [ ] Registered in the [[MCP Gateway]] catalogue with normalized schemas
- [ ] Added to the allow-lists of exactly the agents that need it — and no others
- [ ] Health probe defined for [[Agent — Watchdog]]
- [ ] Untrusted-content fencing configured if it returns external text
- [ ] Rate limits and quotas configured
- [ ] Caching policy defined (what's cacheable, and until when)
- [ ] Typed error mapping — its errors map to `transient` / `degraded` / `fatal`
- [ ] Degradation behaviour documented: what breaks, and what still works

That checklist is the difference between "we added a server" and "we can rely on it."

## Related

[[MCP Gateway]] · [[Trading Corpus Index]] · [[Agent Contract]] · [[Agent — Watchdog]]
