---
title: Knowledge Graph
tags: [memory]
status: spec
implemented_by: []
---

# Knowledge Graph

What the system *believes*, and how those beliefs connect. Entities and typed edges,
consolidated nightly.

Pattern: [[Repo — jarvis]] `src/jarvis/memory/graph.py`, `graph_ops.py`, `graph.spec.md`.

## Entity types

| Type | Key | Examples |
|---|---|---|
| `symbol` | ticker | NVDA, AMD |
| `level` | `SYMBOL:PRICE` | `NVDA:122.10` |
| `setup` | name | orb_breakout, vwap_reclaim |
| `strategy` | id | nq_orb_v3 |
| `idea` | id | idea_01J8XS |
| `thesis` | id | "semis lead this cycle" |
| `trade` | id | from the [[Trade Ledger]] |
| `lesson` | id | from [[Agent — Insight Miner]] |
| `regime` | date-range | risk-on 2026-07-14 → present |
| `catalyst` | id | CPI 2026-08-29 |
| `belief` | id | a promoted, repeatedly-confirmed observation |

## Edge types

Edges are typed and directional — that's what makes the graph answerable rather than
just connected.

| Edge | Meaning |
|---|---|
| `derived_from` | idea ← scan hit, catalyst, level |
| `traded_as` | idea → trade |
| `invalidated_by` | idea/thesis → the event that killed it |
| `confirms` / `contradicts` | evidence → thesis |
| `supersedes` | newer fact → older fact |
| `held` / `broke` | price action → level (the outcome of a level) |
| `works_in` / `fails_in` | setup → regime |
| `learned_from` | lesson → trades |
| `applies_to` | lesson → setup / symbol / condition |
| `correlates_with` | symbol ↔ symbol, with a value and a date |

## The questions it exists to answer

A vector store can find similar text. It cannot answer these:

- *Which of my levels actually hold?* → `level --held/broke--> outcome`, aggregated
- *Which setups work in which regime?* → `setup --works_in--> regime`
- *What killed my last five theses?* → `thesis --invalidated_by--> event`
- *Have I traded this idea before?* → `idea ~ idea` by symbol + setup + level
- *Which lessons apply to the trade I'm about to take?* → `lesson --applies_to-->`
- *Is this "diversified" book really one bet?* → `correlates_with` clusters

That first one is the sleeper. After a few hundred marked levels, the graph knows
your anchored-VWAP levels hold 71% of the time and your fitted trendlines hold 38%.
No charting platform can tell you that about *your own* levels — it's only possible
because [[Markup Spec]] annotations become entities.

## Beliefs

An observation seen repeatedly is promoted to a `belief` by [[Memory Consolidation]]:

```yaml
id: belief_01J8Y1
statement: "NVDA respects its anchored VWAP from earnings gaps"
evidence_count: 11
confirmations: 8
contradictions: 3
confidence: 0.68
first_seen: 2026-02-14
last_confirmed: 2026-08-27
status: active            # active | weakening | retired
```

Beliefs weaken when contradicted and retire when they stop being confirmed. A belief
that hasn't been confirmed in months is not knowledge, it's a fossil — and the graph
should say so rather than keeping it at full weight.

## Superseding

New facts about the same entity supersede old ones rather than piling up. The old
fact is kept with a `supersedes` edge — history matters, but retrieval returns the
current state by default.

Pattern: [[Repo — jarvis]] recency-superseding evals.

## Writes

Agents write entities and edges through their namespace. The heaviest writers:

- [[Agent — Chart Markup]] → `level` entities, one per annotation
- [[Agent — Level Watcher]] → `held` / `broke` edges, the outcome data
- [[Agent — Idea Synthesizer]] → `idea`, `derived_from`, `contradicts`
- [[Agent — Insight Miner]] → `lesson`, `learned_from`, `applies_to`
- [[Agent — Regime And Correlation]] → `regime`, `correlates_with`
- [[Memory Consolidation]] → merges, promotions, retirements

## Acceptance criteria

- Level outcome tracking produces a hold-rate per level type after a sample period.
- Superseded facts are not returned by default retrieval, but remain queryable.
- Beliefs retire automatically without confirmation.
- Duplicate entities are merged nightly (same level within a tick tolerance, same
  thesis phrased differently).
- Graph queries used in the hot path return in under 50 ms.

## Related

[[Memory Fabric]] · [[Memory Consolidation]] · [[Recall Pathways]] ·
[[Markup Spec]] · [[Agent — Insight Miner]] · [[Vector Store]]
