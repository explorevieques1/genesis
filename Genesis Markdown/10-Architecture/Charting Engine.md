---
title: Charting Engine
tags: [architecture, charting]
status: built
implemented_by: [src/genesis/charting/render.py, src/genesis/charting/theme.py, src/genesis/charting/levels.py, src/genesis/charting/indicators.py, tests/charting/test_render.py, tests/charting/test_levels.py, ui/src/workspace/panels/tradingview.tsx, ui/src/workspace/panels/charting.tsx, ui/src/components/charts/SymbolBar.tsx, src/genesis/server/symbol_routes.py, tests/test_symbol_routes.py, src/genesis/research/setup.py, tests/research/test_setup.py]
---

# Charting Engine

Two renderers, one source of truth. The source of truth is the [[Markup Spec]] —
a declarative object. Everything else renders it.

## Renderers

| Renderer | Output | Headless? | Data | Used by |
|---|---|---|---|---|
| **Server-side** | PNG / SVG from an OHLCV frame + [[Markup Spec]] | yes | ours | vault notes, voice-reply attachments, [[Agent — Pattern Recognition]] vision input, journal entry/exit snapshots |
| **Client-side** (`CH`) | interactive chart in the browser | yes | ours | [[Dashboard]] chart pane |
| **TradingView Desktop** | the spec compiled to a Pine indicator, applied to your live chart | **no** | tier 2 | you, at the desk — via [[genesis-tradingview-mcp]] |
| **TradingView embed** (`TV`) | their Advanced Chart, in a panel | no — needs the public internet | **theirs, tier 3** | reaching a symbol Genesis does not hold |

The first three consume the identical spec, so what you see on the dashboard is
exactly what went into the vault and exactly what the vision model read. No
drift between views.

**The fourth consumes nothing of ours, and that is the point.** See below.

The third renderer is the one you look at all day, and the one that cannot run
without a GUI. **Nothing autonomous may depend on it** — the 3am
[[Daemon And Cadence|market-closed loop]] marks up charts through the headless
renderer, and TradingView catches up when you are back at the desk.

> [!tip] Compile, don't click
> The Desktop renderer works by compiling the spec into a Pine indicator and
> loading it through the editor — not by simulating mouse drags on the chart.
> Text and keystrokes are a far more robust automation surface than price→pixel
> math, and Genesis ends up owning exactly one indicator, so your hand-drawn
> objects are never touched. See [[genesis-tradingview-mcp]].

Client lineage: `price-chart.html` from [[Repo — Gensis Terminal Official]] (lightweight-charts style).

## Two client charts, and why

`CH` is the **chart of record**: `lightweight-charts` over bars in the store,
with a provenance chip and a trust tier on every series. It never draws a
symbol Genesis does not hold — a box that accepts `TSLA` and shows an empty
chart teaches the operator only that the UI accepts text. What it does instead
is **load**: see §Symbol search.

### Symbol search

The top of `CH` is a symbol bar (`ui/src/components/charts/SymbolBar.tsx`): a
palette-style search, the timeframe row `1m 5m 15m 30m 1H 4H 1D 1W` (IBKR's
bar sizes), and a stream toggle.

- **Held first, then IBKR.** Typing filters the bar store instantly (no gateway
  needed) and, 300 ms after the last keystroke, asks `GET /v1/market/search`,
  which runs IBKR's `reqMatchingSymbols` and expands any futures root into its
  next six dated contracts via `reqContractDetails`. Each match carries the
  canonical id IBKR's directory produced — `STK→EQ`, `FUT→FUT` (dated only),
  `IND→IDX`, `CASH→FX`, `CRYPTO→CRYPTO`. Options, warrants, bonds and CFDs have
  no symbol id and are not offered. Deterministic, never a model
  ([[Operating Model]] §4); ambiguous matches are listed side by side with
  exchange and currency. "All IBKR symbols" means *searchable*, not *listed*:
  IBKR has no enumerate-everything call.
- **Selecting loads.** A symbol or timeframe switch reads the store at once and,
  beside it, `POST /v1/market/load` fills the series through the `chart_markup`
  chain — the same `StoreBarSource.fetch` `genesis chart <symbol> <tf>` runs
  (the by-hand door). The chart re-reads only when the load brought a newer
  bar. A symbol no feed serves shows the reason; the answer's `source` and
  `tier` ride on every bar as always.
- **Streaming is `feed.live`.** The toggle (`+ live` / `● live`) adds or
  removes the current *symbol* through `POST /v1/broker/feed` — the same list
  `LD` and `CON` edit and the live session reads, per symbol like `LD`, at the
  chart's timeframe. There is no second path to a live series.
- **One IBKR worker thread** serves search and load: `ib_async` binds a
  connection to its thread's loop, and IBKR paces symbol lookups at ~1/s.
  Client id is the adapter's `+3` (live session `+1`, check `+2`).

`TV` (`ui/src/workspace/panels/tradingview.tsx`) is TradingView's Advanced Chart
embedded in a panel. It brings its own feed, so **any** symbol on their platform
charts instantly with no ingest, no adapter and no storage — the full drawing and
indicator surface, for the cost of a script tag.

Both exist because they answer different questions. *"What does the data I
collected actually look like, and where did it come from?"* is `CH` and can only
be `CH`. *"Show me the weekly on a name I have never ingested"* is `TV` and would
otherwise be a two-hour ingest job.

> [!warning] Nothing on the `TV` chart is Genesis data
> [[Market Data Sources]] rates a public third-party feed **tier 3** — research,
> screening and closed-market work, **never** an intraday execution decision —
> and [[Safety Invariants]] §11 keeps tier 1 as the only thing the
> [[Pre-Trade Risk Engine]] reads. A price on this chart has no provenance line,
> no gap detection and no reconciliation, and **may not be cited as a number
> Genesis knows**. The panel carries a tier-3 chip on its face, because the
> person reading a chart is not reading this note.

