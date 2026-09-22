---
title: Idea Schema
tags: [schema]
status: building
implemented_by: [src/genesis/news/ideas.py, ui/src/workspace/panels/trade-ideas.tsx, tests/news/test_ideas.py, src/genesis/research/setup.py, tests/research/test_setup.py]
---

# Idea Schema

The central object. Produced by [[Agent — Idea Synthesizer]], written to the vault at
`10-Ideas/YYYY/MM/` and to the [[Knowledge Graph]].

## The rule

**No invalidation, no idea.** An idea whose author cannot state what would prove it
wrong is not an idea — it's a hope. This is enforced, not encouraged.

> [!info] What the code carries today — `src/genesis/research/schema.py`, 2026-09-18
> A subset of the shape below, and two things it adds:
>
> - **`invalidation` is text** (the condition, stated so a person could check it),
>   and **`stop_price` is the number**. Either records an idea; only the number
>   sizes one — the gate measures risk from entry to stop. A long's `stop_price`
>   must be below its `entry_zone` and a short's above, refused at construction.
> - **`author`** — `human` for the trader's own ideas ([[Agent — Session Plan]]),
>   the agent id for the synthesizer's. One store, one shape, one ranking. The
>   trader's ideas are stored under subject `<symbol>-<direction>`, so restating one
>   updates it and never supersedes the synthesizer's.
> - **`rr` is computed, never stated** — first target against the stop, from the
>   middle of the entry zone — so it cannot disagree with the prices it is made of.
>
> Not carried yet: `suggested_risk_pct` (sizing is the gate's), `evidence` weights,
> `counter_evidence`.

## Schema

```yaml
---
type: idea
id: idea_01J8XS
created: 2026-08-29T07:12:04Z
created_by: idea-synthesizer
trace_id: tr_01J8XP
degraded: false

# What
symbol: NVDA
direction: long                  # long | short
setup: orb_breakout
timeframe: swing                 # scalp | intraday | swing | position
horizon_days: 5                  # how long the thesis has to work

# The trade
entry_zone: [120.60, 121.40]     # a range, never a single price
invalidation: 118.40             # REQUIRED
invalidation_reason: "below the 8/21 fair value gap the thesis is void"
targets: [124.50, 128.00]
rr: 2.1
suggested_risk_pct: 0.5

# Why
thesis: >
  Semis leading a risk-on tape with breadth confirming. NVDA reclaimed the
  prior-day high on 2.4x relative volume after guiding above consensus.
  Structure is HH-HL on daily and weekly.
conflicts: >
  Earnings after the close today — this is a before-the-close trade or nothing.
  Sentiment is at the 81st percentile, so the crowd is already long.

# Evidence — every claim cites a source
evidence:
  - { kind: catalyst, id: cat_01J8XR, weight: 0.3 }
  - { kind: scan_hit, id: scan_01J8XQ, weight: 0.2 }
  - { kind: regime,   id: reg_20260829, weight: 0.2 }
  - { kind: markup,   id: ms_01J8XR4K, weight: 0.2 }
  - { kind: fundamental, id: fun_NVDA_20260829, weight: 0.1 }
counter_evidence:
  - { kind: sentiment, id: sen_01J8XR, note: "81st percentile, divergence bearish" }
  - { kind: mtf, id: mtf_01J8XR, note: "hourly ranging" }

# Scoring
confidence: 0.72
confidence_factors:
  regime_support: +0.10
  multi_evidence_agreement: +0.12
  historical_setup_edge: +0.08
  level_hold_rate: +0.05
  sentiment_divergence: -0.05
  event_risk: -0.08
lessons_checked: [lesson_01J8XY]
lesson_warnings: []

# Lifecycle
status: active                   # active | triggered | invalidated | expired | taken | dismissed
expires: 2026-09-05T20:00:00Z
markup_spec: ms_01J8XR4K
mtf_alignment: 0.85

tags: [semis, orb, breakout, earnings-risk]
---
```

## Status lifecycle

```
 active ──► triggered ──► taken ──► (see [[Trade Journal Schema]])
    │           │
    ├───────────┴──► invalidated     # invalidation price hit
    ├──────────────► expired         # horizon passed, never triggered
    └──────────────► dismissed       # you said no — with a reason
```

Transitions are recorded, never overwritten. `dismissed` requires a reason, which
feeds [[Agent — Insight Miner]]'s selection-bias analysis — the one that eventually
tells you whether the ideas you skip outperform the ones you take.

## Required fields

An idea missing any of these is rejected at write time:

`symbol` · `direction` · `entry_zone` · **`invalidation`** · `invalidation_reason` ·
`thesis` · `confidence` · `evidence` (≥1) · `timeframe` · `expires`

`conflicts` may be empty only if the synthesizer explicitly states it looked and
found none — an absent counter-argument usually means nobody looked.

## Confidence semantics

Confidence must be **calibrated**, not decorative. [[Observability]] tracks outcome
by confidence bucket; if 0.7 ideas don't beat 0.4 ideas over a sample, the scoring
is wrong and gets fixed.

`confidence_factors` shows the arithmetic so a surprising score is inspectable rather
than mysterious.

## Constraints

- `entry_zone` is always a range — a single price is a rejected value
- `invalidation` must be on the losing side of `entry_zone` for the direction
- `rr` is computed, never asserted
- `degraded: true` caps `confidence` at a configured ceiling
- An idea whose symbol has a `disqualifying` fundamental verdict is never written

## Related

[[Agent — Idea Synthesizer]] · [[Markup Spec Schema]] · [[Trade Journal Schema]] ·
[[Obsidian Vault Schema]] · [[Knowledge Graph]] · [[Data Model Overview]]
