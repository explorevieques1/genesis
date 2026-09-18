---
title: Obsidian Vault Schema
tags: [memory, schema]
status: building
implemented_by: [src/genesis/research/store.py]
---

# Obsidian Vault Schema

The human-readable, human-editable projection of [[Memory Fabric]]. Agents write it
continuously; you edit it freely; [[Memory Consolidation]] reads your edits back.

Reference: `OBSIDIAN-VAULT-PROMPT.md` in [[Repo — Gensis Terminal Official]].
Location decision: [[Open Questions]] §5 — a dedicated vault is recommended.

## Structure

```
GenesisVault/
├── 00-Inbox/                  # raw capture, unprocessed — your quick notes
├── 10-Ideas/
│   ├── YYYY/MM/               # one note per trade idea
│   └── plans/                 # one note per plan of action — [[Agent — Session Plan]]
├── 20-Charts/                 # rendered PNGs + spec references
├── 30-Journal/
│   └── YYYY/MM/               # one note per trade
├── 40-Strategies/
│   └── <strategy-id>/         # definition, backtests, optimization history, tearsheets
├── 50-Research/
│   ├── daily/YYYY-MM-DD.md    # the daily brief
│   ├── symbols/<TICKER>.md    # a living note per symbol
│   └── themes/                # multi-symbol theses
├── 60-Lessons/                # [[Agent — Insight Miner]] output
├── 70-Watchlists/             # agent-maintained, dynamic
├── 90-Meta/                   # regime log, correlation matrices, tearsheets, health
└── templates/                 # note templates the agents fill
```

## Who writes what

| Folder | Writer | You edit? |
|---|---|---|
| `00-Inbox/` | you | yes — agents read it |
| `10-Ideas/` | [[Agent — Idea Synthesizer]] | yes — your notes are absorbed |
| `20-Charts/` | [[Agent — Chart Markup]] | no — regenerated from specs |
| `30-Journal/` | [[Agent — Trade Journal]] | **yes — the human fields are yours** |
| `40-Strategies/` | [[Agent — Strategy Author]], [[Agent — Backtest Runner]] | yes |
| `50-Research/` | research family | yes |
| `60-Lessons/` | [[Agent — Insight Miner]] | yes — you can promote or dismiss |
| `70-Watchlists/` | [[Agent — Screener]] | yes |
| `90-Meta/` | various | no |

## Frontmatter is the contract

Every agent-written note carries typed frontmatter so both Dataview and the agents
can query it. See [[Idea Schema]], [[Trade Journal Schema]], [[Strategy Schema]].

```yaml
---
type: idea                    # idea | journal | strategy | research | lesson
id: idea_01J8XS
symbol: NVDA
direction: long
status: active                # active | triggered | invalidated | expired | taken
confidence: 0.72
entry_zone: [120.60, 121.40]
invalidation: 118.40
timeframe: swing
created: 2026-08-29T07:12:00Z
trace_id: tr_01J8XP
tags: [semis, orb, breakout]
degraded: false
---
```

Never put a computed value in the body that isn't also in frontmatter. If Dataview
can't query it, it doesn't exist for the system.

## Dataview dashboards

The vault is a working surface, not an archive:

````
```dataview
TABLE symbol, confidence, entry_zone, invalidation, status
FROM #idea WHERE status = "active"
SORT confidence DESC
```

```dataview
TABLE symbol, r_multiple, setup, plan_followed
FROM #journal WHERE date >= date(today) - dur(7 days)
SORT date DESC
```

```dataview
TABLE strategy, live_expectancy_r, backtest_expectancy_r, drift_severity
FROM #strategy WHERE status = "live"
```

```dataview
LIST FROM #lesson WHERE status = "active" SORT confidence DESC
```
````

## Linking conventions

- Ideas link to their charts, the strategy, the catalysts, and the trade taken
- Journal notes link back to the idea, forward to any lesson derived from them
- Lessons link to the trades that produced them
- Symbol notes link to every idea, trade, and level for that symbol

The result is a graph you can *walk*: from a losing trade to the idea, to the
research, to the lesson it produced, to the next trade where that lesson fired.

## Conflict rule

Your edit always wins. If an agent and you both changed a note, yours is kept; the
agent's version goes into the note's history section with a timestamp. Agents never
overwrite your prose — they append to their own sections.

## Acceptance criteria

- Every agent-written note has valid, complete frontmatter.
- Dataview queries in the templates return correctly against real data.
- A vault edit survives the next consolidation and changes agent behaviour.
- No agent overwrites human-authored text, verified by test.
- Charts are always regenerable from their stored specs.

## Related

[[Memory Fabric]] · [[Memory Consolidation]] · [[Idea Schema]] ·
[[Trade Journal Schema]] · [[Strategy Schema]] · [[Repo — Gensis Terminal Official]]
