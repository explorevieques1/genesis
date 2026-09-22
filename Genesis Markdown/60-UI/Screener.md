---
title: Screener
tags: [ui, research, screener]
status: building
implemented_by:
  - ui/src/workspace/panels/screener.tsx
  - ui/src/workspace/panels/ask.tsx
  - ui/src/workspace/modules.ts
  - ui/src/api/client.ts
  - ui/src/App.tsx
  - src/genesis/server/watchlist_routes.py
  - src/genesis/server/app.py
  - tests/test_screener.py
---

# 🔎 Screener — `SCR`

The S&P 500 screen you are building, big enough to work in. [[Ask Genesis]] is
where you talk to the screener about what you want; `SCR` is where you look at
the result and push it around by hand. The agent and its catalogue are
[[Agent — Screener]].

## One screen, every door

There is **one current screen**, saved in `screener.db` (`meta.current`) by
whichever door ran last — chat, ⌘K, voice, or this panel. Every door runs through
`POST /v1/command`. When a reply carries `data.screen` the daemon emits
`screen.updated` (a ping, no rows) and the panel re-reads `GET /v1/screener`.

The interpreter is always shown that current screen, so an edit made here is
what the next chat message refines, and a refinement made in chat lands here.

| Action | Door | Model? |
|---|---|---|
| Describe or refine in plain English | Ask Genesis conversation | small tier |
| Tap a suggested choice | Ask Genesis conversation | small tier |
| Remove a criterion (✕) | `scr <remaining terms>` | no |
| Sort by a column | `scr … sort:-field` | no |
| Edit the scan text | `scr <expression>` | no |
| Refresh data | `scr refresh` | no |

Plain-English input in the panel is **sent into Ask Genesis** (opened if needed),
prefixed `refine the current screen:` when a screen exists — the dialogue stays
in one thread and the prefix routes it to the screener even with no history.

## Opening

The canvas opens empty ([[Operating Model]] §3). `SCR` appears when a screen is
asked for — Ask Genesis and ⌘K reveal it on a `data.screen` reply — or when typed
as a module code.

## Layout

- **Header** — `N of 503 match`, interpreted/typed, snapshot size, source and
  as-of (red when stale), *refresh data*.
- **Reading** — what was asked, what the agent understood, one chip per criterion
  (with the trader's phrase when the agent read it from one), unsupported parts,
  names excluded for missing data, the agent's question with choices.
- **Matches** — symbol, name, sector, the criteria columns, sort column, price,
  market cap. Click a row: ticker to the workspace, Company panel revealed.
- **Inputs** — refine in plain English; edit the `scr` expression (field list in
  its tooltip).

The chat reply keeps the conversation's half: readings, the first eight rows,
`all N in SCR →`, and tap-to-send choices.

## Routes

`GET /v1/screener` → `{available, tier, current, snapshot: {as_of, rows, failed,
stale}, fields, text_fields, sectors}`. Read-only; a scan is only ever run through
the command door.

## Not built

Saved named screens, and multiple screens side by side — one current screen until
a second is actually wanted.

## Related

[[Agent — Screener]] · [[Ask Genesis]] · [[Widget Catalog]] · [[Terminal]] ·
[[Operating Model]] · [[Index Movers]]
