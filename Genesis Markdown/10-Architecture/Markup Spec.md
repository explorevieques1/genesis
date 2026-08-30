---
title: Markup Spec
tags: [architecture, charting, schema]
status: spec
implemented_by: []
---

# Markup Spec

A first-class object, not a picture. The markup spec is *what the system believes
about a chart*, expressed declaratively.

Formal schema: [[Markup Spec Schema]]. Renderers: [[Charting Engine]].

## Why it's an object and not an image

| Capability | Enabled by the spec |
|---|---|
| **Re-render** | Draw the same analysis against fresh data six weeks later |
| **Diff** | "Show me how that level held up" — replay the old spec, compare |
| **Watch** | [[Agent — Level Watcher]] subscribes to every level in every active spec |
| **Query** | "Which of my ideas had a level within 1% of the 200-day?" |
| **Explain** | Each annotation carries its own reasoning string |
| **Audit** | The chart in a journal entry is provably the one the agent reasoned about |
| **Consistency** | Dashboard, vault, and vision model all read the same object |

An image can do none of these.

## Shape (illustrative)

```yaml
id: ms_01J8XR4K
symbol: NVDA
timeframe: 1D
as_of: 2026-08-29T20:00:00Z
bars_ref: { source: alpaca, from: 2025-09-01, to: 2026-08-29 }
parent: ms_01J7WQ2A          # this is a re-mark of an earlier spec
created_by: chart-markup
annotations:
  - kind: level
    price: 122.10
    label: PDH
    type: resistance
    strength: 0.8
    touches: 3
    why: "prior-day high, rejected twice intraday"
  - kind: zone
    from: 117.90
    to: 118.60
    label: demand
    why: "unfilled FVG from the 8/21 impulse leg"
  - kind: line
    points: [[2026-06-14, 104.20], [2026-08-27, 119.80]]
    label: rising trendline
    touches: 4
  - kind: trade_plan
    side: long
    entry: 121.00
    stop: 118.40
    targets: [124.50, 128.00]
    rr: 2.1
    why: "long above PDH reclaim, invalidation below the FVG"
structure:
  trend: up
  swing: HH-HL
  regime: risk-on
  volatility_pct_rank: 0.34
render:
  theme: dark
  size: [1600, 900]
  output: 20-Charts/NVDA-2026-08-29-1D.png
```

## Annotation kinds

| Kind | Fields | Notes |
|---|---|---|
| `level` | price, label, type, strength, touches | horizontal S/R, PDH/PDL, POC, VWAP |
| `zone` | from, to, label | supply/demand, FVG, value area, order block |
| `line` | points[], label | trendlines, channels |
| `projection` | points[], label | dashed — expected path, measured move |
| `marker` | time, price, label | event: earnings, fill, news spike |
| `trade_plan` | side, entry, stop, targets, rr | drawn as a risk-reward box |
| `fib` | anchor_from, anchor_to, retracements[] | derived from the dominant swing |
| `text` | position, content | free annotation |

Every annotation carries a `why`. An unexplained line on a chart is noise, and
six months later you will not remember what you meant.

## Immutability and lineage

Specs are **immutable**. Re-marking a symbol creates a new spec with `parent`
pointing at the previous one. The chain is the story of how your read of a symbol
evolved — and [[Agent — Insight Miner]] mines it ("you move your stop down when
price approaches it").

## Who produces and consumes

**Produced by:** [[Agent — Chart Markup]] (primary), [[Agent — Multi Timeframe]],
[[Agent — Strategy Author]] (trade_plan annotations), you (hand edits in the [[Dashboard]]).

**Consumed by:** [[Charting Engine]] (render), [[Agent — Level Watcher]] (subscribe to
levels), [[Agent — Pattern Recognition]] (context for vision), [[Agent — Idea Synthesizer]]
(levels become entries/invalidations), [[Agent — Trade Journal]] (entry/exit snapshots),
[[Knowledge Graph]] (each level becomes an entity).

## Levels become graph entities

Every `level` annotation is written to the [[Knowledge Graph]] as
`level:SYMBOL:PRICE` with edges to the spec, the idea, and any trade taken at it.
Over time this answers: *which of my levels actually hold?* That's a real edge,
and it's only available because the spec is structured.

## Related

[[Markup Spec Schema]] · [[Charting Engine]] · [[Agent — Chart Markup]] ·
[[Agent — Level Watcher]] · [[Idea Schema]] · [[Knowledge Graph]]
