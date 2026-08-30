---
title: Widget Catalog
tags: [ui]
status: spec
implemented_by: []
---

# 🧩 Widget Catalog

The [[Dashboard]] is a widget grid. [[Repo — Gensis Terminal Official]] already has
many of these built — reuse rather than rewrite.

## Already built (in Gensis Terminal Official)

| Widget | File | Genesis use |
|---|---|---|
| Price chart | `price-chart.html` | The [[Dashboard]] chart pane; overlay [[Markup Spec]] annotations |
| Ticker manager | `ticker-manger.html` | Watchlist, fed by [[Agent — Screener]] |
| Trade calendar | `trade-calendar.html` | Journal at a glance; heatmap by day P&L |
| Account stats | `account-stats.html` | Positions and P&L from [[Agent — Position And PnL Accountant]] |
| Consistency calculator | `consistency-calc.html` | Direct fit for the [[Prop Firm Rules]] consistency rule |
| Strategy library | `strategy-library.html` | Browse [[Strategy Schema]] objects and their backtests |
| Indicator library | `indicator-library.html` | Reusable indicator scripts |
| Calculator V2 | `calculator V2.html` | Position sizing — wire to [[Agent — Portfolio And Allocation]] so it uses the real limits |
| Timer, clock, timezone | | Session awareness |
| Sticky notes | `sticky.html` | Quick capture → vault `00-Inbox/` |
| Dice, browser, help | | Utility |

Widgets are declared with a `.json` manifest alongside the HTML — keep that pattern.

## New widgets Genesis needs

| Widget | Purpose |
|---|---|
| **Agent grid** | Fleet status. The main new one. |
| **Activity feed** | Streaming plain-English agent activity |
| **Idea board** | Ranked idea cards with chart thumbnails and actions |
| **Approval queue** | Pending proposals with risk detail and expiry countdown |
| **Risk gauges** | Portfolio heat, daily loss headroom, drawdown — the glanceable three |
| **Prop-firm bars** | Headroom per rule, live ([[Agent — Prop Firm Guard]]) |
| **Transcript** | Searchable conversation with `trace_id` links |
| **Memory viewer** | Knowledge graph, lessons, beliefs |
| **Level watch** | Active levels sorted by distance in ATR |
| **Drift monitor** | Live vs. backtest per strategy ([[Agent — Backtest Vs Live Drift]]) |
| **Kill switch** | Always visible, direct to the kill-switch process |

## Widget contract

Every widget:

- Declares the [[Event Schema]] events it subscribes to
- Renders from pushed state — it never polls, and never holds authority
- Handles the degraded case explicitly: stale data must *look* stale
  ([[Error Handling And Degradation]])
- Works in the dark theme, matching [[Charting Engine]] renders
- Survives a refresh with no state loss — everything lives in [[Memory Fabric]]

That third rule is not cosmetic. A P&L widget that shows a confident number from a
stale feed is actively dangerous.

## Reuse before building

Check `Gensis Terminal Official/widgets/` first. Several of these are done, styled,
and working — the design-system zips in [[Repo — gensis-agents]] `New Downloads/`
carry the visual language. Building a second price chart is wasted effort.

## Related

[[Dashboard]] · [[Desktop Shell]] · [[Event Schema]] ·
[[Repo — Gensis Terminal Official]] · [[Repo — gensis-agents]]
