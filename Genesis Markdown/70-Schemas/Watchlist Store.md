---
title: Watchlist Store
tags: [schema, ui]
status: built
implemented_by:
  - src/genesis/watchlist/__init__.py
  - src/genesis/watchlist/store.py
  - ui/src/workspace/panels/watchlist.tsx
  - src/genesis/server/watchlist_routes.py
  - src/genesis/marketdata/quotes.py
  - src/genesis/commands.py
  - tests/test_watchlist.py
---

# 👁 Watchlist Store

The trader's own symbol lists. A local SQLite database at
`<memory_dir>/watchlists.db`, opened per request like every other read store,
`ON DELETE CASCADE` from a list to its members.

## Why it is its own store

A watchlist is not market data. The [[Charting Engine]]'s `SR`/Series inventory
is the set of OHLCV series Genesis has *deliberately ingested*, provenance
attached — a symbol appears there because bars for it exist on disk. A watchlist
is the opposite direction: a pointer at symbols the trader wants to keep an eye
on, most of which Genesis holds no bars for. So it follows the [[Conversation
Store]] pattern, not the marketdata one:

- Not a source of record. Losing this database costs the trader their lists and
  nothing else — every entry is just a ticker string.
- The trader's own data, theirs to edit. The write routes sit in
  `watchlist_routes.py`, apart from `reads.py` because they **act**
  ([[Biological Design]] §2), but they import no execution code and reach no
  order path — the same argument [[Research Canvas]] and [[Conversation Store]]
  make. Not the [[Pre-Trade Risk Engine]] gate.

## Tables

```sql
watchlists (
  id       TEXT PRIMARY KEY,   -- ULID, prefix "wl"
  name     TEXT NOT NULL,
  created  TEXT NOT NULL,       -- ISO-8601 UTC, seconds
  sort     INTEGER              -- order in the switcher
)

watchlist_members (
  id       TEXT PRIMARY KEY,   -- ULID, prefix "wm"
  list_id  TEXT REFERENCES watchlists(id) ON DELETE CASCADE,
  symbol   TEXT NOT NULL,       -- canonical ticker, via company.symbols.normalise
  grp      TEXT NOT NULL DEFAULT '',   -- section within the list; '' is unsectioned
  sort     INTEGER,
  added    TEXT NOT NULL,
  UNIQUE (list_id, symbol)      -- a symbol is on a list once; re-adding regroups it
)
```

**Sections, not folders.** "Groups" are named sections *within* a list
(`grp`) — the trader arranges one list into headed blocks, TradingView-style.
There is no folder layer above lists; a list is the unit you switch between.

**Symbols are canonicalised, never repaired.** `company.symbols.normalise`
rejects an unusable ticker (`Operating Model` §7, "nobody knows the ticker").
It is *not* checked against a vendor on add — a watchlist is tier-3
scaffolding, and a typo surfaces as "no quote" in the panel rather than
blocking the edit. There is no name resolution here: `UI-0` Step 1's
`resolve("Nvidia")` is unbuilt, so the panel accepts already-resolved tickers.

## Routes

| Route | Method | Effect |
|---|---|---|
| `/v1/watchlists` | GET | every list, each with its members |
| `/v1/watchlists/new` | POST | `{name}` → new list |
| `/v1/watchlists/{id}/rename` | POST | `{name}` |
| `/v1/watchlists/{id}/delete` | POST | drop the list and its members |
| `/v1/watchlists/{id}/add` | POST | `{symbol, group?}` — idempotent on symbol |
| `/v1/watchlists/{id}/remove` | POST | `{symbol}` |
| `/v1/watchlists/{id}/group` | POST | `{symbol, group}` — move between sections |
| `/v1/market/quotes` | GET | `?symbols=A,B` → day change, **tier 3** |

Each mutation returns the whole set back, like [[Research Canvas]]: a person and
Genesis both edit these, so the answer is the current state.

## Quotes are tier 3, and are settled closes

