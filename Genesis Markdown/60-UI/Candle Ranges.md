---
title: Candle Ranges
tags: [ui, module, marketdata]
status: built
implemented_by: [src/genesis/marketdata/ranges.py, src/genesis/server/range_routes.py, ui/src/workspace/panels/ranges.tsx, tests/marketdata/test_ranges.py]
---

# Candle Ranges — `CR`

A named window of price, downloaded once and kept. *"ES, 5-minute, 8 September
2026, 09:30 to 11:05"* — captured, named "ES opening drive", and thereafter
frozen.

It exists because reviewing a setup you took is a different job from holding
market history. You want the forty bars around the trade, under a name you
chose, looking the same next month as they do today. Everything else about the
symbol is noise for that job.

Home category: [[Workspaces|charting]].

## What it is not

It is **not** the bar store. [[Market Data Plane]] holds what the world did:
canonical symbol ids, immutable closed bars, restatement tracking, coverage
records. A range is the trader's scrapbook — keyed by whatever ticker the
vendor answers to, and losing `ranges.db` costs some snippets and no history.
Same lifecycle and same shape as [[Watchlist Store]] and the [[Conversation
Store]]: the trader's own data, theirs to change.

| | `SR` Series | `CR` Candle Ranges |
|---|---|---|
| Keyed by | canonical symbol id | vendor ticker |
| Contents | all history held | one window |
| Written by | ingest | the trader, by hand |
| Losing it costs | the history | some snippets |

## Why `ES=F` is allowed here

The yfinance adapter refuses futures outright, and that refusal is correct:
Yahoo's `ES=F` is a **continuous front-month series with an undocumented roll**,
one of the four different things spelled "ES" in [[Open Questions]] §13. Written
into the bar store beside `FUT:CME:ES:2026-12` it would put two incompatible
price series under keys that differ by nothing a reader would notice.

As a named scrapbook page labelled with the vendor ticker it came from, it is
exactly what it says it is and corrupts nothing. So `ranges.py` calls yfinance
directly rather than going through the adapter chain — the chain is keyed by
canonical symbol id, and the thing that makes the chain right is the thing that
makes it useless here.

Every range is **tier 3** and the panel says so on its face.

## The window is wall-clock

A window typed as `09:30` is 09:30 where the trader was looking, so a range
carries its timezone (`America/New_York` by default) and stores its bounds in
UTC. The same clock time is a different instant in June and December, and a
range read back six months later must not shift.

Bars are trimmed to the window after the fetch: the saved range is the range
that was asked for, not the bars around it.

## A range charts like any other series

`CR:<range_id>` is served by `GET /v1/market/bars` and appears in
`GET /v1/market/symbols`, so `CH` draws a range without knowing it is doing
anything unusual, and `SR` lists it beside the ingested series. This is the
[[Operating Model]] parity rule doing real work: a snippet you can only look at
inside the tool that made it is a snippet you cannot compare with anything.

## Routes

| Route | | |
|---|---|---|
| `GET /v1/market/ranges` | afferent | the scrapbook |
| `POST /v1/market/ranges/new` | efferent | fetch and save one window |
| `POST /v1/market/ranges/{id}/rename` | efferent | |
| `POST /v1/market/ranges/{id}/delete` | efferent | |

`new` is a POST because it reaches a vendor and takes real time — the same
reasoning [[UI Stack]] §7 gives for commands. None of the three imports
execution code, and `ranges.db` holds OHLCV rows and a name.

## Deliberately not built

- **No range from a source other than Yahoo.** Databento would serve dated
  contracts properly; add it when a range of a real contract is wanted.
- **No annotation on the range *row*.** Marking happens on the chart, where the
  bars are: a range opens as the series `CR:<id>`, and a zone drawn over it can
  be journalled as an entry, an exit or an idea — see
  [[Agent — Trade Journal]] §Marks. Prose write-ups still belong in the
  [[Notebook]], and a note can name a range.

## Related

[[Terminal]] · [[Workspaces]] · [[Charting Engine]] · [[Market Data Plane]] ·
[[Market Data Sources]] · [[Watchlist Store]] · [[Open Questions]] · [[Chart Tools]]
