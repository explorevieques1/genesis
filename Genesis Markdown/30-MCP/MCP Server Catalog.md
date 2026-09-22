---
title: MCP Server Catalog
tags: [mcp, moc]
status: building
implemented_by: [src/genesis/mcp/servers.py, src/genesis/mcp/default_servers.yaml, src/genesis/mcp/discovery.py, tests/mcp/test_discovery.py, tests/mcp/test_servers.py]
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
| **alpaca-mcp-server** (official) | **configured, off** | Promoted from *study* by [[Open Questions]] §1. **The tier-1 feed** ([[Market Data Sources]]) — the only source [[Pre-Trade Risk Engine]] may read, because it is the venue's own book. Also **the reference implementation** for tool schema, auth handling and error shape — read `src/` before writing [[genesis-execution-mcp]]. Read half configured with real tool names (`get_stock_bars`, `get_stock_latest_quote`, `get_stock_snapshot`, `get_account_info`, `get_all_positions`, `get_clock`), verified 2026-09-03. See §three locks below. |
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
| **mcp-market-data-server** (fintools-ai) | configured, off | Volume profile, 15+ indicators, ORB, fair-value-gap analysis. Built for AI trading agents. The structural-level workhorse for [[Agent — Chart Markup]] and [[Agent — Screener]]. |
| **maverick-mcp** (`wshobson`) | configured, off — **11 of 52** | Screening and technical analysis, and good at both. **It also sizes positions and computes ATR stops** (`portfolio_get_regime_adjusted_sizing`, `portfolio_risk_adjusted_analysis`, `portfolio_check_position_risk`) — [[Safety Invariants]] §3 — **keeps its own portfolio and trade journal**, which is a second [[Trade Ledger]], and **ships twelve backtesting tools**, which is a second [[genesis-backtest-mcp]]. Eleven named tools only: screens, RSI/MACD/full TA, bars, quote, fundamentals, overview. See the danger box below. |
| **mcp-trader** (`wshobson`) | **not usable** | **Archived 2025-08-24 and superseded by maverick-mcp**, by its author. Row kept so nobody re-adds it from an old bookmark. |
| **yfinance-mcp-server** (`barvhaim`) | configured, off | 10 tools over yfinance — history, dividends, splits, financials, earnings, analyst recommendations. No API key, and no service agreement either: Yahoo changes what it serves without notice, which is exactly the tier-3 bargain. Its real value is **breadth of history for free**, which is what [[Market Data Catalog]] says an analyst's list is made of. Launched from a clone. |
| **stock-market-mcp-server** (`sverze`) | configured, off | Finnhub behind a small server — symbol lookup, quote, basic financials, market and company news, candles. The thinnest of the options, and useful mainly as a **cross-check on a number that matters**: two independent sources disagreeing is information, and one source is never wrong about itself. Launched from a clone. |
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
| **financial-datasets mcp-server** | configured, off — 6 of 10 | Fundamentals, prices, news. Primary source for [[Agent — Fundamental]]. Six taken: income, balance, cash flow, quote, historical prices, news. The four crypto tools are out by §1. No PyPI package — launched from a clone. |
| **sec-edgar-mcp** | integrate | 10-K / 10-Q / 8-K, insider Form 4, full-text filing search. **US-issuer only — which is exactly what §1 chose.** The one source in this section that is primary rather than derivative: it is the filing itself, not somebody's summary of it. Structured backbone for [[Agent — Fundamental]]. |
| **openbb-mcp** | configured, off | The heavyweight. Fundamentals, macro, estimates, ownership and news across many providers behind one interface, Python-native (§3). Closest thing to *one server covers most of Phase 4 research* — and the biggest single contributor of tools, so see the overlap warning below. **It gates its own surface by category**, which is the enforcement that matters: `--allowed-categories equity,news,economy,etf,index,fixedincome` is a ceiling the server imposes on itself, where a `tools:` block is only a filter on what we catalogue. Crypto, derivatives, currency and commodity are out by §1. Its `activate_tools` / `activate_category` tools are **never registered** — a model changing the shape of our own catalogue at runtime is the decision the registry exists to make at boot. |
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
| **exa-mcp** *or* ~~tavily-mcp~~ | **integrated** | **Exa, wired 2026-09-02** — the *hosted* endpoint (`https://mcp.exa.ai/mcp`), authenticated by an `x-api-key` header. The original reasoning holds and Exa satisfies it: structured results with source URLs, so `<untrusted>` fencing is mechanical rather than an HTML-parsing exercise. Four tools: `web_search_exa`, `web_search_advanced_exa`, `web_fetch_exa` and `agent_run`. Tavily stays unwired — the rule was pick **one**. |
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