`/v1/market/quotes` is backed by `marketdata/quotes.py`: one yfinance
`history(period="1mo", interval="1d")` call per symbol, 15-minute TTL cache,
returning `{close, prev_close, change, change_pct, as_of}`.

**Not a live price.** No realtime feed is wired to Genesis, so a row is the last
*completed* daily close against the one before it, carrying the session date.
`fast_info.last_price` was the obvious alternative and is the wrong one: it is a
delayed last-trade that moves intraday, so two rows refreshed a minute apart
would disagree with each other and with every chart on the surface, while
looking authoritative. This is the same stance [[Charting Engine]]'s `CH` takes
— *"closed bars only, the right edge is the last bar on disk"* — and the panel
names the session in its footer rather than implying "now".

A public feed with no provenance line and no reconciliation. [[Market Data
Sources]] puts it at tier 3; [[Safety Invariants]] §11 keeps tier 1 as the only
feed the risk engine reads. The colour on a watchlist row **may not be cited as
a number Genesis knows**, and the panel says so on its face.

Two third parties, deliberately not conflated: the closes are Yahoo's, the chart
a row opens is TradingView's.

> A single close is an **error row**, not a flat one. A symbol with one bar
> cannot produce a day change, and rendering it as `0.00%` would be a
> fabricated number in the one place the panel exists to colour.

## Picking a row drives the chart

Two separate acts, and only the first is the link:

1. **Setting the symbol.** The panel sets `tvSymbol` on the workspace context,
   which *every* open TradingView panel follows. That is an **unnamed,
   page-wide link group** — the mechanism [[Terminal]] §Symbol linking
   describes, minus the naming and the `🔗` chip.
2. **Making sure a chart exists.** `revealPanel('tradingview')` focuses whatever
   TradingView panel is already open, *however it was opened*, and adds one only
   if there is none.

Step 2 is deliberately keyed on the **component**, not on a private panel id.
Keying on an id owned by the caller finds only panels that caller opened, so a
chart the operator opened by hand with `TV` was invisible to it and every click
stacked another one. A panel is a panel regardless of which door it came
through — the same parity argument [[Operating Model]] §2 makes about Genesis
and the human, applied to the dock.

> **Ceiling.** One unnamed group per page: every watchlist drives every
> TradingView panel on that page. Correct for one of each, wrong as soon as you
> want two watchlists driving two charts independently. The upgrade is **named
> link groups** (`A`/`B`/`C` + the chip) — [[UI-0 Build Order]] step 4, a specced
> feature in its own right, not a tweak to this panel.

## Parity

Opening the panel is the palette code `WL` — "a match is an open"
([[Terminal]]). The edits are the panel's own buttons: a person doing it by
hand, through the same REST door.

Genesis writes through the `watchlist` entry in `commands.py` — deterministic,
no model, typed or spoken alike ([[Open Questions]] §18.1, decided 2026-09-14):

| Said | Does |
|---|---|
| `save these to a watchlist` | the last screen's matches → new list, named from the screen (`understood`, else `described`) |
| `save NVDA AMD TSM to a watchlist` | new list, auto-named `NVDA · AMD · TSM` (`+N` past three) |
| `create a watchlist called semis with NVDA` | new list `Semis` |
| `add INTC to my semis watchlist` | a list with that name (case-insensitive) is **added to**, not duplicated |

Tickers only — a word that fails `normalise` is skipped and named in the reply,
never guessed. A company *name* that happens to pass the ticker pattern
("nvidia") is stored as-is and shows "no quote", the same stance as a typo in
the panel. On success the daemon emits `watchlist.updated`; the `WL` panel
re-reads on it, like `SCR` on `screen.updated`.

## Related

[[Conversation Store]] · [[Data Model Overview]] · [[Charting Engine]] ·
[[Market Data Sources]] · [[Safety Invariants]] · [[Operating Model]] ·
[[Terminal]] · [[Widget Catalog]] · [[Agent — Screener]] · [[Open Questions]]
