---
title: Index Movers
tags: [ui, overview, marketdata]
status: built
implemented_by:
  - src/genesis/marketdata/index_map.py
  - ui/src/workspace/panels/movers.tsx
  - tests/marketdata/test_index_map.py
  - ui/src/workspace/modules.ts
  - ui/src/api/client.ts
  - src/genesis/marketdata/heatmap.py
  - src/genesis/server/watchlist_routes.py
---

# 🥧 Index Movers

One index on the day: who is up, who is down, and how much of the index they
are. The `MOV` module (*Index movers*, aliases *movers, gainers, losers, market
map*), home `overview`, seeded into no layout — the canvas opens empty.

## What it is on the map

A sense organ's display. Afferent, tier 3 ([[Market Data Sources]]), no model
anywhere — membership is a file, prices are a screen, the rest is arithmetic in
Python. Nothing here reaches [[Pre-Trade Risk Engine]].

## Universes

| Code | Membership | Slice angle |
|---|---|---|
| `SPX` S&P 500 | State Street **SPY** daily holdings xlsx | fund weight |
| `NDX` Nasdaq-100 | hand-corrected table in `marketdata/heatmap.py` (Invesco publishes no plain QQQ file) | market-cap share |
| `DJIA` Dow Jones | State Street **DIA** holdings | fund weight (price-weighted index) |
| `SML` S&P 600 Small Cap | State Street **SPSM** holdings | fund weight |
| `XLK XLF XLV XLY XLC XLI XLP XLE XLU XLRE XLB` | that Select Sector SPDR's holdings | fund weight |

The Russell 2000 is the small-cap index a trader asks for, but iShares serves the
IWM holdings file only to a browser, so `SML` is the S&P 600 — same asset class,
same SSGA feed as every other universe here. Small caps have no sector breakdown:
the SPDR sector funds hold only S&P 500 names and the SSGA file's own sector
column is blank, so `SML` draws as one flat ring.

Sectors for S&P and Dow members come from **which sector SPDR holds them** — the
eleven funds partition the S&P 500 by GICS sector. Holdings are cached 12 hours;
futures, cash and placeholder lines are dropped by ticker shape.

Prices: one Yahoo equity screen across NASDAQ, NYSE, Cboe and NYSE American,
1,500 names deep (~1.5 s, 15 min cache), shared by every universe — 5,000 deep
(~7 s) for `SML`, whose members begin below that first page; `fast_info`
for the few it misses. A member with no price is listed in `missing`, never drawn
as a flat slice.

## Layout

- **Header:** a **Sector** dropdown of the eleven GICS sector names (a fund ticker is not a name anyone reads), then a chip per whole-market universe — S&P 500, NAS 100, DOW, S&P 600 — then Movers / All, Map / Table, member count, refresh.
- **Map:** echarts sunburst. Inner ring = sectors, outer ring = members; angle = weight, colour = `changeColour`. The centre shows the group code and its **weighted member change**.
- **Movers / All:** *Movers* (default) draws only the current group's top five gainers and losers, the same names as the right rail, labelled by symbol only. Sectors with no mover are dropped, and the colour scale stretches to the largest move so the gradient stays readable. *All* draws every member.
- **Size:** picks what a slice's angle measures: index weight (default), market cap, price, session volume, dollar volume (close × volume, computed server-side), absolute change, or equal. A member with no figure for the chosen basis is left out, never drawn as zero, and the footer names the basis in use. The hover card shows all of them.
- **Hone in:** clicking a sector narrows the pie, the centre figure, the lists and the table to that sector. *← all of …* goes back out. Sector ETFs have a single ring.
- **Table:** members of the current group sorted by change.
- **Right rail:** TOP GAINERS and TOP LOSERS (five each, strictly up / strictly down), advancers vs decliners.
- **Click a stock:** sets `tvSymbol` and `ticker`, so `TV` and [[Company Description]] follow.
- **Footer:** tier 3, settled vs intraday, weight basis and holdings date, unpriced names.

## Rules

1. **Membership is never from a model or from memory.** A fund file or the
   hand-corrected NDX table. An unreachable file is an absent envelope.
2. **The centre figure is the members' weighted move, not the ETF's print.**
   Labelled as such — cash, fees and unpriced names make them differ.
3. **Server computes, UI draws.** Group change, advancers, decliners and top
   five are in `summarise_group`.

`GET /v1/market/movers?index=<code>`.

## Related

[[Widget Catalog]] · [[Market Data Sources]] · [[Company Description]] ·
[[Workspaces]] · [[Operating Model]]
