---
title: News
tags: [ui, research]
status: building
implemented_by:
  - src/genesis/news/__init__.py
  - ui/src/workspace/panels/news.tsx
  - tests/research/test_news.py
  - ui/src/workspace/panels/status.tsx
  - ui/src/api/client.ts
  - src/genesis/news/store.py
  - src/genesis/news/collect.py
  - src/genesis/server/news_routes.py
  - src/genesis/automation/actions.py
---

# 📰 News

Headlines you scroll and open, an article you read in place, and Genesis reading
it with you. A module (`NW`, aliases *news, headlines, briefs*), home `research`,
spawnable into any workspace. Like a TradingView news pane, plus the analyst.

## What it is on the map

Two organs, deliberately separate ([[Biological Design]]):

| Part | Organ | Reflex or judgement |
|---|---|---|
| [[Agent — News Collector]] | afferent nerve — gathers headlines on a cadence | reflex, `tier: none` |
| [[Agent — News And Catalyst]] | the analyst — summary, insights, trade ideas, briefs | judgement, `large` |

The collector never decides what a story means; the analyst never fetches on a
timer. Giving the collector a model would be the bug the reflex arc warns about.

## The module

Two tabs.

- **Headlines** — every stored story, newest first. Filter by window (24h · 3d ·
  7d · all), by text, or by typing tickers (`NVDA, TSLA` filters by symbol).
  `refresh` collects now. Selecting a story opens the **reader**: the article
  text (read once by the daemon and cached), the publisher, time and symbols,
  and *open original ↗*. A page that will not give up its text (paywall, block)
  says so and shows the feed's summary instead — never a blank.
- **AI summary** (in the reader) — the analyst reads the article and returns
  summary, key points, insights, direction / magnitude / horizon / kind, trade
  ideas with an invalidation, risks, confidence, and what it actually read.
- **Briefs** — multi-story summaries: pick a window (24h · weekend 64h · week),
  an optional focus, `write brief`. Each brief lists the stories it read, and a
  story in it opens in the reader. Workflows write briefs here too.

It does not poll ([[UI Stack]] §9). Lists reload when a `task.completed` event
from `news-collector` or `news-catalyst` arrives, or when you press a button.
The canvas-opens-empty rule holds: the module is not seeded on any page.

## Trust

Everything here is **tier 4** ([[Market Data Sources]]): third-party text and a
model's reading of it. A tier-4 chip is always on screen.

- Article text is **fenced** (`mcp.fence.wrap`) before it meets a prompt. A page
  that tries to instruct the model is flagged on the result (`injection`,
  `flags`) and shown as a warning — never obeyed.
- **Trade ideas are directions in words** — bias (long · short · watch),
  symbols, rationale, invalidation. No size, no stop, no target: the prompt
  forbids them, and [[Safety Invariants]] #3 is why. Nothing here reaches an
  order path; the module imports no execution code.
- A brief's stories cite stored article ids. A story the model numbered wrongly
  is **dropped**, not guessed at.

## Store

`news.db` beside the other stores, path from config (`memory.db_path` parent).
The trader's own deletable cache — the [[Conversation Store]] pattern.

| Table | Holds |
|---|---|
| `articles` | one row per story, keyed by title + publisher (the same story arrives under two URLs); `symbols` merge; `body` read on demand; `analysis` the AI summary |
| `briefs` | title, window hours, who asked (`operator` · `workflow` · `orchestrator`), body JSON with `articles` it read |
| `collections` | one line per collector run — `ok`, sources, fetched, new, error detail; last 500 kept |

## Routes

| Route | Does |
|---|---|
| `GET /v1/news?hours&symbols&q&limit` | stored headlines, no bodies |
| `GET /v1/news/status` | collector status — Status (`HLT`) → data sources → `news` |
| `GET /v1/news/article/{id}` | one story with its text (reads the page on first open) |
| `GET /v1/news/briefs` · `/v1/news/briefs/{id}` | briefs |
| `POST /v1/news/collect` | collect now |
| `POST /v1/news/article/{id}/summarise` | AI summary |
| `POST /v1/news/brief` | write a brief `{hours, symbols, focus, max_articles, refresh}` |

The two model routes build the large tier per call, so a Settings change applies
at once, and an unbuildable tier returns its reason (*"GEMINI_API_KEY is not
set"*), not a shrug.

## Status

`HLT` → **data sources** → `news`: source, stories in the last 24h, stories held,
when it last ran and its error if any. `collecting` when the last run worked and
a run succeeded within two hours (twice the slowest cadence); `stale` past that;
`failing` when the last run failed; `idle` when it has never run.

## Automation

Three nodes in the **News & sentiment** category ([[Automation]] §Node library):

| Node | Kind | Does |
|---|---|---|
| `news.collect` — *Collect news* | write | collect for market + watchlists + extra symbols / topics |
| `news.recent` — *Recent headlines* | read | stored stories from the last N hours, filtered; items carry ids |
| `agent.news-brief` — *Write news brief* | agent | dispatch `news.brief` to [[Agent — News And Catalyst]]; given `news.recent` as input it briefs exactly those stories |

**The Sunday-evening weekend brief:** trigger `cron 18:00` → `logic.days [sun]`
→ `agent.news-brief {hours: 64, focus: "what matters for next week", refresh: on}`.
The brief lands in the Briefs tab. Dispatch is fire-and-forget, so an alert step
after it cannot quote the brief — the `task.completed` event carries its title
and overview.

## Parity

Button, workflow and planner reach the same two functions
(`news_catalyst.summarise_article`, `write_brief`) and the same collector
(`news.collect.collect`). *"Brief me on the weekend's news"* typed or spoken
plans `news.brief`.

## Not built

- No source beyond yfinance. Finnhub `news.market` and TradingView headlines are
  gateway tools, not collector sources.
- Catalyst records, the forward calendar and `news.spike` — [[Agent — News And Catalyst]] §Outputs.
- Article extraction is a paragraph scrape; trafilatura when pages come back as boilerplate.

## Related

[[Agent — News Collector]] · [[Agent — News And Catalyst]] · [[Automation]] ·
[[Market Data Sources]] · [[MCP Gateway]] · [[Workspaces]] · [[Widget Catalog]]
