---
title: Widget Catalog
tags: [ui]
status: building
implemented_by: [ui/src/components/EventStream.tsx, ui/src/components/SafetyFloor.tsx, ui/src/components/KillSwitch.tsx, ui/src/views/MemoryFabric.tsx, ui/src/views/ExecutionPath.tsx, ui/src/workspace/panels/heatmap.tsx, src/genesis/marketdata/heatmap.py, ui/src/workspace/panels/performance.tsx, src/genesis/marketdata/performance.py, ui/src/workspace/panels/trade.tsx, ui/src/api/useExecState.ts, ui/src/components/charts/PriceChart.tsx, ui/src/workspace/panels.tsx, ui/src/workspace/panels/browser.tsx]
---

# 🧩 Widget Catalog

The [[Dashboard]] is a widget grid. [[Repo — Gensis Terminal Official]] already has
many of these built — reuse rather than rewrite.

## Already built (in Gensis Terminal Official)

| Widget | File | Genesis use |
|---|---|---|
| Price chart | `price-chart.html` | The [[Dashboard]] chart pane; overlay [[Markup Spec]] annotations |
| Ticker manager | `ticker-manger.html` | Reference only — the watchlist was rebuilt as the `WL` panel ([[Watchlist Store]]): user-owned lists with sections, tier-3 day change, pick-to-chart into the TradingView panel. Screener-fed universes are a later wiring. |
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
| **Agent grid** | Fleet health roster. The main new one. |
| **Fleet view** | Live agent graph with lineage, memory and event edges ([[Fleet View]]) |
| **Genesis core** | The animated presence / corner sigil ([[Genesis Core]]) |
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

## Built — `HM` Heatmap

The Nasdaq-100 on the day as an echarts treemap: **area is market cap, colour
is the session's change**, grouped by GICS sector. It answers *"what moved, and
did it matter?"* in one picture — a 6% move in a $20B name and a 2% move in a
$4T one are the same row in a list and nothing like the same tile here.

Opened by code `HM` from the command line; `home: overview`, seeded into no
layout, because a whole-index picture is something you ask for
([[Operating Model]] §3, the canvas opens empty).

- **Tier 3, labelled on its face.** Yahoo's public feed via
  `src/genesis/marketdata/heatmap.py`, served at `GET /v1/market/heatmap`
  beside `/v1/market/quotes` — research and closed-market scaffolding, never a
  number the pre-trade engine reads ([[Safety Invariants]] §11).
- **The settled session, said out loud.** The payload carries Yahoo's
  `market_state`, and the panel's chip reads `SETTLED CLOSE` or
  `INTRADAY — NOT THE CLOSE`. Same stance as the watchlist and `CH`.
- **It does not poll** ([[UI Stack]] §9). One read on mount, and a refresh you
  press. The 15-minute server cache means the first read after the close is the
  close.
- **Membership is a static, hand-corrected table** — no free feed publishes
  index constituents, and asking a model would be a §10 confabulation. A member
  the feed cannot price is reported in `missing`, never drawn as a zero tile.
- **Colour is clamped at ±3%** so an ordinary session uses the full ramp instead
  of one earnings gap flattening the board. The legend at the foot is drawn by
  the same function as the tiles.
- Scroll to zoom, click a sector to drill into it. Clicking a tile drives the
  page's TradingView link group, as `WL` does — not `CH`, which holds no bars
  for most of these names.

## Built — `PFM` Performance

*What moved*, across two universes and four windows. Opened by code `PFM`;
`home: overview`, seeded into no layout.

Two toggles, not four panels: **view** is `barchart` or `heatmap`, **market** is
`stocks` (the eleven SPDR sector ETFs) or `futures` (front-month continuous
contracts, plus the cash indices a futures board conventionally shows beside
them). Fed by `src/genesis/marketdata/performance.py` at
`GET /v1/market/performance?asset=`.

- **The sector table is imported, not retyped.** `SECTOR_ETFS` already has one
  right answer in `agents/charting/data_viz.py`; importing it means the board
  the operator reads and the chart [[Agent — Data Viz]] draws cannot drift.
- **Every futures ticker was verified against the live feed.** Yahoo answers an
  unknown contract with an empty frame rather than an error, so an unchecked
  table yields a board quietly missing rows. Canola, SOFR, ethanol and gasoil
  have no Yahoo symbol and are absent by decision, recorded in the module.