Three constraints the panel holds, each with its reason:

- **Symbol resolution is a table, not a guess.** `EQ:XNAS:AAPL` → `NASDAQ:AAPL`
  by deterministic lookup ([[Operating Model]] §4). The table covers only
  exchanges with an unambiguous TradingView spelling; everything else surfaces
  *"no TradingView exchange known for XLON"* and leaves the chart alone. A wrong
  guess is worse than no guess — a chart the operator trusts and should not.
- **Futures are absent from the table on purpose.** `FUT:CME:ES:2025-12` is one
  dated contract; TradingView's `ES1!` is a continuous series. Those are
  different price series, which is exactly the conflation `normalize.py` exists
  to prevent, and it does not become acceptable because it is only a picture.
- **It verifies that it rendered.** `onerror` does not fire when the script
  loads and the iframe is then blocked, so the panel checks for the iframe and
  reports honestly when there is none — [[Biological Design]] §3, never build an
  actuator without the sense that confirms it acted. A grey rectangle claiming
  nothing is wrong is the failure this rule is about.

**This is not [[genesis-tradingview-mcp]].** That server drives the Desktop app
over CDP to read your paid tier-2 subscription and to put Genesis's
[[Markup Spec]] on your real chart. This is an embedded widget on a public feed
with no read path back. They share a vendor and nothing else.

## Level computation

Genesis computes structure itself rather than trusting a screenshot.

| Level type | Source |
|---|---|
| Support / resistance | swing-point clustering with touch counts and recency weighting |
| VWAP / anchored VWAP | computed from intraday volume; anchors at session open, prior high/low, or an event |
| Opening range (ORB) | first N minutes' high/low — `mcp-market-data-server` |
| Fair value gaps | three-bar imbalance detection — `mcp-market-data-server` |
| Volume profile / POC / value area | `mcp-market-data-server` |
| Prior day / week H-L-C | trivially derived, always drawn |
| Fibonacci | from the dominant swing chosen by structure, not by hand |
| Order blocks | last opposing candle before an impulsive move |
| Trendlines | fitted to swing points with a minimum-touch threshold |
| Moving averages / bands | standard, configurable set |

Indicator math should be **borrowed, not reinvented** — see [[Trading Corpus Index]]:
`nautilus_trader/indicators/`, `vectorbt/indicators/factory.py`,
`mcp-market-data-server` for the structural ones.

### Where levels come from

Both computed and fetched, for different jobs.

| Use | Source | Why |
|---|---|---|
| Anything written to a [[Markup Spec]] or tracked in [[Knowledge Graph]] | **computed here** | Level-outcome tracking needs provenance and determinism. A level whose derivation we can't reproduce can't be scored later. |
| Quick answers, cross-checks, second opinions | `tradingview-mcp` TA tools, or read from the desktop app | Free, instant, and already paid for ([[Market Data Sources]]) |

Fetching a level is cheap; **it is not cheaper in the way that matters.** Computing
S/R from an OHLCV frame is milliseconds — compute was never the bottleneck. Getting
the bars is what costs money, which is why [[genesis-tradingview-mcp]] has a read
path into the live subscription.

So: read *bars* from wherever they are cheapest, compute *structure* locally. When
a fetched level and a computed one disagree, keep the computed one and log the
disagreement — a persistent gap means the scoring in `compute_levels` needs work.

## Rendering rules

Charts are read by two audiences — you, and a vision model. Both need clarity.

- Dark theme, high contrast, no gridline clutter.
- Every level labelled with its **price** and its **type** ("PDH 122.10").
- Zones as translucent rectangles; lines as solid; projections dashed.
- Entry / stop / target drawn as a risk-reward box when the chart backs an
  [[Idea Schema|idea]].
- Timestamp and timeframe burned into the corner — a chart with no date is useless
  in a journal six months later.
- Fixed output size (e.g. 1600×900) so vision-model input is consistent.

## Multi-timeframe composite

[[Agent — Multi Timeframe]] renders 4–5 timeframes into one image with a shared
symbol header and an alignment score. Layout: monthly/weekly small on the left,
the trading timeframe large on the right.

## PineScript path

Separate output, same idea source. [[Agent — Strategy Author]] can emit a PineScript
alert or indicator from a strategy or markup spec — condition builder, filters,
lookback confirmation, cooldown gate.

Lineage: [[Repo — gensis-agents]] `agents/alert-agent` (20+ condition types, AND/OR/
IF-THEN logic, volume/ATR/trend/session filters, three-category notebook) and the
`.pine` files in its `New Downloads/`.

## Storage

- PNG → vault `20-Charts/`, filename `SYMBOL-YYYY-MM-DD-TF.png`
- Spec → [[Memory Fabric]], referenced by id from the idea and journal notes
- Specs are **immutable**; a re-mark creates a new spec that links to its parent

This is what makes "show me how that level held up" answerable — you re-render the
old spec against new data.

## Acceptance criteria

- The same spec renders to visually equivalent server and client charts.
- A rendered chart is legible enough that a vision model correctly names the
  marked levels ≥90% of the time on an eval set.
- Render of a 1-year daily chart with 12 levels completes in <2 s.
- Every chart in the vault is re-renderable from its stored spec alone.

## Related

[[Markup Spec]] · [[Markup Spec Schema]] · [[Agent — Chart Markup]] ·
[[Agent — Pattern Recognition]] · [[Agent — Level Watcher]] · [[Dashboard]] · [[Chart Tools]]
