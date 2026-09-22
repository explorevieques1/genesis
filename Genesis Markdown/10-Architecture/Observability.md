---
title: Observability
tags: [architecture]
status: built
implemented_by: [src/genesis/observability.py, src/genesis/cli.py, tests/test_observability.py, ui/src/views/TraceView.tsx, tests/test_fleet_health.py]
---

# Observability

You must be able to answer *"why did it do that?"* three weeks later, from the logs
alone. In a system that trades money autonomously, this is a safety feature.

## Three streams

| Stream | Audience | Store |
|---|---|---|
| **Console / CLI** | you, live | stdout, emoji-prefixed, indented |
| **Structured log** | machines, debugging | JSONL on disk, rotated |
| **[[Episodic Log]]** | agents, audit, [[Agent — Insight Miner]] | SQLite, permanent |

## Console style

House style from [[Conventions]] — leading emoji per line, indentation for hierarchy:

```
🌅 07:00 Pre-market brief
  📊 Regime: risk-on · VIX 14.2 (−8% w/w) · breadth 62% above 50d
  📰 Catalysts (3)
    ⚠️  08:30 CPI — high impact
    📈 NVDA earnings AMC
  🔍 Screener: 412 scanned → 9 candidates
  💡 Ideas ranked (4)
    🥇 NVDA long · conf 0.72 · entry 121.00 · inval 118.40
  🗂️  Wrote 50-Research/daily/2026-08-29.md
  🗣️  Ready to brief on request
```

## Structured event

```json
{
  "ts": "2026-08-29T11:00:04.221Z",
  "level": "info",
  "agent": "screener",
  "task_id": "t_01J8XQ...",
  "trace_id": "tr_01J8XP...",
  "event": "scan.completed",
  "data": { "universe": 412, "candidates": 9, "scan": "orb_breakout" },
  "cost": { "llm_tokens": 0, "tool_calls": 2, "wall_ms": 1840 },
  "degraded": false
}
```

## Tracing

Every user utterance opens a `trace_id`. Every task, tool call, LLM call, memory
write, order, and fill descending from it carries that id. One query reconstructs
the entire causal chain from *"find me a long setup in semis"* to a fill.

The [[Idea Schema]] and [[Trade Journal Schema]] both store `trace_id`, so a journal
entry links back through the idea, through the research, to the words you said.

## Metrics

| Metric | Why it matters |
|---|---|
| Agent latency p50/p95, by agent | catches a slow agent before it starves the [[Task Bus]] |
| Task queue depth by lane | early warning of backpressure |
| Tool error rate by MCP server | which feed is flaky |
| LLM spend by agent by day | an expensive agent should be visible, not silent |
| Tier distribution | ≥90% of calls should be nano/small ([[LLM Model Tiers]]) |
| **Idea → trade conversion** | are the ideas actually actionable? |
| **Idea outcome by confidence bucket** | is the confidence score calibrated at all? |
| **Live vs. backtest drift** | see [[Agent — Backtest Vs Live Drift]] |
| Risk rejections by rule | which limit actually binds |
| Reconciliation mismatches | must be zero; non-zero → [[Kill Switch]] |
| Voice: wake→first-word latency | the felt responsiveness of the whole system |

The two in bold are the ones that tell you whether the system is *worth running*.
Everything else tells you whether it's healthy.

## Health

[[Agent — Watchdog]] heartbeats every agent, MCP server, data feed, and broker
session on a 30 s cadence. Status surfaces in the [[Dashboard]] agent grid and, for
fatal conditions, is spoken immediately.

Health is not just "process alive" — it includes **data freshness**. A feed that
returns stale quotes is `degraded`, not `healthy`, and any output built on it is
labelled.

## Audit trail

For every order, the record must contain: the utterance or event that started it,
the idea it implements, the research that supported the idea, the risk check result
with the numbers, the approval (who/how/when), the broker response, and the fill.

If any link is missing, the audit is broken — treat that as a bug of the same
severity as a risk-gate bypass.

## Acceptance criteria

- Given a fill from three weeks ago, reconstruct the full causal chain in one query.
- Every log line has `trace_id`, `agent`, and `event`.
- A degraded data feed produces visibly labelled output, not silent bad data.
- Dashboard shows current spend and agent health without a page refresh.

## Related

[[Episodic Log]] · [[Task Bus]] · [[Agent — Watchdog]] · [[Conventions]] · [[Dashboard]]
