---
title: Episodic Log
tags: [memory]
status: building
implemented_by: [src/genesis/memory/episodic.py, tests/memory/test_episodic.py]
---

# Episodic Log

Append-only. Everything that happened, forever. This is how you answer *"why did it
do that?"* three weeks later — and in a system that trades money, that question will
be asked.

## What goes in

| Category | Examples |
|---|---|
| Utterances | Every directed request, with its transcript and `trace_id` |
| Task lifecycle | Every state transition on the [[Task Bus]] |
| Agent runs | Inputs, outputs, cost, duration, degraded flag |
| Tool calls | Which tool, arguments, result summary, latency, errors |
| Decisions | Risk approvals and rejections with all inputs, approval-mode changes |
| Orders and fills | Mirrored from the [[Trade Ledger]] for causal context |
| Memory writes | What was written where, and by whom |
| Spoken replies | What the system actually said |
| Health events | Agent down, feed stale, reconnects, degradations |

## Shape

```json
{
  "id": "ep_01J8XZ...",
  "ts": "2026-08-29T14:31:02.104Z",
  "trace_id": "tr_01J8XP...",
  "parent_id": "ep_01J8XY...",
  "actor": "screener",
  "kind": "agent.run",
  "summary": "scanned 412 symbols, 9 candidates",
  "payload_ref": "blob_01J8Y0...",
  "cost": { "llm_tokens": 0, "tool_calls": 2, "wall_ms": 1840 },
  "degraded": false
}
```

Large payloads go to a blob store, referenced by id. The log row itself stays small
and fast to scan — that matters when the log holds millions of rows.

## Tracing

`trace_id` links everything descending from one utterance or event. `parent_id`
gives the tree structure within it.

One query answers *"show me everything that happened because I said 'find me a long
setup in semis'"* — including the tool calls, the rejected ideas, the risk check,
and the fill. This is the [[Observability]] audit trail, and it's a requirement for
every order.

## Append-only, enforced

- No `UPDATE`, no `DELETE`. Enforced at the database level, not by convention.
- A correction is a new row that supersedes the old one, with a pointer.
- The log survives every migration; schema changes add columns, never rewrite rows.

## Compaction without loss

The log grows fast — an always-on system generates tens of thousands of rows a day,
most of them routine. [[Agent — Digest]] compacts nightly:

**Collapsible:** repetitive health checks, screener runs with no hits, routine
heartbeats, cache hits, tool calls whose results were unused.

**Never collapsible:**
- Anything with an order, fill, or position change
- Any risk decision
- Any spoken confirmation
- Any idea creation
- Anything referenced by a journal note, lesson, or knowledge-graph entity
- Anything on a `trace_id` that ended in a trade

Collapsing produces a summary row that retains counts and links to the blob store —
the detail is retrievable, just not indexed.

## Queries this must serve

- "Why did it reject that order?" → by proposal id
- "What did it do overnight?" → by time range, actor
- "Everything that came from this utterance" → by `trace_id`
- "Every time the news feed went down last month" → by kind
- "What did the screener see before that trade?" → by trace, walking backwards
- Feeding [[Agent — Insight Miner]] → broad, by time and actor

Index accordingly: `(trace_id)`, `(ts)`, `(actor, ts)`, `(kind, ts)`.

## Acceptance criteria

- `UPDATE` or `DELETE` against the log fails at the database level.
- Full causal reconstruction of any trade from `trace_id` in a single query.
- Compaction never removes anything on the never-collapsible list, verified by test.
- A year of logs remains queryable in under a second for the common queries.

## Related

[[Memory Fabric]] · [[Observability]] · [[Trade Ledger]] · [[Memory Consolidation]] ·
[[Agent — Digest]] · [[Agent — Insight Miner]]