## Wired — status 2026-09-03

**103 tools from 14 servers**, every one started through genesis's own runtime
with its tool list read back. `genesis mcp check` repeats that on demand.
**Every market-data source here is free and most need no key at all.**

| Server | Tools | Key? | Trust | What it brings |
|---|---|---|---|---|
| `openbb` | 24 of 113 | none | untrusted t3 | Earnings/dividend/split/IPO/econ **calendars**, forward estimates, discovery screens, individual statements, OECD & IMF macro |
| `sec-edgar` | 13 of 21 | contact string | trusted t1 | The filings themselves — content, sections, financials, insider Form 4 |
| `maverick` | 13 of 37 | none | untrusted t3 | **Screening** and **technical analysis**, quote, batch bars, market overview |
| `yfinance` | 10 | none | untrusted t3 | **Twenty years of daily bars**, snapshots, statements, earnings, dividends, splits, analyst ratings, company news |
| `obsidian` | 8 | none | trusted t1 | Read, search, create, edit notes and tags |
| `arxiv` | 7 of 19 | none | untrusted t4 | Search, abstracts, full text, citation graph |
| `filesystem` | 6 | none | trusted t1 | Read files already in the vault |
| `fred` | 5 of 33 | free key | trusted t1 | Series observations and search, release calendar |
| `tradingview` | 5 of 73 | none | untrusted t3 | Sentiment, patterns, anomalies, multi-timeframe |
| `git` | 4 | none | trusted t1 | Repo state for [[Agent — Watchdog]] |
| `exa` | 4 | paid key | untrusted t4 | Web search, page read, deep-research agent |
| `time` | 2 | none | trusted t1 | Clock and timezone |
| `markitdown` | 1 | none | trusted t1 | PDF/docx/xlsx/pptx → markdown |
| `fetch` | 1 | none | untrusted t4 | Known URL, SSRF-guarded |
| `stock-market` | 2 | **free key** | untrusted t3 | Finnhub: market-wide news, basic financial metrics. *Awaiting `FINNHUB_API_KEY`* |
| `github` | 0 | **token** | untrusted t3 | Hosted read-only endpoint; reached and authenticating. *Awaiting a token* |

Three of these are launched from a clone rather than PyPI, because they have no
published package:

```
git clone https://github.com/barvhaim/yfinance-mcp-server      ~/.genesis/mcp-servers/yfinance-mcp-server
git clone https://github.com/wshobson/maverick-mcp             ~/.genesis/mcp-servers/maverick-mcp
git clone https://github.com/sverze/stock-market-mcp-server    ~/.genesis/mcp-servers/stock-market-mcp-server
```

`uv --directory` syncs their dependencies on first run. A missing clone is a
start-up failure that `genesis mcp check` reports and skips — never fatal.

**Configured and off:** `alpaca` (needs a broker account — tier 1, the only
source [[Pre-Trade Risk Engine]] may read), `genesis-tradingview` (needs the
desktop app running), `financial-datasets` and `alpha-vantage` (paid or
superseded by free sources), `telegram` (writes, so its tool names must come
off a live server first), `market-data` (does not install).

### `capability_prefix` — how a bulk-registered server becomes grantable

A tool registered in bulk gets its own bare name as its capability, and a
capability with no namespace is one **no allow-list can grant**: entries are
exact or `prefix.*`. That is why `time` and `filesystem` above name every tool by
hand for no reason other than to give it a capability. `capability_prefix` says
it once — `filings.*`, `macro.*`, `papers.*`, `convert.*`, `repo.*` — and keeps
two servers apart when they happen to agree on a word.

