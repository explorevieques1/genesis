---
title: Agent — News Collector
tags: [agent, research]
family: research
cadence: market-open, market-closed, on-demand
tier: none
status: built
implemented_by: [src/genesis/agents/research/news_collector.py, src/genesis/news/collect.py, src/genesis/news/store.py, src/genesis/agents/research/fleet.py]
---

# 📡 Agent — News Collector

## Purpose

The afferent nerve for news. Gathers headlines into `news.db` on a cadence so
that when a person opens [[News]] or a workflow asks for a brief, the stories
are already there. It reads no meaning into anything — that is
[[Agent — News And Catalyst]].

Split out because collection is a **reflex** and analysis is **judgement**
([[Biological Design]]). A collector with a model would spend tokens on a timer
and could be talked into skipping a source.

## Cadence

- `market-open` every 15 min
- `market-closed` every 60 min — so a Sunday-evening brief has the weekend
- `on-demand` — `refresh` in [[News]], the `news.collect` workflow node

## Inputs

yfinance, the only integrated news feed with no key:

- `Ticker(sym).news` for broad-market proxies — SPY QQQ DIA IWM TLT GLD USO ^VIX
- the same for every watchlist symbol (at most 40 per run)
- `Search(q).news` for subjects with no ticker — *stock market, federal reserve, economy*

## Outputs

Rows in `news.db` `articles` (deduped by title + publisher, symbols merged) and
one `collections` line per run — what Status reads. A run where more than half
the sources failed is `ok: false`, and the task result is `degraded`. It does not
mark the agent degraded: one bad hour of yfinance is not a down organ.

## Tools

None through the gateway. yfinance is called directly, as the company profile
provider does. No model, no broker, no vault.

## Memory namespace

Read: `shared` · Write: `news-collector` (`news.db`)

## Acceptance criteria

- A collection with every source failing logs `ok: false` and Status shows `failing`.
- The same story under two symbols is one row carrying both.
- No model is constructed anywhere on its path (`tier: none`).

## Related

[[News]] · [[Agent — News And Catalyst]] · [[Research Family]] · [[Market Data Sources]]
