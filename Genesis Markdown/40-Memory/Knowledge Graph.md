---
title: Knowledge Graph
tags: [memory]
status: building
implemented_by: [src/genesis/memory/graph.py, src/genesis/research/store.py, tests/research/test_canvas.py, ui/src/graph/nodes/EntityNode.tsx]
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

## Implementation notes — the built core

`src/genesis/memory/graph.py`. Entities, typed edges, supersession, namespaced
writes and bounded expansion. Three things are enforced rather than intended:

- **An edge to an entity that does not exist is refused**, by foreign key. A
  dangling edge is a hole in an answer, and it is far cheaper to reject it at
  write time than to explain a node that renders empty later.
- **Nothing in the module computes similarity.** There is no code path that
  creates an edge nobody asserted.
- **Every row carries its writer's namespace**, which is what makes Memory
  Fabric's single-writer rule checkable at all.

**A twelfth entity type: `document`.** [[Research Canvas]]'s opening line is
"documents, filings, charts, notes and the links between them", and none of the
eleven covers a fetched web page or a filing. Modelling one as a `thesis` would
be a lie about what it is — a page is not a claim, it is where a claim came
from — and `derived_from` edges into it are exactly the provenance the canvas
exists to show.

**A fourteenth edge kind: `mentions`**, kept separate from `applies_to` on
purpose. "This research note mentions NVDA" is not "this lesson applies to
NVDA": one is a pointer, the other is a claim about scope. Collapsing them would
let a passing mention answer *"which lessons apply to the trade I'm about to
take?"*

### Not built

**Beliefs, promotion, retirement and nightly merges.** Those belong to
[[Memory Consolidation]], and they need a corpus of repeated observations this
system has not accumulated: a belief promoted from three observations is worse
than no belief. The `belief` type is accepted so the consolidator has somewhere
to write; nothing creates one yet.

**Level outcome tracking**, the note's sleeper feature, is unreached for the
same reason — it needs [[Agent — Level Watcher]] writing `held`/`broke` edges,
which it does not do yet. The edge kinds exist and are refused to nobody.

## Writers today

[[Research Directory]] projects every note it stores: an entity per note
(`thesis`, `idea` or `regime`), an entity per cited source (`document`), and
`derived_from` edges between them. One hook, in the store, rather than three
agents each remembering — an agent that forgets writes a note the canvas can
never show, and the omission is invisible until someone goes looking for a node
that should exist.

## Related

[[Memory Fabric]] · [[Memory Consolidation]] · [[Recall Pathways]] ·
[[Markup Spec]] · [[Agent — Insight Miner]] · [[Vector Store]]