### `read_only: true` does not mean "register everything"

Several servers above are `read_only: true` **and** `explicit_tools: true`. The
first says the server cannot write. The second says we are naming its tools
anyway, because it offers more of them than a trading desk has questions for.

FRED ships 33 tools and 28 walk its own taxonomy — categories, tags, sources,
release tables, GeoJSON shapes. That is how a person *browses* FRED in a
browser; nothing in Genesis browses. arxiv ships 19 and 12 manage a local paper
library, which is the second retrieval system [[Open Questions]] §9 decided
against.

This was measured, not assumed. Registered whole, the catalogue reached 104
tools and the router found the right *server* every time and the right *tool*
never: a server's keywords are equally true of all of it, so 33 FRED tools tied
and the tie fell alphabetically. Curated to 56, selection is right. **A bigger
catalogue made the system worse, which is the whole premise of [[MCP Gateway]]
§2 demonstrated on our own config.**

### Free market data, wired — and the correction that got it there

**Status 2026-09-03: 103 tools from 14 servers, and every market-data source
in it is free.**

An earlier pass parked eight servers on a "vendor bench" pending *the
market-data decision*, and that was wrong in a way worth writing down, because
the mistake is easy to repeat.

**"Market data" was doing too much work as a phrase.** It was being used for six
different things — real-time tick and streaming quotes, delayed quotes, closed
EOD bars, fundamentals, macro series, and screening — and the deferral was
applied to all six when it only ever justified the first. Fundamentals are not
market data. Neither are dividends, analyst estimates, an earnings calendar, or
a stock screener. Blocking those on a decision about the cost of a live feed
bottlenecked production for nothing.

Worse, the note being deferred to says the opposite. [[Market Data Plane]]:
*"v1 needs no live feed at all"* — batch-first, closed bars, because Genesis is
an analyst and the human is the trader. The expensive axis is latency, and
latency is worth almost nothing to an analyst. **The expensive thing was never
in scope, and the free things were being gated on it.**

The real engineering concern underneath was narrower and is now handled: a
**capability contest**, three servers all claiming `market-data.quote` and the
router silently picking a defensible-but-wrong one. That is settled by deciding
owners, which is a judgement call, not an open question.

#### One owner per capability, decided free-first

Registry dedup *refuses* two tools claiming one capability at one tier — it
raises rather than picking, because a silent coin-flip between two data feeds
is exactly what it exists to prevent. That refusal happens at start-up, so a
contest introduced by editing the config is not a subtle bug; it is a system
that will not boot. So the contest is settled by hand, and the tie-break is
**cost**:

> needs nothing  >  needs a free key  >  needs a paid key

| Capability | Owner | Why it won |
|---|---|---|
| `market-data.ohlcv` | yfinance | Twenty years of daily bars, free, no key. Depth is what [[Market Data Catalog]] says an analyst's list is made of. |
| `market-data.quote` | maverick | No key, no account. Delayed, which is fine — tier 3 answers *what's it trading at*, never *how much do I buy*. |
| `market-data.quotes` | yfinance | Many symbols in one call. A **different question** from one quote, so a different capability rather than a competitor. |
| `market-data.overview` | maverick | Indices, sectors, movers, volatility. |
| `calendar.*` | openbb | Earnings, dividends, splits, IPOs, company events, economic releases. Nothing else here has them. |
| `analyst.consensus`, `.price-target`, `.forward-eps` | openbb | Forward numbers. yfinance has *recommendations* and no forecasts. |
| `analyst.recommendations` | yfinance | Ratings and targets as published. |
| `screen.bullish/bearish/supply-demand/all/criteria` | maverick | Momentum and structure screens. |
| `screen.gainers/losers/most-active/undervalued/growth-tech` | openbb | Discovery screens — a different question from momentum. |
| `fundamentals.income/.balance/.cashflow/.as-reported` | openbb | Statements individually, with growth and as-reported variants. |
| `fundamentals.statements` | yfinance | All three together — different granularity, different capability. |
| `ta.rsi/.macd/.full` | maverick | Indicator reads. `ta.sentiment/.pattern/.anomaly/.multi-timeframe` stay with tradingview. |
| `corporate.dividends/.splits` | yfinance | Corporate actions as facts, not prices. |
| `news.company` | yfinance | Free and no key. |
| `news.market` | Finnhub | The one genuinely market-wide feed here. |
| `macro.series/.search/.release-calendar` | FRED | Primary government releases, already wired. |
| `macro.indicators/.interest-rates/.fomc` | openbb | OECD and IMF series FRED does not carry. |

