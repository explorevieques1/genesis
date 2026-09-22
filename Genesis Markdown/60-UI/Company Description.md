---
title: Company Description
tags: [ui, research]
status: built
implemented_by:
  - ui/src/workspace/panels/company.tsx
  - tests/company/test_describe.py
  - ui/src/api/client.ts
  - src/genesis/company/profile.py
  - src/genesis/company/providers/yfinance.py
  - src/genesis/marketdata/quotes.py
  - src/genesis/server/reads.py
  - src/genesis/server/watchlist_routes.py
---

# 🏢 Company Description

One issuer on one page, laid out like a terminal description screen. The `CO`
module (title *Company*), home `research`, spawnable into any workspace. The
ticker is the workspace's `ticker` selection, so other research panels follow it.

## What it is on the map

A sense organ's display, not an organ. Everything is afferent and tier 3
([[Market Data Sources]]); nothing on it reaches [[Pre-Trade Risk Engine]].
No model runs anywhere on this page — it is all lookup and arithmetic.

## Layout

| Region | Data | Source |
|---|---|---|
| Header | name, `EQ`, symbol · sector · industry, website, price, change, volume, quote date | `info` |
| About | first two sentences of the business summary | `info` |
| Chart | 1D / YTD / 1Y / 5Y closes with volume | `GET /v1/market/history` (yfinance, 15 min cache) |
| EPS | fiscal year × quarter grid, plus annual row | see below |
| Relations | Customers / Suppliers / Competitors / Partners headings | **no free source — shown empty, never guessed** |
| Latest News | ten headlines with age, open in browser | profile `news` (tier 4 text) |
| Top Holders | institutional holders, $value (shares), top 10 → 20 | `institutional_holders` |
| Functions | `TV`, `NW`, `CR`, `AI` — open real modules via the dock API | — |
| Stats rail | CEO, HQ, employees, sector, sub-sector · price, shares out, market cap, currency, float, EV · insiders, institutions · P/S, P/B, EV/EBITDA, EV/R, trailing and forward P/E · trailing, forward and 5-year yield, payout, ex-div and pay dates · beta, short shares, short ratio | `info` |

## Rules

1. **The page reads the store; it does not fetch a profile.**
   `GET /v1/company/{symbol}/description` returns `describe(profile)` from the
   cache or an absent envelope. *Look up* and *refresh* post `<TICKER> profile`
   to `/v1/command` — the same door as typing it ([[Operating Model]] parity rule).
2. **The UI formats; it does not compute.** Change, change %, forward yield and
   every EPS cell are computed in `describe` on Decimals.
3. **Actual and estimate never share a colour.** Reported diluted GAAP EPS is
   green; analyst consensus mean (usually non-GAAP) is plain. The annual cell is
   a sum only when all four quarters are reported; otherwise it is the `0y` /
   `+1y` consensus.
4. **Fiscal year is named for the year it ends.** Quarter = months after the
   fiscal-year-end month ÷ 3, so NetApp's July quarter is Q1 of the next FY.
5. **Vendor units are normalised server-side.** `dividendYield` and
   `fiveYearAvgDividendYield` arrive in percent, `trailingAnnualDividendYield`
   and ownership as fractions (observed 2026-09-13).

## Not built

- Supply-chain relations — no free source.
- Company logo — a monogram tile stands in; fetching a logo would call a third party per render.
- Estimates beyond `+1q` per quarter — yfinance gives only two quarters ahead.

## Related

[[Company Data Model]] · [[Market Data Sources]] · [[News]] · [[Workspaces]] ·
[[Widget Catalog]] · [[Operating Model]]
