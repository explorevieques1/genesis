---
title: Charting Engine
tags: [architecture, charting]
status: spec
implemented_by: []
---

# Charting Engine

Two renderers, one source of truth. The source of truth is the [[Markup Spec]] —
a declarative object. Everything else renders it.

## Renderers

| Renderer | Output | Headless? | Used by |
|---|---|---|---|
| **Server-side** | PNG / SVG from an OHLCV frame + [[Markup Spec]] | yes | vault notes, voice-reply attachments, [[Agent — Pattern Recognition]] vision input, journal entry/exit snapshots |
| **Client-side** | interactive chart in the browser | yes | [[Dashboard]] chart pane |
| **TradingView Desktop** | the spec compiled to a Pine indicator, applied to your live chart | **no** | you, at the desk — via [[genesis-tradingview-mcp]] |

All three consume the identical spec, so what you see on the dashboard is exactly
what went into the vault and exactly what the vision model read. No drift between
views.

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
[[Agent — Pattern Recognition]] · [[Agent — Level Watcher]] · [[Dashboard]]
