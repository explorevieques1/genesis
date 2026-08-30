---
title: genesis-tradingview-mcp
tags: [mcp, charting, data]
status: spec
implemented_by: []
---

# genesis-tradingview-mcp

**Control of the TradingView Desktop app, and a read path into the live data
subscription already running inside it.**

TradingView is the primary charting surface — the app open on the desk all day,
with a paid live feed. Genesis runs alongside it rather than replacing it: it
drives the app the way a person would, and reads what the app already knows.

> [!important] TradingView is a hand, not a brain
> Genesis computes its own levels ([[genesis-charting-mcp]]) and holds its own
> [[Markup Spec]]. This server *actuates* — it puts Genesis's conclusions on your
> screen and fetches quotes from a feed you already pay for. When TradingView is
> closed, agents keep working, degraded ([[Error Handling And Degradation]]).
> Nothing in the autonomous loop may hard-depend on a GUI being open.

## Why it exists

Two jobs that no headless server can do:

1. **Act on the app you actually use.** *"Open TradingView and mark key support and
   resistance on gold"* has to move your chart, not render a PNG in a folder.
2. **Read the feed you already have.** Real-time data is the project's most likely
   cost bottleneck ([[Open Questions]] §6). A live subscription is already running;
   *"what's the current high of day on NQ"* should read it rather than buy the same
   tick twice.

The second is about **data access and cost, not compute.** Computing levels from
an OHLCV frame is milliseconds — that is never the bottleneck. Getting the bars in
the first place is what costs money. See [[Market Data Sources]].

## Transport

TradingView Desktop is an Electron app. Launch it with a remote debugging port and
attach over the Chrome DevTools Protocol:

```
tradingview --remote-debugging-port=9222
playwright.chromium.connect_over_cdp("http://localhost:9222")
```

> [!warning] Verify this before building anything else
> Electron apps can disable remote debugging, and if this door is shut the whole
> approach changes. **A 30-minute spike gates this entire server.** Do it first;
> record the result here.

## Drawing: compile to Pine, don't simulate clicks

The obvious implementation — select the trendline tool, click two points — depends
on price→pixel math, pan position, and zoom state. It breaks constantly.

**Instead: compile the [[Markup Spec]] into a Pine indicator and load it through
the editor.** Every operation becomes text and keystrokes, which is the robust
surface. `compile_pine` already exists in [[genesis-charting-mcp]].

Three things fall out of this for free:

| | |
|---|---|
| **Your drawings are untouched** | Genesis owns exactly one indicator. You own your chart. Clearing its markup is removing one indicator, not hunting objects. |
| **Deterministic and re-renderable** | The same spec produces the same script — which is what level-outcome tracking in [[Knowledge Graph]] requires. |
| **One mechanism, both requests** | *"Mark S/R on gold"* and *"write me a Pine script for daily highs and lows on ES"* differ only in whether Genesis wrote the script from a spec or from your words. |

Lineage: [[Repo — gensis-agents]] `agents/alert-agent` for the condition
vocabulary, and `pine-forge` for the builder UI.

## Tools exposed

### Navigation
| Tool | Notes |
|---|---|
| `open_symbol` | Switch the active chart |
| `set_timeframe` | 1m … 1M |
| `set_layout` | Named saved layouts, multi-pane |

### Markup
| Tool | Notes |
|---|---|
| `apply_markup` | [[Markup Spec]] → Pine → replaces Genesis's indicator |
| `clear_markup` | Removes **only** Genesis's own indicator |
| `write_pine` | A named script → editor → save |
| `add_to_chart` | Apply a saved script |
| `read_pine` | Read a script you wrote, so Genesis can iterate on it |

### Read
| Tool | Returns |
|---|---|
| `quote` | Last, bid/ask, change, session high/low — the live-subscription read path |
| `ohlcv` | Bars for a symbol/timeframe, for local computation |
| `watchlist` | Your watchlist symbols |
| `screenshot` | Chart image — read-back verification, and vision input |

### Explicitly absent
**No tool touches the Trade panel.** See the hard rules below.

## Hard rules

### 1. Nothing here can reach a broker
TradingView Desktop has broker integration. An automation server that can click is
an automation server that can click **Buy** — a path around
[[Pre-Trade Risk Engine]], which [[Safety Invariants]] §1 forbids structurally.

Enforced at the tool surface, not by prompting: no order tool is defined, the
Trade panel is a denied selector, and any action resolving into it aborts and logs.
Orders go through [[genesis-execution-mcp]]. Only.

### 2. Verify every mutation by reading back
The app is a black box. Act → `screenshot` → confirm the expected state. A
mismatch reports `degraded`; it never reports success.

### 3. Never the risk engine's price source
A quote scraped from a GUI is fine for answering *"what's the high of day"*. It is
not fine for sizing a position or evaluating a stop. [[Pre-Trade Risk Engine]]
uses the broker's own feed, always. See [[Market Data Sources]].

### 4. Degrade, never block
TradingView closed, updated, or unresponsive → the tool returns `unavailable` and
the agent proceeds without it. The headless renderer in [[genesis-charting-mcp]]
covers vault notes, journal snapshots, and vision input at 3am when no GUI is
running.

## Fragility budget

This server automates someone else's UI. It **will** break on their updates. Design
for that:

- Every selector in one config file, not scattered through the code
- A `self_test` tool that exercises each interaction and reports what broke
- [[Agent — Watchdog]] runs it on a schedule and after any TradingView update
- Failures are `degraded`, never `fatal` — nothing in the execution path depends
  on this server

## Access

Allow-listed to [[Charting Family]], [[Agent — Market Analyst]],
[[Agent — Strategy Author]], and the [[Orchestrator]] for direct voice commands.
**Never** to [[Execution Family]].

## Acceptance criteria

- The CDP spike is recorded above with a definite yes/no.
- `apply_markup` renders a spec onto the live chart, and `clear_markup` removes it
  without disturbing any hand-drawn object.
- `quote` on a liquid symbol matches the app's displayed value.
- With TradingView closed, every allow-listed agent still completes its task and
  reports `degraded` — no exceptions, no hangs.
- No defined tool can reach an order path. Asserted by a test that enumerates the
  tool surface.
- `self_test` detects a deliberately renamed selector.
- A voice request — *"mark support and resistance on gold and tell me the long-term
  trend"* — moves the chart and returns a spoken synopsis.

## Related

[[Market Data Sources]] · [[genesis-charting-mcp]] · [[Charting Engine]] ·
[[Markup Spec]] · [[MCP Gateway]] · [[MCP Server Catalog]] ·
[[Safety Invariants]] · [[Agent — Chart Markup]] · [[Agent — Strategy Author]] ·
[[Repo — gensis-agents]]
