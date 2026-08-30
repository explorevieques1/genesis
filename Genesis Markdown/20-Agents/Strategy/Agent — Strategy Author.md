---
title: Agent — Strategy Author
tags: [agent, strategy]
family: strategy
cadence: on-demand
tier: large
status: spec
implemented_by: []
---

# ✍️ Agent — Strategy Author

## Purpose

Turn a plain-English idea into a **testable strategy object** — entries, exits,
sizing, filters, and the regime it assumes. Also emits PineScript when you want the
alert on TradingView rather than in Genesis.

This is the agent behind "Genesis, build me a strategy that buys the ORB breakout in
semis when relative volume is above two."

## Cadence

`on-demand` only.

## Inputs

- A natural-language description, or an [[Idea Schema|idea]] to generalize into a rule
- Available condition primitives (indicators, structure, session, volume, volatility)
- Existing strategies (to avoid building a near-duplicate of one you already have)
- Costs and constraints from [[Config And Secrets]]

## Outputs

A strategy object per [[Strategy Schema]]:

```yaml
id: nq_orb_v3
name: NQ Opening Range Breakout
version: 3
universe: [NQ]
timeframe: 5m
assumed_regime: trending          # checked later by [[Agent — Regime And Correlation]]
entry:
  conditions:
    - { kind: orb_break, direction: long, minutes: 15 }
    - { kind: rel_volume, op: ">=", value: 1.5 }
    - { kind: trend_align, ma: 20, direction: up }
  logic: AND
  confirmation_bars: 1            # signal must hold N bars
filters:
  - { kind: session, from: "09:45", to: "11:30", tz: America/New_York }
  - { kind: atr_noise, min_atr_pct: 0.3 }
  - { kind: skip_if_event, impact: high, within_min: 30 }
exit:
  stop:   { kind: atr, mult: 1.5 }
  target: { kind: r_multiple, value: 2.0 }
  trail:  { kind: atr, mult: 2.0, after_r: 1.0 }
  time:   { kind: session_close }
sizing:
  kind: risk_pct
  value: 0.5                      # % of equity risked per trade
cooldown_bars: 12
notes: "derived from idea_01J8XS; user has positive live edge on ORB (see lessons)"
```

Plus, optionally, a compiled **PineScript** alert or indicator.

## Condition primitives

Entry/exit conditions are composed from a fixed vocabulary, grouped by category —
indicator, volume, range, time, price, structure. Roughly 20+ types, with AND / OR /
IF-THEN logic, per-condition weights, lookback confirmation, and a cooldown gate.

Lineage: [[Repo — gensis-agents]] `agents/alert-agent` implements exactly this
condition builder plus volume-spike, ATR-noise, trend-alignment, and session filters.
Reuse the vocabulary rather than inventing a new one.

## Tools

`strategy.primitives` · `strategy.validate` · `pine.compile` · `memory.read` ·
`memory.write` · `obsidian.write` · `taskbus.dispatch` (to queue a backtest)

## Memory namespace

Read: `shared`, `idea-synthesizer`, `lessons`, `performance-analyst`, strategy library
Write: `strategy-author`

## System prompt sketch

> You are the Strategy Author. You translate ideas into precise, testable rules.
>
> **Every strategy must be falsifiable and complete.** Entry, exit, stop, sizing,
> and session. A strategy without a stop is not a strategy — refuse to emit one.
>
> Use only the condition primitives available to you. If the user's description
> requires something that doesn't exist, say exactly which part cannot be expressed
> and propose the closest supported alternative. **Never invent a primitive.**
>
> Declare `assumed_regime` honestly. Most strategies only work in one kind of tape,
> and the system later checks whether that regime still holds.
>
> Prefer few conditions. Every added condition is a degree of freedom and a step
> toward curve-fitting. Three conditions that make sense beat seven that fit history.
>
> Check `lessons` and existing strategies. If this is a near-duplicate of something
> that already failed, say so before building it again.
>
> You never place trades and never declare a strategy validated — that requires
> [[Agent — Backtest Runner]] and [[Paper To Live Promotion]].

## Acceptance criteria

- Refuses to emit a strategy without a stop and a sizing rule.
- Uses only existing primitives; unsupported requests get a specific explanation.
- Auto-queues a backtest on creation.
- Detects and flags a near-duplicate of an existing strategy.
- Generated PineScript compiles without error on a test corpus.
- `assumed_regime` is populated on every strategy.

## Related

[[Strategy Schema]] · [[Agent — Backtest Runner]] · [[Agent — Optimizer]] ·
[[Agent — Idea Synthesizer]] · [[Strategy Family]] · [[Repo — gensis-agents]]
