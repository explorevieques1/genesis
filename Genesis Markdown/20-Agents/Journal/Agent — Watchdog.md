---
title: Agent — Watchdog
tags: [agent, journal]
family: journal
cadence: market-open, market-closed, event
tier: none
status: built
implemented_by: [src/genesis/agents/journal/watchdog.py, src/genesis/journal/health.py, tests/journal/test_agents.py]
---

# 🐕 Agent — Watchdog

## Purpose

Is everything actually running? Heartbeats every agent, MCP server, data feed, and
broker session; reconnects what it can; escalates what it can't.

In an always-on system, silent failure is the real danger. An agent that died three
hours ago and nobody noticed is worse than one that crashes loudly.

## Cadence

`market-open` every 30 s · `market-closed` every 2 min · immediately on any
`agent.down` event.

## What it watches

| Target | Healthy means |
|---|---|
| Each agent | Heartbeat within its interval; not stuck in `running` past its timeout |
| Each MCP server | Session alive, a probe call returns, latency within bounds |
| Market data feed | Connected **and fresh** — a feed serving stale quotes is not healthy |
| Broker session | Authenticated, positions queryable, not rate-limited |
| LLM endpoints | Reachable per tier ([[LLM Model Tiers]]) |
| [[10-Architecture/Voice Stack]] | Mic available, STT/TTS reachable |
| [[Memory Fabric]] | Database writable, not locked, disk space available |
| [[Task Bus]] | Queue depth within bounds, no lane starving |
| [[Trade Ledger]] | Consistent, reconciled recently |
| Disk / memory / CPU | Within thresholds |

**Freshness, not just liveness.** The most dangerous failure mode is a component
that responds correctly while serving stale data. Every data check includes an age
assertion.

## Health states

| State | Meaning | Action |
|---|---|---|
| `healthy` | Everything within bounds | — |
| `degraded` | Working with reduced capability or stale data | Label downstream output; **force [[Approval Modes\|`confirm`]] if execution-path** |
| `down` | Not responding | Restart with backoff; notify |
| `failed` | Restart limit exhausted | Stop restarting; escalate loudly; consider [[Kill Switch]] if execution-path |

## Recovery actions

1. **MCP session lost** → one silent reconnect, then count as a failure
   (pattern: [[Repo — jarvis]] `mcp_runtime.spec.md`)
2. **Agent unresponsive** → restart with exponential backoff (1s → 60s cap)
3. **5 crashes in 10 min** → `failed`, stop restarting, notify
   ([[Daemon And Cadence]] supervision)
4. **Broker session lost** → reconnect, then **reconcile before any new order**
5. **Data feed stale** → attempt resubscribe; mark degraded regardless until fresh
6. **Execution-path component `failed`** → force `confirm` mode; if positions are
   open and the broker is unreachable, trigger [[Kill Switch]]

## Output

```yaml
as_of: 2026-08-29T14:31:00Z
overall: degraded
agents:
  screener:        { state: healthy,  last_run: 30s ago }
  sentiment:       { state: degraded, reason: "social feed unavailable — options-only mode" }
  chart-markup:    { state: healthy,  last_run: 4m ago }
mcp_servers:
  market-data:     { state: healthy,  latency_ms: 82,  data_age_ms: 400 }
  news:            { state: down,     reason: "session lost", retries: 3, next_retry: 45s }
  obsidian:        { state: healthy }
broker:            { state: healthy,  mode: paper, reconciled: 22h ago }
llm:
  nano:  healthy
  small: healthy
  large: { state: degraded, reason: "elevated latency, p95 8.2s" }
voice:             { state: healthy }
resources:         { disk_free_gb: 84, mem_pct: 41 }
approval_mode_forced: null
notifications_sent: ["news MCP down"]
```

## Notification discipline

An alerting system you mute is worthless. Same principle as [[Agent — Level Watcher]].

- **Speak** only: execution-path failures, broker problems, reconciliation issues,
  anything that changes approval mode
- **Dashboard** for everything else
- **Deduplicate** — one notification per issue, not per check cycle
- **Say when it recovers**, once — "News feed is back"
- Never speak a health issue during an active trade confirmation; queue it

## Tools

`system.probe` · `mcp.health` · `genesis-execution.ping` · `taskbus.publish` ·
`memory.write`

## Memory namespace

Read: `shared`
Write: `watchdog`, `shared` (health record — everyone reads it)

## Acceptance criteria

- Detects a killed agent within one cadence interval.
- A stale-but-responsive data feed is marked `degraded`, not `healthy`.
- A `failed` execution-path component forces `confirm` mode, verified by test.
- Broker reconnect always reconciles before permitting a new order.
- Repeated failures produce one notification, not one per cycle.
- Recovery is announced once.

## Related

[[Daemon And Cadence]] · [[Error Handling And Degradation]] · [[Observability]] ·
[[Kill Switch]] · [[Approval Modes]] · [[Journal Family]]