**Tier still means trust, not preference.** Everything above is tier 3 — public
and third-party, fine for research and closed-market work, **never for sizing a
position or setting a stop**. [[Pre-Trade Risk Engine]] reads tier 1 and nothing
else ([[Safety Invariants]] §11), and nothing in this table is tier 1. A test
asserts that no server except the broker may ever claim a `market-data.*` or
`broker.*` capability at tier 1 or 2.

When `alpaca` is enabled it takes `market-data.ohlcv` and `market-data.quote`
from the free servers on tier — correctly. A quote from the venue's own book
beats a quote from Yahoo wherever both exist.

#### What is still parked, and why

Three servers, and none of them for a pending decision:

| Server | Why |
|---|---|
| `financial-datasets` | **Paid, and now superseded.** Every one of its 11 tools is free elsewhere: statements from openbb, prices from yfinance, news from yfinance, filings from sec-edgar. Kept as a written route if a free source degrades, with `vendor-` scoped capabilities so enabling it can never win a tier contest against a free tool. |
| `alpha-vantage` | **Superseded by openbb**, and this is the clearest win of the batch. Its unique value was the earnings calendar at **25 calls a day** — one retry loop from useless. openbb serves the same calendar free and unmetered. |
| `market-data` (fintools-ai) | **Does not install.** `uvx mcp-market-data-server` resolves to something that dies on start-up. The failing name is left in place rather than deleted, so the next person does not spend the same twenty minutes. |
| `alpaca` | Needs a broker account, not a decision. Its role was settled long ago: tier 1, the venue's own book, the only source the risk engine may read. |

The `vendor-` rule still applies to what remains: those capabilities are in a
namespace **no allow-list grants**, so enabling one by accident registers tools
no agent can reach. `enabled: false` is one edit from wrong; the namespace is
the property that survives the edit.

#### Curation is not optional at this size

openbb offers **113 tools**. Registering them would be more than the rest of the
catalogue combined — the context-rot problem [[MCP Gateway]] §2 exists to
prevent, measured on our own config when curating FRED from 33 tools to 5 turned
selection from wrong to right. 24 are taken. maverick offers 37; 13 are taken.
yfinance offers 10 and all 10 are useful.

Selection was re-verified against the live 103-tool catalogue: **16 of 16** at
rank 1 across quotes, deep history, calendars, screens, estimates, corporate
actions, indicators, filings, macro, web, vault writes and the clock.

> [!danger] maverick-mcp sizes positions, keeps a portfolio, and backtests
> Three invariants, and the first is the one that matters:
> `portfolio_get_regime_adjusted_sizing`, `portfolio_risk_adjusted_analysis`
> (ATR stops and targets) and `portfolio_check_position_risk` are
> [[Safety Invariants]] §3 verbatim — **position sizing and risk arithmetic
> arriving over a socket from somebody else's code.** Genesis sizes its own
> positions and computes its own stops.
>
> **Not one of those names contains a verb the discovery tripwire catches.**
> "Sizing" and "risk" are not "order" or "delete". This is the clearest case in
> the catalogue for why the tripwire is the *second* line of defence and the
> explicit `tools:` block is the first — here it is the only one that works at
> all.
>
> Its portfolio store and trade journal are a second [[Trade Ledger]], which is
> proprioceptive drift with a schema. Its twelve backtesting tools are a second
> [[genesis-backtest-mcp]], which is two answers to *did this strategy work*
> and no way to tell which is authoritative.

