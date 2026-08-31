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

> [!note] This catalogue is filtered by [[Open Questions]]
> §1 (Alpaca paper, US equities), §2 (no prop firm), §4 (no GPU, hosted Claude),
> §6 (TradingView is tier 2; tier 1 is the broker's own feed) and §9 (Lithium for
> corpus retrieval) each rule whole categories in or out. Servers that those
> decisions exclude are not simply absent — they are recorded in
> [[#Ruled out by decision]] with the question that killed them, so Phase 4 does
> not re-propose them.

## Broker / execution

| Server | Status | Notes |
|---|---|---|
| **alpaca-mcp-server** (official) | **integrate** + study | Promoted from *study* by [[Open Questions]] §1. FastMCP + OpenAPI. **This is now the tier-1 feed** ([[Market Data Sources]]) — the only source [[Pre-Trade Risk Engine]] may read, because it is the venue's own book. Still also **the reference implementation** for tool schema, auth handling, and error shape — read `src/` before writing [[genesis-execution-mcp]]. Wire the **read** half in Phase 3 (bars, quotes, `account`, `positions`); the order-placement half is never exposed to an agent, see below. |
| jesse-mcp | study | Bridge to the Jesse crypto framework. Relevant only if crypto is in scope ([[Open Questions]] §1). |
| **topstepx-mcp** (`brandononchain`) | study | Reference MCP for the official TopstepX/ProjectX Gateway API. The pointer to fork from if [[Open Questions]] §2 resolves to Topstep — see [[Futures Broker Options]]. |
| Tradovate MCP servers (`alexanimal`, `0xjmp`) | not usable | Both wrap Tradovate's direct API, which requires a $1,000 **live** balance and excludes prop/eval accounts outright. Dead end for a funded futures account regardless of implementation quality — see [[Futures Broker Options]]. |

Execution tools are wrapped by [[genesis-execution-mcp]] so the risk gate is
unavoidable. No agent gets raw broker access.

> [!danger] Integrating Alpaca in Phase 3 means integrating *half* of it
> `alpaca-mcp-server` exposes order placement in the same server as market data.
> Registering it whole would put a `place_order` tool in the catalogue three
> phases before the risk engine exists — precisely the path [[Safety Invariants]]
> §1 forbids. The gateway registers its **read tools only**, by explicit
> allow-list of tool names rather than by server. A test enumerates the
> registered surface and fails if any mutating Alpaca tool appears.

## Market data / technical analysis

| Server | Status | Notes |
|---|---|---|
| **mcp-market-data-server** (fintools-ai) | integrate | Volume profile, 15+ indicators, ORB, fair-value-gap analysis. Built for AI trading agents. The structural-level workhorse for [[Agent — Chart Markup]] and [[Agent — Screener]]. |
| **tradingview-mcp** (atilaahmettaner) | integrate | 37 tools: indicators, screeners, multi-timeframe reads, sentiment, backtesting. **Headless data and analysis only — it does not draw.** No TradingView account in the loop; fetches public endpoints, so it is tier 3 ([[Market Data Sources]]). |
| **[[genesis-tradingview-mcp]]** | build | Drives the TradingView **Desktop app** over CDP, and reads the live subscription already running in it. A different job entirely from the row above — actuation and tier-2 data. |
| StockMCP | optional | Yahoo Finance real-time + basic analysis, FastAPI-based. Good free fallback. |

Those first two rows share a name and share nothing else. One answers *what is true
about the market*; the other *makes my screen show it*. Both earn a place.

Every source is tiered by trust in [[Market Data Sources]] — and tier 1, the
broker's own feed, is the only thing [[Pre-Trade Risk Engine]] is allowed to read.

## Fundamentals / news

| Server | Status | Notes |
|---|---|---|
| **financial-datasets mcp-server** | integrate | Fundamentals, prices, news. Primary source for [[Agent — Fundamental]]. |
| **sec-edgar-mcp** | integrate | 10-K / 10-Q / 8-K, insider Form 4, full-text filing search. **US-issuer only — which is exactly what §1 chose.** The one source in this section that is primary rather than derivative: it is the filing itself, not somebody's summary of it. Structured backbone for [[Agent — Fundamental]]. |
| **openbb-mcp** | integrate | The heavyweight. Fundamentals, macro, estimates, ownership and news aggregated across many providers behind one interface, Python-native (§3). Closest thing to *one server covers most of Phase 4 research* — and correspondingly the biggest single contributor of tools, so see the overlap warning below. |
| **alpha-vantage-mcp** (official) | integrate | Free tier carries the earnings calendar, economic indicators, and news-with-sentiment. The cheapest way to make the *News / calendar sources* row concrete. |
| **fred-mcp** | integrate | St. Louis Fed series — rates, CPI, unemployment, spreads. Free and unmetered in practice. Macro context for [[Agent — News And Catalyst]], and the only macro source here that is a primary government release. |
| News / calendar sources | *superseded* | Placeholder, now filled by the three rows above. |

Everything from this category is fenced as untrusted ([[MCP Gateway]]).

> [!warning] Overlap degrades routing, not just context
> `openbb-mcp`, `mcp-market-data-server` and `tradingview-mcp` all return bars,
> quotes and indicators. Three competing `get_quote` variants is a different
> failure from *too many tools*: the router in [[MCP Gateway]] can pick a
> defensible-but-wrong one, and the agent never notices because the shape is
> right. Deduplicate at the **registry** level — one canonical tool per
> capability, the rest unregistered rather than merely deprioritised — and let
> [[Market Data Sources]] decide which server wins each capability by tier.

## Knowledge

| Server | Status | Notes |
|---|---|---|
| **Obsidian MCP** | integrate | Read/write the vault — notes, links, Dataview. The bridge in [[Obsidian Vault Schema]]. |
| **Lithium MCP** | integrate | [[Repo — Lithium Codebase]] — hybrid search over the cloned corpus. Local, Rust, already built. See [[Open Questions]] §9. |

## Utility

filesystem · git · fetch · time · sqlite — housekeeping, and useful to
[[Agent — Watchdog]].

## General purpose — web, work, and the desk

Genesis is a trading system, but it is also *the assistant that is already
listening*. Once the voice loop and the gateway exist, refusing to let it answer
a non-trading question is an artificial limit, not a safety property. These
servers make it generally useful.

The safety property is elsewhere, and it is unchanged: **generality is granted at
the allow-list, never at the tool surface.** Every server in this section is
allow-listed to the [[Orchestrator]], to [[Agent — Idea Synthesizer]] where
noted, and to Claude Code. **None of it reaches [[Execution Family]]** — the
agent nearest the money stays the agent with the fewest tools.

### Web

| Server | Status | Notes |
|---|---|---|
| **exa-mcp** *or* **tavily-mcp** | integrate | Real search with content extraction, rather than raw `fetch` against a URL you guessed. Both return structured results with source URLs, which makes `<untrusted>` fencing mechanical instead of an HTML-parsing exercise. Pick **one** — two search servers is the overlap problem above in miniature. |
| **fetch** (official) | integrate | Already in [[#Utility]]. Retained for the case where the URL is known and search is a detour. SSRF guard per [[MCP Gateway]]. |
| **markitdown-mcp** (Microsoft) | integrate | PDF / docx / xlsx / pptx / html → markdown. The missing link between *a research PDF exists* and *the vault can hold it*. Feeds [[Obsidian Vault Schema]] and, for anything worth keeping, [[Repo — Lithium Codebase]]. |
| **arxiv-mcp** | optional | Quant and ML paper search. Genuinely useful to [[Agent — Strategy Author]] — most of what it should be reading is q-fin preprints, not blog posts. Low volume, so cheap. |

### Work

| Server | Status | Notes |
|---|---|---|
| **github-mcp-server** (official) | integrate | Issues, PRs, code search across [[Repo — Lithium Codebase]], [[Repo — gensis-agents]], [[Repo — Gensis Terminal Official]] and Genesis itself. Also the honest way for [[Agent — Watchdog]] to file a defect rather than only logging one. **Read-only scope by default**; write scope is a deliberate, separately-granted step. |
| **Google Calendar MCP** | optional | The earnings calendar is one calendar; yours is another. Useful mostly so the [[Orchestrator]] knows you are in a meeting and should hold a non-urgent brief. |
| **Gmail MCP** | optional | Broker statements and fill confirmations arrive by email. A cross-check on [[Trade Ledger]] reconciliation that does not come from the broker's API — i.e. genuinely independent evidence. Untrusted, heavily fenced, read-only. |
| **excel-mcp / spreadsheet MCP** | optional | Export a ledger slice or a tearsheet to a file an accountant will open. Output-side only. |

### Desk and notification

| Server | Status | Notes |
|---|---|---|
| **Telegram** *or* **Discord MCP** | integrate | The answer to *what happens when the desk is empty*. Genesis speaks aloud to an empty room otherwise. Alerts, level breaks, and — later — [[Approval Modes|`confirm`]] prompts routed to a phone. Pick one. |
| **chrome-devtools-mcp** (Google) | build-time only | For Claude Code while writing [[genesis-tradingview-mcp]] — poking at Electron's target model interactively beats guessing selectors. **Never registered in the runtime gateway.** Not a contradiction of the Playwright rejection in §11: that was about a client library's attach handshake, this is an interactive debugging surface. |
| **context7-mcp** | build-time only | Current library docs for Claude Code during implementation. No runtime role. |

> [!important] Two rules for everything in this section
> 1. **Untrusted by default.** Web, email, chat and issue trackers are all
>    third-party text reaching a model. Every one of them is fenced per
>    [[MCP Gateway]] — and a Telegram message is not an instruction channel just
>    because it arrives from your own account. Inbound chat is data.
> 2. **The fence and the allow-lists ship first.** These servers are the reason
>    Phase 3 is ordered *gateway, then servers*. Wiring general web access before
>    per-agent allow-lists are enforced would put untrusted text one hop from an
>    agent that has no business reading it. Do not let the tool count tempt the
>    ordering.

## Custom servers we build

| Server | Why it must be ours |
|---|---|
| [[genesis-execution-mcp]] | The risk gate is baked in. No agent can route around it. |
| [[genesis-charting-mcp]] | Level computation + [[Markup Spec]] rendering are core to the system. |
| [[genesis-memory-mcp]] | Query and write [[Memory Fabric]] from any agent — and from Claude Code. |
| [[genesis-backtest-mcp]] | One call runs vectorbt / backtesting.py / freqtrade and returns a complete result. |
| [[genesis-tradingview-mcp]] | Nobody else's server drives *your* desktop app, respects your hand-drawn objects, or refuses to reach the Trade panel. |

## Ruled out by decision

Not *bad servers*. Servers that a resolved question in [[Open Questions]] has
already excluded — recorded here so they are not re-proposed in Phase 4 as though
the question were still open.

| Server | Excluded by | Reason |
|---|---|---|
| ccxt-mcp, jesse-mcp, any crypto venue | §1 | v1 is US equities. Revisit only if §1 is reopened. |
| topstepx-mcp, Tradovate servers | §1 + §2 | No futures, no funded account in v1. Rows retained above with their research intact, since §1 explicitly defers futures rather than rejecting them. |
| chroma-mcp, qdrant-mcp | §9 | Lithium for corpus retrieval, a purpose-built store for [[Memory Fabric]]. A third retrieval system is the thing §9 decided against. |
| `@modelcontextprotocol/server-memory` | §9 + [[Agent Contract]] | [[genesis-memory-mcp]] owns namespace enforcement. A parallel memory server is not a duplicate feature — it is a hole in the enforcement boundary. |
| elevenlabs-mcp | §7 | ElevenLabs is confirmed, but [[10-Architecture/Voice Stack]] already calls the SDK directly. An MCP hop in the voice hot path spends the `<500 ms` budget to gain nothing. |
| sequential-thinking, any local-model server | §4 | No GPU, ~1 GB free RAM, and `claude-opus-5` has adaptive thinking natively. |
| playwright-mcp | §11 | `connect_over_cdp` connects then hangs to a 180 s timeout against Electron. Recorded in [[genesis-tradingview-mcp]]; do not reintroduce. |
| polygon-mcp, databento-mcp | §6 | Not wrong — premature. Tier 1 is answered by Alpaca for v1. Revisit only if the IEX feed proves too thin for [[Agent — Level Watcher]]. |
| Shell / arbitrary-command servers | [[Safety Invariants]] | A general shell tool makes every other allow-list advisory. Claude Code has a shell; the running fleet does not. |

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
- [ ] Capability overlap resolved — no second server registered for a capability
      another server already owns ([[Market Data Sources]] decides by tier)

That checklist is the difference between "we added a server" and "we can rely on it."

## Related

[[MCP Gateway]] · [[Trading Corpus Index]] · [[Agent Contract]] · [[Agent — Watchdog]] ·
[[Futures Broker Options]] · [[Open Questions]] · [[Market Data Sources]] ·
[[Safety Invariants]] · [[Build Order]]
