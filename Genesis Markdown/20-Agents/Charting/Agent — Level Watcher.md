---
title: Agent — Level Watcher
tags: [agent, charting]
family: charting
cadence: market-open, event
tier: none
status: spec
implemented_by: []
---

# 🎯 Agent — Level Watcher

## Purpose

Watch every level in every active [[Markup Spec]] and fire an event the moment price
touches one. No LLM in the path — this is a tight, deterministic loop that must be
fast and must never miss.

It is what turns static analysis into a live system: you marked a level three days
ago, and Genesis tells you the instant it matters.

## Cadence

- `market-open` — streaming where a real-time feed exists, 1-minute poll otherwise
  (see [[Open Questions]] §6)
- Rebuilds its watch list whenever a spec is created or expires

## Inputs

- All active [[Markup Spec]] annotations of kind `level`, `zone`, and `trade_plan`
- Active [[Idea Schema|idea]] entry zones and invalidations
- Open position stops and targets from [[Trade Ledger]]
- Live or near-live price

## Watch types

| Type | Fires when |
|---|---|
| `touch` | Price trades at the level (within a configured tick tolerance) |
| `approach` | Price comes within N ATR — the early warning |
| `break` | Price closes beyond the level on the level's own timeframe |
| `reclaim` | Price closes back through after having broken it |
| `zone_entry` | Price enters a zone (FVG, demand, value area) |
| `invalidation` | An active idea's invalidation condition is met — **highest priority** |

The distinction between `touch` and `break` matters. A wick through a level is not a
break; a close beyond it is. Conflating them produces constant false alerts, which
is how a good alerting system becomes one you ignore.

## Outputs

Events onto the [[Task Bus]] (see [[Event Schema]]):

```yaml
event: level.touched
symbol: NVDA
price: 122.08
level:
  price: 122.10
  label: PDH
  type: resistance
  spec: ms_01J8XR4K
watch_type: touch
context:
  related_idea: idea_01J8XS
  position_open: true
  rel_volume: 2.1
priority: high
```

Priority routing:
- `invalidation` on an open position → **spoken immediately**, interrupts
- `touch` on an active idea's entry zone → spoken, and wakes [[Agent — Idea Synthesizer]]
- `approach` → dashboard only, no voice
- everything else → dashboard + log

## Noise control

The single most important design constraint. An alerting agent that cries wolf gets
muted, and then it is worthless.

- **Cooldown** per level: once fired, suppress for N bars
- **Debounce**: price oscillating across a level fires once, not thirty times
- **Tolerance in ATR**, not cents — a 10¢ tolerance means different things on a $5
  and a $500 stock
- **Expiry**: levels from a spec older than its timeframe's relevance window are
  retired automatically
- **Rate cap**: max N voice-level alerts per hour; excess degrades to dashboard-only
  and the [[Orchestrator]] says "several levels hit, check the board"

## Tools

`market-data.stream` · `market-data.quote` · `memory.read` · `taskbus.publish`

**No LLM.** This agent is `tier: none` by design ([[LLM Model Tiers]]) — it must run
when everything else is degraded.

## Memory namespace

Read: `chart-markup`, `idea-synthesizer`, `ledger`
Write: `level-watcher`

## Level performance tracking

Every fire is recorded against the level entity in the [[Knowledge Graph]], along
with what happened next (held / broke / chopped). Over months this feeds
[[Agent — Insight Miner]]:

> "Your anchored-VWAP levels hold 71% of the time. Your fitted trendlines hold 38%.
> Stop drawing trendlines."

This is the payoff for structuring markup as data. No charting platform can tell you
this about *your own* levels.

## Acceptance criteria

- With a streaming feed, a touch is detected within 1 s; on poll, within one interval.
- A wick through a level does not fire `break`.
- Price oscillating around a level fires once per cooldown, not per tick.
- Runs correctly with all LLM backends unavailable.
- An invalidation on an open position reaches spoken output in under 5 s.
- Every fire is recorded against the level entity for later analysis.

## Related

[[Markup Spec]] · [[Agent — Chart Markup]] · [[Agent — Idea Synthesizer]] ·
[[Event Schema]] · [[Knowledge Graph]] · [[Charting Family]]