- **A cash index is not a future.** `^VIX`, `^GDAXI`, `^STOXX50E`, `DX-Y.NYB`
  and `BTC-USD` carry `kind: "index"`; the rest are `future`. One settles, the
  other merely closes.
- **`settled` is reported, not assumed.** A Globex session opens Sunday evening
  and is dated for the following day, so on a Monday holiday the sector board
  carries Friday's settled close while the futures board carries a session still
  trading. The chip reads `SETTLED <date>` or `IN SESSION <date>` accordingly —
  a number that moves under a label saying it cannot is the drift
  [[Biological Design]] calls proprioceptive.
- **No chart library.** `HM` earns echarts because a squarified treemap is real
  geometry; bars whose width is a percentage and tiles in a grid are CSS, in
  fewer lines than configuring a library to do them.
- **Colour is `changeColour`** (`ui/src/lib/format.ts`), shared with `HM` and
  clamped per window — ±3% at 1D, ±12% at 3M, because one clamp would paint
  every 3M bar the same green. The clamp in force is named above each column.
- **Refreshes on the bell, and does not poll** ([[UI Stack]] §9). Stocks re-read
  when the daemon emits `market.close`, so holidays and half-days are handled
  where the real exchange calendar already lives. Futures have no such event
  (the daemon's calendar is XNYS-only — [[Open Questions]] §1), so they get one
  self-rescheduling timer to the 17:00 ET CME settlement. Plus a refresh button.
- Bars are ranked per column, because "what led" is a different ranking in each
  window; tiles keep a fixed board order, because a name that moves between
  reads cannot be found by position.

`market.open`/`market.close` were already emitted by `Daemon.tick` and named in
no UI type. They are now `MarketSession` in `ui/src/types/events.ts`.

## Built — `MOV` Index movers

Top five gainers and losers for the S&P 500, Nasdaq-100, Dow or any Select
Sector SPDR, beside an echarts sunburst (sectors → members, angle = index
weight, colour = `changeColour`). Click a sector to narrow everything to it.
Membership is the SPDR fund's own daily holdings file. Full spec:
[[Index Movers]].

## Built — `SCR` Screener

The S&P 500 fundamentals screen being built in chat: criteria chips with ✕,
the agent's readings and question, a sortable matches table, a plain-English
refine box that talks through Ask Genesis, and an editable `scr` expression.
Updates live on `screen.updated`. Full spec: [[Screener]].

## Built — `WEB` Browser

A real browser in a dock panel: a headless Chromium runs beside the daemon with
its own persistent profile, the panel shows a `multipart/x-mixed-replace` JPEG
stream of its viewport, and mouse and keyboard events post back over HTTP. Any
site, your own logins, the vendor's own drawing tools — the things an embedded
widget or an iframe cannot give you, because most of the web refuses to be
framed.

It breaks the widget contract below on one clause and it is worth being plain
about which: **it does not render from pushed state**, because its state is a
web page and there is no event that carries one. Everything else holds — it
declares its degraded case (`Absent` with the reason the browser gave), it is
not seeded into any layout, and it holds no authority over anything.

Not seeded anywhere, per [[Operating Model]] §3: a browser nobody asked for is
the most unrequested screen there is. Type `WEB`. Full spec: [[Web Access]]
§The presentation surface.

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

## Trade (`TRD`) and order lines (2026-09-14)

`TRD` follows the workspace symbol the chart is on: order ticket (market or
limit, stop or trailing stop in points, target in points, GTC/DAY), a confirm
bar naming contract, size and worst case, or one-click when that mode is on;
the position with IBKR's live P&L and a protected / NO STOP chip; flatten
(arm-then-fire), close 1, stop to breakeven, trail; working orders with inline
price edits and cancel; halt and reconciliation banner with adopt and resume;
today's execution quality. `CH` draws the position's average price and every
working entry, stop, target and trail as price lines, from the same pushed
`execution.state` the panel reads.

## Related

[[Dashboard]] · [[UI Stack]] · [[Fleet View]] · [[Genesis Core]] · [[Desktop Shell]] ·
[[Event Schema]] · [[Repo — Gensis Terminal Official]] · [[Repo — gensis-agents]]