> [!success] Three independent locks on Alpaca's order path
> More than [[Safety Invariants]] §1 asks for, and the right number.
>
> 1. **`ALPACA_TOOLSETS: "account,stock-data"`** — the *server* never exposes
>    the trading tools. `place_stock_order`, `close_all_positions` and
>    `cancel_all_orders` do not exist on the wire, so nothing downstream has to
>    be careful about them. Strongest of the three, and new.
> 2. **`explicit_tools`** — six tools named, so a toolset flag changed by hand
>    does not silently catalogue an order tool.
> 3. **`EXECUTION_NAMESPACES`** — a mutating `order.*` or `broker.*` capability
>    is refused outright until [[Pre-Trade Risk Engine]] exists, whatever
>    anyone wrote in the config.
>
> `ALPACA_TOOLSETS` lives in `env:` in the config file, **not** in the
> environment, because it is behaviour rather than a credential. A safety
> decision in someone's shell profile is invisible, unversioned and changed by
> accident; this one is in the file somebody reviews. `env:` and `env_keys:`
> may not name the same variable, and a test proves it.
>
> `ALPACA_PAPER_TRADE` defaults true and is left unset. Going live must require
> **both** a config change and a live key in a separate env file — two
> independent acts, never one flag.

### Keywords

`keywords:` on a server or a tool are words a person would use that the tool's
own name and description do not contain. FRED says "economic time series"; a
person says "CPI". This is the maintenance surface of a deterministic router and
it is a feature, not a patch: the gap is a missing fact about the catalogue, the
catalogue is ours, and stating it costs one line and is testable. The
alternative is a model call on every selection, forever.

> [!important] The vault is written through the filesystem, not the Obsidian app
> `mcp-obsidian` (the row further up) drives the Obsidian **app** through its
> Local REST API plugin, which means the app must be running. [[Biological
> Design]] is explicit that nothing in the autonomous loop may hard-depend on a
> GUI being open, and Phase 4's exit criterion — a daily brief waiting in the
> morning — is exactly that dependency. `obsidian-mcp` works on the vault
> directory instead. An Obsidian vault is a folder of markdown; treating it as
> one is what lets the fleet write while the app is closed.
>
> Four tools are deliberately **not** registered: `delete_note`, `move_note`,
> `remove_tag`, `rename_tag`. Genesis writes to the vault; it does not
> reorganise or destroy what you wrote. An agent that can delete notes can lose
> research nobody knew was gone.

> [!danger] tradingview-mcp ships `execute_order` and `kelly_position_size`
> Its 73 tools include `execute_order`, `execute_portfolio_trade`,
> `record_trade`, `close_trade`, `dispatch_trade_alert`, `kelly_position_size`,
> `risk_based_position_size` and `assess_trade_risk_full`.
>
> Registering it by server would be **two** invariants at once — §1, order
> placement four phases before the [[Pre-Trade Risk Engine]] exists, and §3,
> **position sizing and risk arithmetic arriving over a socket from somebody
> else's code**. Genesis sizes its own positions and computes its own stops.
>
> It would also be most of the catalogue on its own, which is the context-rot
> problem [[MCP Gateway]] §2 exists to prevent. Five named tools are
> registered: analysis and sentiment, nothing that prices, sizes or acts.

> [!warning] Exa's local npm server accepts `--tools=` and ignores it
> `exa-mcp-server@3.4.1` exposes `web_search_exa` and `web_fetch_exa` only, whatever
> you pass. `web_search_advanced_exa` and `agent_run` exist **only on the hosted
> endpoint**, enabled by its `tools=` query parameter — which is why this is the
> one server wired over HTTP rather than stdio.
>
> Hosted needs header auth, so [[MCP Gateway]]'s transport now sends headers,
> with values written as `${EXA_API_KEY}` and resolved from the environment at
> connect time. The config file holds the *name* of a secret, never the secret,
> and a rotated key takes effect on the next reconnect rather than the next
> restart.
>
> **Vendor docs are stale on auth.** Exa's own setup guide says "OAuth — no API
> key needed"; `docs.exa.ai/reference/exa-mcp` documents both `EXA_API_KEY` and
> the `x-api-key` header. The header is what works. OAuth would have been the
> wrong choice anyway: a browser sign-in in an overnight autonomous loop is the
> GUI dependency [[Biological Design]] forbids.

