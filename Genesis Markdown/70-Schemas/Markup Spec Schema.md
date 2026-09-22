---
title: Markup Spec Schema
tags: [schema, charting]
status: built
implemented_by: [src/genesis/charting/spec.py, tests/charting/test_spec.py, ui/src/components/charts/drawings.ts]
---

# Markup Spec Schema

The formal contract for [[Markup Spec]]. Produced by [[Agent — Chart Markup]],
rendered by [[Charting Engine]], consumed by half the system.

## Schema

```yaml
id: ms_01J8XR4K
created: 2026-08-29T14:20:00Z
created_by: chart-markup
trace_id: tr_01J8XP
degraded: false

symbol: NVDA
timeframe: 1D
as_of: 2026-08-29T20:00:00Z
parent: ms_01J7WQ2A              # this is a re-mark; null for a first mark
bars_ref:
  source: alpaca
  from: 2025-09-01
  to: 2026-08-29
  adjusted: true

annotations:
  - kind: level
    id: ann_01
    price: 122.10
    label: PDH
    type: resistance             # support | resistance | pivot | vwap | poc | value_area
    strength: 0.8                # touches × recency × reaction × volume
    touches: 3
    confluence: ["prior-day high", "value area high"]
    why: "prior-day high, rejected twice intraday on elevated volume"

  - kind: zone
    id: ann_02
    from: 117.90
    to: 118.60
    label: demand
    subtype: fvg                 # fvg | supply | demand | value_area | order_block
    why: "unfilled fair value gap from the 8/21 impulse leg"

  - kind: line
    id: ann_03
    points: [["2026-06-14", 104.20], ["2026-08-27", 119.80]]
    label: rising trendline
    touches: 4
    why: "four touches since the June low"

  - kind: trade_plan
    id: ann_04
    side: long
    entry: 121.00
    stop: 118.40
    targets: [124.50, 128.00]
    rr: 2.1
    idea: idea_01J8XS
    why: "long on PDH reclaim; invalidation below the FVG"

structure:
  trend: up                      # up | down | range
  swing: HH-HL                   # HH-HL | LH-LL | mixed | range
  regime: risk-on
  volatility_pct_rank: 0.34
  atr14: 3.10

render:
  theme: dark
  size: [1600, 900]
  output: 20-Charts/NVDA-2026-08-29-1D.png
  rendered_at: 2026-08-29T14:20:04Z
  render_hash: sha256:...        # determinism check
```

## Annotation kinds

| Kind | Required fields |
|---|---|
| `level` | `price`, `label`, `type`, `why` |
| `zone` | `from`, `to`, `label`, `why` |
| `line` | `points[]` (≥2), `label`, `why` |
| `projection` | `points[]`, `label`, `why` — rendered dashed |
| `marker` | `time`, `price`, `label` — events, fills, news |
| `trade_plan` | `side`, `entry`, `stop`, `why` |
| `fib` | `anchor_from`, `anchor_to`, `retracements[]` |
| `text` | `position`, `content` |

**`why` is required on every annotation** except `text`. An unexplained line on a
chart is noise, and six months later you will not remember what you meant.

## Constraints

- **Immutable.** A re-mark creates a new spec with `parent` set. Never mutate.
- **Annotation cap** — max ~8 (configurable). Restraint is the skill
  ([[Agent — Chart Markup]]).
- **Confluence merging** — annotations within 0.25 ATR merge into one with a
  `confluence` list, rather than appearing as separate levels.
- **Every price traces to a tool result.** No price in a spec may originate from an
  LLM. Enforced by an eval that diffs spec prices against tool outputs.
- **Deterministic render** — same spec + same bars = identical `render_hash`.

## Downstream effects

| Consumer | What it uses |
|---|---|
| [[Charting Engine]] | Renders it — server-side and in the [[Dashboard]] |
| [[Agent — Level Watcher]] | Subscribes to every `level`, `zone`, and `trade_plan` |
| [[Agent — Pattern Recognition]] | Reads the render, with the spec as context |
| [[Agent — Idea Synthesizer]] | Levels become entry zones and invalidations |
| [[Agent — Trade Journal]] | Entry and exit chart snapshots |
| [[Knowledge Graph]] | Each `level` becomes a `level:SYMBOL:PRICE` entity |

That last row is the one that compounds — see [[Charting Family]] for why level
outcome tracking is the system's most distinctive edge.

## Lineage queries

Because specs are immutable and linked by `parent`:

- "How has my read of NVDA evolved?" → walk the parent chain
- "Show me how that level held up" → re-render the old spec against current data
  (`diff_spec` in [[genesis-charting-mcp]])
- "Do I move my levels to justify positions?" → compare spec lineage against position
  timing ([[Agent — Insight Miner]])

## Related

[[Markup Spec]] · [[Charting Engine]] · [[Agent — Chart Markup]] ·
[[Agent — Level Watcher]] · [[genesis-charting-mcp]] · [[Data Model Overview]]
