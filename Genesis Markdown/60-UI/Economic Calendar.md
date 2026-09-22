---
title: Economic Calendar
tags: [ui, research, data]
status: built
implemented_by:
  - src/genesis/news/econ.py
  - ui/src/workspace/panels/econ.tsx
  - src/genesis/news/store.py
  - src/genesis/news/collect.py
  - src/genesis/server/news_routes.py
  - ui/src/components/EconCountdown.tsx
  - ui/src/components/SystemHealth.tsx
  - ui/src/api/client.ts
---

# 📕 Economic Calendar

The red folder: which day, what time, and how long until it lands. A module
(`EC`, aliases *econ, calendar, red folder, data releases, nfp, cpi, fomc*),
home `research`, spawnable into any workspace — plus one always-visible
countdown in the status row.

It answers one question, asked under load: *what is about to print?*

## What it is on the map

An **afferent nerve and a clock**, nothing more ([[Biological Design]]). It
senses a published schedule and displays it. There is no agent, no model and no
tier — `src/genesis/news/econ.py` is `tier: none`, and giving it judgement
("which of these matters to my book") would be the reflex-arc bug.

It is **not an actuator and not an alarm**. Nothing here acts, nothing pops,
nothing speaks. A print approaching is not a request, so nothing opens itself
([[Operating Model]] §3): the countdown is ambient, and the operator clicks it.

## The data

| | |
|---|---|
| **Source** | ForexFactory's weekly JSON — `https://nfs.faireconomy.media/ff_calendar_thisweek.json` |
| **Key** | none |
| **Shape** | `title`, `country`, `date` (ISO with a real UTC offset), `impact`, `forecast`, `previous` |
| **Horizon** | one rolling Mon–Sun week. `nextweek` and the rest 404 — this is the only file published |
| **Cadence** | folded into the [[Agent — News Collector]] run, rate-limited to once every 6h |
| **Trust** | **tier 3** ([[Market Data Sources]]) — a third party's schedule and their impact rating |

**Why this source and not FRED.** The impact rating is the entire feature. FRED
release dates, the Fed's published schedule and the BLS calendar are all free
and all give dates without a rating — with those you hand-maintain the list of
which prints are red, and that list is a judgement pretending to be data. Here
the rating is the vendor's, so a wrong one is a wrong row rather than a wrong
decision of ours. The upgrade path, if the horizon must reach past one week, is
the Fed and BLS schedules for the handful of prints known months out.

**Revisions are replaced, not appended.** A time that moves or a forecast that
appears overwrites its row (identity is *what prints, where, when*). Two rows
for one print is how a countdown ends up naming a corrected time.

**Nothing safety-critical reads this table.** It informs a person. No risk
check, no sizing, no stop and no agent may read it ([[Safety Invariants]] #3).

## The module

Rows grouped by day and read **forwards** — the only panel that does, because
nothing here has happened yet. Each row is *New York time · title · forecast vs
previous · a countdown chip*, amber inside a day and red inside an hour. All-day
and tentative entries (the vendor's midnight) are labelled `all day`, never
shown as a 00:00 print.

Two filters, both defaulting to the desk: **red folder** (high impact; toggles
to high + medium) and **US** (toggles to every country). They are the same
widening the route takes as query params — [[Operating Model]] §1. `refresh`
pulls now. The footer names the zone, the tier, the vendor, and when it was
last pulled.

A print stays on the list for 15 minutes after its time: the number is most
interesting in the minute *after* it lands.

## The countdown

One segment in the status row: `▮ Federal Funds Rate  in 2h 14m`. The next
**timed, high-impact, US** print, and how long until it lands.

It is the one thing in the chrome that is not system health, and it earns the
place the way the kill switch does — a number that matters behind a click is a
number nobody reads. A print you have forgotten about is the one that takes a
position with it.

It shows **nothing at all** — its separator included — when there is no print
ahead, no calendar pulled, or no daemon answering. A stale countdown is worse
than no countdown. Clicking it opens `EC`, the same module `⌘K → EC` opens, by
the same call.

## Store

`econ_events` in `news.db` ([[News]] §Store) — the same file, because it arrives
on the same afferent pass and is the same kind of thing: third-party text the
trader may delete.

| Column | Holds |
|---|---|
| `id` | sha1 of `at` + country + title — identity is the print, not the row's place in the file |
| `at` | UTC ISO. The UI renders New York and local; nothing stores a naive datetime |
| `country`, `title`, `impact` | vendor's own spelling; `High` is the red folder |
| `forecast`, `previous` | as published, strings — they are not arithmetic and are never parsed as numbers |
| `all_day` | midnight in the feed's zone: all-day or tentative |
| `fetched` | drives the 6h staleness guard in `econ.refresh` |

Old rows are kept rather than pruned, so the table grows backwards into a record
of what printed and what was forecast.

## Routes

| Route | Does |
|---|---|
| `GET /v1/news/econ?impacts&countries&limit` | what has not printed yet, soonest first; defaults `High` + `USD` |
| `POST /v1/news/econ/refresh` | pull now, bypassing the staleness guard |

## Not built

- **No reminder that reaches you away from the screen.** The countdown is
  ambient; there is no notification, no TTS at T-5m, no feed row. Voice would be
  the natural next one and it needs a mute rule first ([[Voice UX]]).
- One rolling week of horizon, and no way to see the week after it.
- No history view: past prints are in the table but nothing reads them, so
  "what did SPY do the last five CPIs" is not a question `EC` can answer yet.
- No link from a print to the story that followed it ([[News]]).

## Related

[[News]] · [[Agent — News Collector]] · [[Agent — News And Catalyst]] ·
[[Market Data Catalog]] · [[Market Data Sources]] · [[Operating Model]] ·
[[Biological Design]] · [[Workspaces]] · [[Terminal]]
