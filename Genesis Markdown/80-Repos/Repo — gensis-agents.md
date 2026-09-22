---
title: Repo — gensis-agents
tags: [repo]
---

# Repo — gensis-agents

`/home/gzacc2002/Projects/gensis-agents/`

**"Trading OS" — the direct predecessor.** A central orchestrator managing a fleet of
autonomous agents, each a focused specialist. Node/npm workspaces. This is where the
Genesis agent-fleet model comes from.

Its own README states the thesis Genesis inherits: *"The orchestrator is the
dashboard; the agents are the employees."*

## Structure

```
trading-os/
├── orchestrator/          # dashboard + agent manager (port 3000)
│   ├── src/server.js      # Express + WebSocket + process manager
│   ├── src/registry.js    # agent definitions — add new agents here
│   └── public/index.html  # dashboard UI
├── agents/
│   ├── alert-agent/       # PineScript alert builder (3001) — the built one
│   ├── calendar-agent/    # (3002) stub
│   ├── scanner-agent/     # (3003) stub
│   └── journal-agent/     # (3004) stub
├── shared/
│   ├── agent-base.js      # start/stop/status/runTask
│   ├── task-queue.js      # cross-agent task tracking
│   └── logger.js          # colour-coded unified logger
└── scripts/{dev,start,seed}.js
```

## What Genesis takes

| Genesis component | Source |
|---|---|
| [[Agent Contract]] | `shared/agent-base.js` — the start/stop/status/runTask interface |
| [[Task Bus]] | `shared/task-queue.js` |
| [[Dashboard]] agent grid + activity feed | `orchestrator/` — status cards, start/stop/restart, live feed, summary bar |
| [[Daemon And Cadence]] supervision | `scripts/dev.js` process manager |
| **[[Agent — Strategy Author]] condition vocabulary** | `agents/alert-agent/` |
| [[Observability]] log style | `shared/logger.js` |
| Agent registration pattern | `orchestrator/src/registry.js` |

## The alert agent — the most valuable piece

Fully built, and it's exactly the condition vocabulary [[Strategy Schema]] needs:

- **20+ condition types** grouped by category: indicator, volume, range, time, price
- **AND / OR / IF-THEN** logic modes
- Per-condition **weights** and Claude-assisted reasoning
- **Lookback confirmation** — require a signal to hold for N bars
- **Cooldown gate** — suppress re-alerts for N bars
- **Filters**: volume spike (X× the N-bar average), ATR noise, trend alignment (EMA
  direction), session (regular / pre / after hours)
- **Three-category notebook**: strategies (parent) → alerts (compiled Pine, linked to
  a strategy) → indicators (reusable across alerts)

Reuse this vocabulary rather than inventing a new one. It's tested against real Pine
output, and the three-category notebook maps cleanly onto Genesis's strategy /
alert / indicator split.

## `New Downloads/` — assets worth mining

- `NQ_PropFirm_Strategy*.pine` (multiple versions) — prop-firm strategy Pine, and
  useful test fixtures for [[genesis-charting-mcp]]'s `compile_pine`
- `4hr_range_trading_indicator*.pine`, `today_trade_idea.pine`
- `Genesis Terminal Design System.zip` (×2) — the visual language for [[Dashboard]]
- `launchpad.html`, `launchpad_v3.html`, `explorer.jsx`, `palette.jsx`,
  `settings.jsx`, `calculator.html`, `timer.*`, `widgets.zip` — UI components
- `Performance.csv`, `Performance.pdf` — real performance data; useful test fixtures
  for [[Agent — Performance Analyst]] and [[Agent — Risk Metrics]]

## What Genesis changes

| gensis-agents | Genesis |
|---|---|
| Agents are HTTP services on their own ports | Agents are supervised workers on a [[Task Bus]] |
| Dashboard is the primary input | **The command line is primary**, voice is its peer; panels are what a question opened ([[Operating Model]]) |
| 4 agents, 3 stubs | ~30 agents in 5 families ([[Agent Index]]) |
| No execution | Full execution behind [[Pre-Trade Risk Engine]] |
| No memory layer | Five-layer [[Memory Fabric]] |
| Notebook JSON files | Vault + graph + vector ([[Obsidian Vault Schema]]) |

The port-per-agent model doesn't scale to thirty agents and makes priority lanes
impossible — hence the [[Task Bus]]. Everything else carries forward.

## Note

This directory also contains its own copies of `INDEX.md` and `CLAUDE.md` — the same
[[Trading Corpus Index]] rules, duplicated. Treat `Genesis Agent/INDEX.md` as canonical.

## Related

[[Agent Contract]] · [[Task Bus]] · [[Dashboard]] · [[Agent — Strategy Author]] ·
[[Strategy Schema]] · [[Repo Map]]
