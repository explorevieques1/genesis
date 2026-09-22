---
title: Event Schema
tags: [schema]
status: building
implemented_by: [ui/src/types/events.ts, ui/src/components/EventStream.tsx]
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

### Fleet telemetry

Task lifecycle, consumed by [[Fleet View]]. All `speak: false`, all on the
**low-priority lane** — fleet telemetry must never contend with an `order.filled`
([[Task Bus]] lanes). Shedding this lane under load degrades the fleet view and
nothing else.

| Event | Data | Subscribers |
|---|---|---|
| `task.dispatched` | `task_id`, `parent_task_id`, `agent`, `task_type`, `lane` | [[Fleet View]] |
| `task.started` | `task_id`, `agent` | [[Fleet View]] |
| `task.completed` | `task_id`, `agent`, `wall_ms`, `cost_usd`, `spoken_summary` | [[Fleet View]], [[Observability]] |
| `task.failed` | `task_id`, `agent`, `failure_class`, `code` | [[Fleet View]], [[Agent — Watchdog]] |
| `agent.state_changed` | `agent`, `from`, `to`, `reason` | [[Fleet View]], [[Dashboard]] |
| `memory.read` | `agent`, `namespace`, `layer`, `written_by`, `age_ms` | [[Fleet View]] |
| `memory.written` | `agent`, `namespace`, `layer`, `keys` | [[Fleet View]] |
| `voice.state_changed` | `to` (one of the five [[Genesis Core]] states) | [[Genesis Core]], [[Desktop Shell]] |
| `ui.tier_changed` | `from`, `to`, `reason` | [[Observability]] |

Field names above are the wire names, fixed when the UI was built and mirrored in
`ui/src/types/events.ts`. Four are additions made in that commit, each with a
reason:

- **`lane`** on `task.dispatched` — the fleet view must be able to show *which*
  lane a task rode, because "the low lane was shed and the trading path was not"
  is only observable if the lane is on the wire.
- **`cost_usd` as a string, and `spoken_summary`** on `task.completed` — the
  summary is the [[Agent Contract]] field the [[Dashboard]] activity feed already
  renders, and sending it with the completion saves the UI a second lookup. Cost
  is a string for the same reason every other money value is ([[UI Stack]] §8).
- **`layer`** on `memory.read` / `memory.written` — `namespace` says *whose* data;
  `layer` says *which of the five stores* ([[Memory Fabric]]). The memory
  visualisation needs both and neither implies the other.
- **`memory.written`** — without it the fabric view can show reads but not the
  writes they eventually point back at. Same lane, same `speak: false`.

`ui.tier_changed` is emitted by the UI rather than consumed by it, and is listed
here so the one event the surface *publishes* is in the catalogue rather than
undocumented ([[UI Stack]] §6).

`parent_task_id` is load-bearing: without it the graph can show activity but not
causation. `task.failed` carries the [[Conventions]] failure class
(`transient` / `degraded` / `fatal`), not a free-text reason.

These are emitted as **OpenTelemetry spans** (GenAI semantic conventions) and fanned
out by a collector — see [[Fleet View]] §Instrument once, render twice.

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