> [!note] `agent_run` takes minutes, and that changed the timeout model
> Exa's research agent plans, searches and synthesises before answering — 39s
> on a first real call, and it can run far longer. Timeouts are therefore
> **per-tool**, not per-server: 30s would kill it, and giving every tool 300s
> would let a hung quote lookup block its server's queue for five minutes.
>
> It belongs on a [[Task Bus]] lane. Nothing that takes minutes should be
> awaited by a spoken turn.

> [!note] Claude Code is not registered in the runtime gateway, and cannot be
> `claude mcp serve` exposes Bash, Edit and Write. [[Safety Invariants]] rules
> out shell servers in as many words: *a general shell tool makes every other
> allow-list advisory*. It stays a build-time tool, alongside
> `chrome-devtools-mcp` and `context7-mcp`. The intended direction is the
> reverse — Claude Code connects **to** [[genesis-memory-mcp]] as a client.

## Ruled out by decision

Not *bad servers*. Servers that a resolved question in [[Open Questions]] has
already excluded — recorded here so they are not re-proposed in Phase 4 as though
the question were still open.

| Server | Excluded by | Reason |
|---|---|---|
| ccxt-mcp, jesse-mcp, any crypto venue | §1 | v1 is US equities. Revisit only if §1 is reopened. |
| **mcp-trader** (`wshobson`) | upstream | **Archived 2025-08-24 by its author**, superseded by maverick-mcp. Not a judgement — it simply no longer exists as a maintained thing. Listed so it is not rediscovered from an old bookmark and researched twice. |
| maverick-mcp's `portfolio_*` sizing and risk tools | [[Safety Invariants]] §3 | Regime-adjusted sizing, ATR stops, pre-trade risk checks. Genesis sizes its own positions. **No discovery tripwire catches these names**, which is why the server is registered by explicit tool list. |
| maverick-mcp's `portfolio_journal_*` and `backtesting_*` | [[Trade Ledger]], [[genesis-backtest-mcp]] | A second record of what we hold and a second answer to "did this work". Two stores of one truth is proprioceptive drift with a schema. |
| openbb-mcp's `activate_tools` / `activate_category` | [[MCP Gateway]] | Tools that change which tools exist. The shape of the catalogue is decided at boot by the registry, not at runtime by a model. |
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

## How the danger above is actually enforced

`default_servers.yaml` ships every server **disabled**; step 7 of
[[MCP Gateway Build Plan]] turns them on one at a time through that checklist.
Three mechanisms carry the Alpaca warning from prose into structure:

1. **A server that can write must name every tool it wants registered.**
   `read_only: false` obliges an explicit `tools:` list, and an unnamed tool is
   silently refused. Silence is a refusal, not a default-open.
2. **The registry refuses mutating tools outright** unless constructed with
   `allow_mutating=True` — which is a Phase 7 act, for the server that owns the
   gate. A test enumerates the registered surface and fails if anything that can
   write appears.
3. **A read-only claim does not cover a dangerous verb.** `read_only: true` buys
   bulk registration, and it is an assertion about the server *as it was when it
   was written* — servers gain tools. A name-level tripwire (`order`, `buy`,
   `sell`, `cancel`, `liquidate`, `transfer`, `withdraw`, `delete`, …) refuses
   those even under the claim. It is a reflex, not a proof: deterministic and
   incapable of being argued out of firing, but only as good as its list. The
   real guarantee for anything that writes is mechanism 1."

## Related

[[MCP Gateway]] · [[Trading Corpus Index]] · [[Agent Contract]] · [[Agent — Watchdog]] ·
[[Futures Broker Options]] · [[Open Questions]] · [[Market Data Sources]] ·
[[Safety Invariants]] · [[Build Order]]
