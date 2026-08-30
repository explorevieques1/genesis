---
title: Strategy Schema
tags: [schema, strategy]
status: spec
implemented_by: []
---

# Strategy Schema

The contract between [[Agent — Strategy Author]], [[Agent — Backtest Runner]],
[[Agent — Optimizer]], and [[Agent — Order Manager]]. One object, used by all of them.

## Schema

```yaml
---
type: strategy
id: nq_orb_v3
name: NQ Opening Range Breakout
version: 3
created: 2026-08-15T10:00:00Z
created_by: strategy-author
derived_from: idea_01J8XS
status: paper                # draft | backtested | paper | live_confirm | live_auto | retired

universe: [NQ]
timeframe: 5m
assumed_regime: trending     # checked by [[Agent — Regime And Correlation]]
direction: long_only         # long_only | short_only | both

entry:
  conditions:
    - { kind: orb_break,   direction: long, minutes: 15, weight: 1.0 }
    - { kind: rel_volume,  op: ">=", value: 1.5,         weight: 0.8 }
    - { kind: trend_align, ma: 20, direction: up,        weight: 0.6 }
  logic: AND                 # AND | OR | IF_THEN
  confirmation_bars: 1       # signal must hold N bars before acting
  order_type: limit
  limit_offset_ticks: 2

filters:
  - { kind: session, from: "09:45", to: "11:30", tz: America/New_York }
  - { kind: atr_noise, min_atr_pct: 0.3 }
  - { kind: skip_if_event, impact: high, within_min: 30 }
  - { kind: max_trades_per_day, value: 3 }

exit:
  stop:   { kind: atr, mult: 1.5 }
  target: { kind: r_multiple, value: 2.0 }
  trail:  { kind: atr, mult: 2.0, after_r: 1.0 }
  breakeven: { after_r: 0.75 }
  time:   { kind: session_close }
  partial: [{ at_r: 1.0, pct: 50 }]

sizing:
  kind: risk_pct             # risk_pct | fixed_qty | kelly_fraction | volatility_target
  value: 0.5

cooldown_bars: 12

params:                      # optimizable, with ranges
  orb_minutes: { value: 15,  range: [5, 30],   step: 5 }
  rel_volume:  { value: 1.5, range: [1.0, 3.0], step: 0.1 }
  atr_mult:    { value: 1.5, range: [1.0, 3.0], step: 0.25 }

envelope_override:           # may only be STRICTER than global
  max_risk_per_trade_pct: 0.5
  max_position_pct: 3.0

approval_mode: confirm       # may only be STRICTER than global

backtests: [bt_01J8XT]
optimizations: [opt_01J8XU]
promotion: { stage: paper, record: promo_01J8XV }

notes: "Derived from idea_01J8XS. Positive live edge on ORB per lesson_01J8XZ."
---
```

## Required for validity

A strategy missing any of these is **refused**, not warned about:

`entry.conditions` (≥1) · **`exit.stop`** · `sizing` · `timeframe` · `universe` ·
`assumed_regime`

A strategy without a stop is not a strategy. [[Agent — Strategy Author]] refuses to
emit one and [[genesis-backtest-mcp]] refuses to run one.

## Condition primitives

Entry and exit conditions compose from a **fixed vocabulary** — indicator, volume,
range, time, price, structure. An LLM may not invent a primitive; if a request can't
be expressed, the author says which part is unsupported.

Lineage: [[Repo — gensis-agents]] `agents/alert-agent` — 20+ condition types grouped
by category, AND/OR/IF-THEN logic, per-condition weights, lookback confirmation,
cooldown gate, plus volume-spike / ATR-noise / trend-alignment / session filters.
**Reuse that vocabulary.**

## Status lifecycle

```
 draft ──► backtested ──► paper ──► live_confirm ──► live_auto
                            ▲           │              │
                            └───────────┴──────────────┘
                                    demotion
                                        │
                                    retired
```

Forward transitions require [[Paper To Live Promotion]] criteria plus your explicit
approval. Backward transitions are automatic and need no approval.

## Stricter-only overrides

`envelope_override` and `approval_mode` may only **tighten** relative to global.
Effective values are `min(global, strategy)` on the risk/autonomy scale. A strategy
can never widen a global limit ([[Risk Envelope]]).

New strategies typically run at a fraction of the global envelope until they earn more.

## Versioning

Changing rules increments `version`; the prior version is retained with its
backtests. This matters because [[Agent — Backtest Vs Live Drift]] compares live
results against the backtest of *the version that actually traded*.

Optimizing parameters within existing ranges does **not** bump the version, but does
increment the cumulative trial count in [[Agent — Optimizer]].

## Related

[[Agent — Strategy Author]] · [[Agent — Backtest Runner]] · [[Agent — Optimizer]] ·
[[Paper To Live Promotion]] · [[Risk Envelope]] · [[Data Model Overview]]
