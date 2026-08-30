---
title: genesis-memory-mcp
tags: [mcp, memory]
status: spec
implemented_by: []
---

# genesis-memory-mcp

Query and write [[Memory Fabric]] as tools — from any agent, and from Claude Code.

## Tools exposed

| Tool | Behaviour |
|---|---|
| `recall` | Hybrid retrieval per [[Recall Pathways]]. Namespace-filtered, token-budgeted, deduplicated. |
| `remember` | Write to the caller's namespace. Typed by layer. |
| `graph_query` | Traverse the [[Knowledge Graph]] by entity and edge type |
| `entity` | Get one entity with its edges and history |
| `ledger_query` | Read-only [[Trade Ledger]] access: positions, fills, P&L, by any slice |
| `episodic_trace` | Everything on a `trace_id` — the audit chain |
| `lessons_for` | Lessons whose `applies_when` matches a given context |
| `vault_read` / `vault_write` | Obsidian notes (delegates to the Obsidian MCP with schema validation) |

## Why ours

Namespace enforcement has to live at the tool boundary. If agents could query the
memory database directly, [[Agent Contract]] namespace rules would be advisory. Here
they're enforced before scoring, so an agent cannot even infer the existence of
memory it shouldn't see ([[Recall Pathways]]).

It also gives **Claude Code** a first-class way to read the system's state while
building it: "what did the screener find last Tuesday?" is a tool call, not a
database spelunking session.

## Namespace enforcement

Every call carries the caller's agent id. The server:

1. Resolves the agent's declared read/write namespaces
2. Filters candidates **before** scoring
3. Rejects writes outside the declared write namespaces
4. Enforces single-writer namespaces (`ledger`, `lessons`) at the server level

A misconfigured allow-list produces a rejection, not a silent leak.

## `lessons_for` — the important one

```
lessons_for(context: {
  symbol: "NVDA", setup: "orb_breakout",
  consecutive_losses: 2, size_vs_avg: 1.6, session: "14:45"
}) → [lesson_01J8XY, ...]
```

This is the mechanism that makes the learning loop fire ([[Journal Family]]). A
lesson retrieved only when semantically similar text appears is a lesson that never
fires when it matters. Matching on **structured context** is what makes it reliable,
and [[Agent — Idea Synthesizer]] is required to call it.

## Write typing

`remember` is typed by target layer, because writing a durable belief and writing a
transient observation are different acts:

```yaml
remember:
  layer: knowledge_graph      # working | episodic | knowledge_graph | vector
  kind: entity                # entity | edge | observation
  namespace: chart-markup
  data: { type: level, symbol: NVDA, price: 122.10, ... }
```

The [[Trade Ledger]] is **not** writable through this tool by anyone except
[[Agent — Position And PnL Accountant]], enforced server-side.

## Access

`recall`, `remember`, `graph_query`, `entity`, `lessons_for` — all agents, scoped.
`ledger_query` — execution and journal families, read-only.
`episodic_trace` — [[Agent — Insight Miner]], [[Agent — Performance Analyst]],
[[Agent — Watchdog]], and Claude Code.

## Acceptance criteria

- Namespace filtering happens pre-scoring; an agent cannot detect out-of-namespace
  results by count or timing.
- A write outside a declared namespace is rejected.
- Single-writer namespaces reject writes from any other agent.
- `lessons_for` returns matching lessons 100% of the time on structured context match.
- `recall` p95 under 200 ms.
- Ledger writes through this server are impossible except from the accountant.

## Related

[[Memory Fabric]] · [[Recall Pathways]] · [[Knowledge Graph]] · [[Trade Ledger]] ·
[[Agent Contract]] · [[MCP Gateway]]
