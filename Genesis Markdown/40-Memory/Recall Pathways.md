---
title: Recall Pathways
tags: [memory, core]
status: spec
implemented_by: []
---

# Recall Pathways

How memory gets *retrieved*. Getting this right is what separates a system that
remembers usefully from one that either forgets or drowns.

## The recall gate

Before any retrieval, a cheap nano-tier classifier decides **whether memory is needed
at all**, and if so, which layers.

```
utterance ──► RECALL GATE (nano, <100ms)
                  │
    ┌─────────────┼─────────────┬──────────────┐
    ▼             ▼             ▼              ▼
  none        working      graph+vector      ledger
 "what time   "what did    "what do I know   "what's my
  is it?"      I just       about NVDA?"      position?"
               ask?"
```

Most utterances need nothing. Paying for hybrid retrieval on "what time does the
market open?" is exactly how a voice assistant becomes slow enough that you stop
using it.

Pattern: [[Repo — jarvis]] `src/jarvis/memory/recall_gate.py`, `recall_gate.spec.md`.

**Fail open.** If the gate is uncertain, retrieve. A slow correct answer beats a fast
wrong one — the gate optimizes the common case, it doesn't gamble on the rare one.

## Hybrid retrieval

When retrieval is needed, four signals combine:

```
score = w_vector   · semantic_similarity      ← [[Vector Store]]
      + w_graph    · graph_proximity          ← [[Knowledge Graph]]
      + w_recency  · time_decay
      + w_priority · explicit_priority
```

| Signal | Contributes |
|---|---|
| **Vector** | "What else reads like this?" Good for theses, notes, research. |
| **Graph** | "What is structurally connected?" Good for levels, ideas, lessons that *apply*. |
| **Recency** | Recent memory usually wins. Markets are non-stationary. |
| **Priority** | Lessons and active invalidations always surface, regardless of similarity. |

Weights differ by query type. A "what do I know about NVDA" query weights graph
heavily; a "have I thought something like this before" query weights vector.

## Priority recall

Some memory must surface whether or not it's semantically similar:

| Class | Rule |
|---|---|
| **Lessons** ([[Agent — Insight Miner]]) | Any lesson whose `applies_when` matches the current context is always retrieved |
| **Active invalidations** | An open idea's invalidation is always in context |
| **Open positions** | Always in context when discussing a symbol you hold |
| **Prop-firm headroom** | Always in context when discussing size |
| **Regime** | Always in context for any idea-related query |

This is the mechanism that makes the learning loop real. A lesson that only surfaces
when semantically similar text appears is a lesson that never fires when you need it.

## Recency and superseding

Newer facts about the same entity outrank older ones, and mark them stale.

- Retrieval returns the current state by default
- Superseded facts remain queryable for history
- A fact's decay rate depends on its type: a catalyst decays in hours, a lesson
  barely decays at all, a level decays with its timeframe

Pattern: [[Repo — jarvis]] recency-superseding evals.

## Namespace filtering

Applied **before** scoring, not after ([[Agent Contract]]). An agent must not see —
and must not be able to infer the existence of — memory outside its declared
namespaces. Filtering after ranking leaks information through result counts.

## Deduplication

Retrieval returns *facts*, not *repetitions*. The same belief expressed in eleven
notes should return once, with its strongest citation, not eleven times crowding out
everything else.

Dedupe by entity id first, then by near-duplicate text.

## Result budget

Retrieval returns a bounded, token-budgeted set. A large-tier agent gets more; a
small-tier agent gets a tight budget. Overflowing an agent's context with memory is
a failure mode disguised as thoroughness — it degrades reasoning rather than
improving it.

## Acceptance criteria

- Gate keeps ≥80% of trivial utterances from touching retrieval; fails open when uncertain.
- Hybrid retrieval p95 under 200 ms.
- A matching lesson is retrieved 100% of the time when its `applies_when` matches,
  regardless of semantic similarity — tested end to end.
- Superseded facts are not returned by default.
- Namespace filtering is pre-scoring, verified by test.
- Results respect the per-tier token budget.

## Related

[[Memory Fabric]] · [[Knowledge Graph]] · [[Vector Store]] · [[Working Memory]] ·
[[Agent — Insight Miner]] · [[Orchestrator]]
