---
title: Task Bus
tags: [architecture, core]
status: spec
implemented_by: []
---

# Task Bus

The single path all work travels. **Agents never call each other directly** — they
put work on the bus and read results from [[Memory Fabric]].

Reference: [[Repo — gensis-agents]] `shared/task-queue.js`; [[Repo — jarvis]] daemon dispatch.

## Why a bus

- One place to see everything happening → drives the [[Dashboard]] activity feed.
- One place to apply backpressure when the market gets loud.
- One place to persist, so a restart resumes rather than forgets.
- Prevents the agent graph from becoming a tangle of direct calls that nobody can reason about.

## Priority lanes

Higher lanes always drain first. Under load, lower lanes are **shed**, not queued forever.

| Lane | Priority | Contents | Shed under load? |
|---|:--:|---|:--:|
| `execution` | 0 | order place/modify/cancel, fill handling | never |
| `risk` | 1 | risk checks, envelope breaches, kill switch | never |
| `user` | 2 | anything you asked for by voice or dashboard | never |
| `event` | 3 | level touched, news spike, drift alert | drop duplicates |
| `research` | 4 | scans, synthesis, charting, fundamentals | yes — oldest first |
| `maintenance` | 5 | consolidation, re-index, tearsheets | yes — defer to closed market |

Rule: a task in `execution` or `risk` must never wait behind an LLM call in `research`.
Enforce with separate worker pools, not just ordering.

## Task shape

```json
{
  "id": "t_01J8XQ...",
  "type": "chart.markup",
  "lane": "user",
  "agent": "chart-markup",
  "args": { "symbol": "NVDA", "timeframes": ["1D", "1H"] },
  "depends_on": ["t_01J8XP..."],
  "origin": { "kind": "utterance", "ref": "turn_449" },
  "deadline": "2026-08-29T14:31:00Z",
  "idempotency_key": "chart:NVDA:1D,1H:2026-08-29T14:30",
  "attempts": 0,
  "max_attempts": 3,
  "state": "pending"
}
```

**States:** `pending → claimed → running → done | failed | cancelled | shed`

Every transition writes to the [[Episodic Log]] — that log is how you answer
"why did it do that?" three weeks later.

## Dependencies

`depends_on` is a DAG, resolved by the bus. A task whose dependency failed is
cancelled with the parent's reason attached (not silently dropped). The
[[Orchestrator]] is told, so it can speak an honest failure.

## Idempotency

Every task carries an `idempotency_key`. Re-enqueuing the same key while the
original is in flight is a no-op. This matters most in `execution` — see
[[Order And Fill Schema]] — but it also stops the [[Agent — Screener]] from running
the same scan four times when events pile up.

## Events

Events are published to the bus and fan out to subscribers. Shape in [[Event Schema]].

| Event | Typical subscribers |
|---|---|
| `level.touched` | [[Agent — Idea Synthesizer]], [[Orchestrator]] (notify) |
| `order.filled` | [[Agent — Position And PnL Accountant]], [[Agent — Trade Journal]], [[Agent — Execution Quality]] |
| `risk.breached` | [[Kill Switch]], [[Orchestrator]] (speak immediately) |
| `news.spike` | [[Agent — Idea Synthesizer]], [[Agent — Level Watcher]] |
| `agent.down` | [[Agent — Watchdog]], [[Dashboard]] |
| `idea.created` | [[Dashboard]], vault writer |
| `market.open` / `market.close` | [[Daemon And Cadence]] |

## Persistence and restart

The queue lives in SQLite. On restart:
- `running` tasks with a live claim → resume or requeue after the claim TTL expires
- `pending` past their deadline → dropped, logged
- Open order proposals in [[Approval Modes|`confirm`]] → **expired**, never auto-approved

That last rule matters: a restart must never resurrect a stale trade confirmation.

## Backpressure

When queue depth in `research` exceeds a threshold:
1. Deduplicate by `idempotency_key`.
2. Shed oldest `research` tasks.
3. Increase agent cadence intervals (scan every 5 min instead of 1).
4. If `execution`/`risk` latency still degrades → emit `system.degraded`, tell the user.

## Acceptance criteria

- Under 1000 queued research tasks, an `execution` task still starts in <50 ms.
- Killing the process mid-task and restarting resumes without duplicating an order.
- A cancelled parent cancels its dependents, with reasons preserved.
- Every state transition is reconstructible from the [[Episodic Log]] alone.

## Related

[[Daemon And Cadence]] · [[Agent Contract]] · [[Orchestrator Tools]] ·
[[Event Schema]] · [[Episodic Log]] · [[Observability]]
