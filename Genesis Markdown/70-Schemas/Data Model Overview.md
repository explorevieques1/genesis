---
title: Data Model Overview
tags: [schema, moc]
status: spec
implemented_by: []
---

# Data Model Overview

The core objects and how they relate. **Build to these exactly** — they are the
contracts between agents.

## The objects

| Object | Note | Produced by | Lives in |
|---|---|---|---|
| **Idea** | [[Idea Schema]] | [[Agent — Idea Synthesizer]] | vault `10-Ideas/` + graph |
| **Markup Spec** | [[Markup Spec Schema]] | [[Agent — Chart Markup]] | memory + vault `20-Charts/` |
| **Strategy** | [[Strategy Schema]] | [[Agent — Strategy Author]] | vault `40-Strategies/` |
| **Order / Fill** | [[Order And Fill Schema]] | [[Agent — Order Manager]] | [[Trade Ledger]] |
| **Journal Entry** | [[Trade Journal Schema]] | [[Agent — Trade Journal]] | vault `30-Journal/` |
| **Event** | [[Event Schema]] | everything | [[Task Bus]] + [[Episodic Log]] |
| **Lesson** | in [[Agent — Insight Miner]] | [[Agent — Insight Miner]] | `lessons` + vault `60-Lessons/` |
| **Risk Envelope** | [[Risk Envelope]] | you | config, signed |

## How they connect

```
  catalyst ──┐
  scan hit ──┼──► IDEA ──► MARKUP SPEC ──► levels ──► [[Agent — Level Watcher]]
  regime   ──┘     │
                   ├──► STRATEGY ──► backtest ──► [[Paper To Live Promotion]]
                   │
                   └──► ORDER ──(risk approval)──► FILL ──► POSITION
                                                      │
                                                      ▼
                                              JOURNAL ENTRY
                                                      │
                                                      ▼
                                                  LESSON ──► back into IDEA
```

The loop closes at the bottom. A lesson derived from a journal entry changes the
confidence of a future idea ([[Recall Pathways]] priority recall). That's the
compounding mechanism.

## Universal fields

Every object carries these. They are not optional.

| Field | Why |
|---|---|
| `id` | ULID-style, sortable by creation time |
| `created` / `as_of` | UTC, always |
| `created_by` | Which agent |
| `trace_id` | Links back to the utterance or event that caused it ([[Observability]]) |
| `degraded` | Was any input stale or partial? ([[Error Handling And Degradation]]) |

`trace_id` is what makes the audit chain work — from a fill, back through the order,
the idea, the research, to the words you said. Missing it anywhere breaks the chain.

## Identity conventions

| Object | Prefix |
|---|---|
| Idea | `idea_` |
| Markup spec | `ms_` |
| Strategy | slug, e.g. `nq_orb_v3` |
| Order proposal | `ord_prop_` |
| Order | `ord_` |
| Fill | `fill_` |
| Approval | `appr_` |
| Journal entry | `jrn_` |
| Lesson | `lesson_` |
| Backtest run | `bt_` |
| Optimization | `opt_` |
| Episodic entry | `ep_` |
| Trace | `tr_` |

## Types

- **Money:** `Decimal`, never `float`, with explicit currency ([[Conventions]])
- **Quantities:** integer for shares/contracts; `Decimal` if fractional
- **Time:** UTC ISO-8601 in storage. Market times are converted at the edge, and
  always carry their timezone.
- **Prices:** `Decimal` at the instrument's tick precision
- **Percentages:** stored as decimals (`0.05` = 5%), displayed as percent
- **Confidence:** `0.0`–`1.0`
- **R multiples:** `Decimal`, signed

## Versioning

Objects that change over time version rather than mutate:

- **Markup specs are immutable** — a re-mark creates a child with `parent` set
- **Strategies version** — `nq_orb_v3` is version 3; earlier versions retained with
  their backtests
- **Risk envelopes version and are signed** ([[Risk Envelope]])
- **Ideas have status transitions**, not edits: `active → triggered → invalidated |
  expired | taken`

The reason is uniform: you must be able to answer "what did the system believe *at
the time*?" after the fact.

## Related

[[Idea Schema]] · [[Markup Spec Schema]] · [[Strategy Schema]] ·
[[Order And Fill Schema]] · [[Trade Journal Schema]] · [[Event Schema]] ·
[[Memory Fabric]]
