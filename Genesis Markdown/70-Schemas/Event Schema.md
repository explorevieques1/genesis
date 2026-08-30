---
title: Event Schema
tags: [schema]
status: spec
implemented_by: []
---

# Event Schema

Events published on the [[Task Bus]], consumed by agents, the [[Dashboard]], and the
[[Episodic Log]].

## Envelope

```yaml
event: level.touched              # noun.past-tense, always
id: evt_01J8XZ
ts: 2026-08-29T14:35:02.104Z
trace_id: tr_01J8XP
source: level-watcher
priority: high                    # critical | high | normal | low
speak: true                       # should the [[Orchestrator]] say it?
dedupe_key: "level:NVDA:122.10:touch"
data: { ... }                     # event-specific
```

`dedupe_key` collapses repeats within a cooldown window — the mechanism that keeps
[[Agent — Level Watcher]] from firing thirty times as price oscillates.

## The catalogue

### Market and research

| Event | Data | Subscribers |
|---|---|---|
| `market.open` / `market.close` | session, venue | [[Daemon And Cadence]] |
| `regime.changed` | from, to, confidence | [[Agent — Idea Synthesizer]], [[Agent — Regime And Correlation]] |
| `news.spike` | symbols, catalyst id, magnitude | [[Agent — Idea Synthesizer]], [[Agent — Level Watcher]] |
| `scan.hit` | scan, candidates | [[Agent — Idea Synthesizer]] |
| `idea.created` | idea id, confidence | [[Dashboard]], vault writer |
| `idea.invalidated` | idea id, reason | [[Orchestrator]] (speak), [[Agent — Trade Journal]] |
| `strategy.assumption_broken` | strategy, assumed, current | [[Orchestrator]], demotion logic |

### Charting

| Event | Data | Subscribers |
|---|---|---|
| `level.touched` | symbol, price, level, spec, watch_type | [[Agent — Idea Synthesizer]], [[Orchestrator]] |
| `level.broken` | + close confirmation | same |
| `zone.entered` | symbol, zone, spec | same |
| `markup.created` | spec id | [[Agent — Level Watcher]], [[Dashboard]] |

### Execution — the critical lane

| Event | Data | Priority |
|---|---|---|
| `order.proposed` | proposal id, symbol, side, qty | normal |
| `order.approved` / `order.rejected` | approval id, decision, binding check | **high**, spoken |
| `order.placed` | order id, broker id | high |
| `order.filled` | fill id, price, qty | **high**, spoken |
| `order.cancelled` / `order.expired` | order id, reason | normal |
| `position.opened` / `position.closed` | symbol, qty, pnl | high |
| `risk.breached` | rule, value, limit | **critical**, spoken, may trigger [[Kill Switch]] |
| `propfirm.warning` | rule, headroom | **critical**, spoken |
| `reconciliation.failed` | mismatch detail | **critical**, triggers halt |
| `halt.engaged` | trigger, level | **critical** |

Execution events never share a worker pool with research events
([[Task Bus]] lanes).

### System health

| Event | Data | Subscribers |
|---|---|---|
| `agent.down` / `agent.recovered` | agent, reason | [[Agent — Watchdog]], [[Dashboard]] |
| `mcp.session_lost` | server, retries | [[Agent — Watchdog]] |
| `data.stale` | feed, age_ms | [[Agent — Watchdog]], anything using that feed |
| `system.degraded` | components | [[Orchestrator]], forces `confirm` mode |
| `budget.exceeded` | agent, spend | [[Observability]] |

## Priority semantics

| Priority | Behaviour |
|---|---|
| `critical` | Speak immediately, interrupt TTS, notify every surface, never deduplicated away |
| `high` | Speak if you're present; always to the dashboard |
| `normal` | Dashboard and log |
| `low` | Log only |

The `speak` flag is a hint; [[Voice UX]]'s "when it speaks unprompted" rules are
authoritative and can suppress a `speak: true` event (rate caps, active confirmation
dialogue).

## Ordering and delivery

- **Per-symbol ordering guaranteed** for execution events — you cannot process a
  fill before the placement that caused it
- **At-least-once delivery**; consumers must be idempotent on `id`
- Events are persisted to the [[Episodic Log]] **before** dispatch, so nothing is
  lost on a crash mid-fanout
- A slow subscriber never blocks the publisher

## Related

[[Task Bus]] · [[Observability]] · [[Voice UX]] · [[Dashboard]] ·
[[Agent — Level Watcher]] · [[Data Model Overview]]
