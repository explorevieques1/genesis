---
title: Memory Fabric
tags: [memory, moc, core]
status: spec
implemented_by: []
---

# 🧠 Memory Fabric

Five layers, each with a distinct job. Obsidian is the **human** view; the graph and
vector store are the **machine** view; they are kept in sync.

Pattern reference: [[Repo — jarvis]] `src/jarvis/memory/` — `graph.py`, `graph_ops.py`,
`recall_gate.py`, `conversation.py`, `summariser.spec.md`.

## The five layers

| Layer | Store | Contents | Lifetime |
|---|---|---|---|
| [[Working Memory]] | in-memory ring + SQLite | last N turns, current task list, ambient buffer, what's on screen | minutes–hours, rolls off |
| [[Episodic Log]] | SQLite, append-only | every request, agent run, tool call, decision, outcome | forever; summarised, never deleted |
| [[Knowledge Graph]] | SQLite / embedded graph | entities + typed edges: tickers, levels, setups, theses, lessons | forever; consolidated nightly |
| [[Vector Store]] | sqlite-vec / LanceDB | embeddings of ideas, notes, research, chart descriptions, corpus chunks | forever; re-embed on model change |
| [[Trade Ledger]] | SQLite, append-only, double-entry | orders, fills, positions, P&L, fees | forever; reconciled daily |

Plus the mirror: **[[Obsidian Vault Schema]]** — the human-readable, human-editable
projection of all of it.

## Why five and not one

Each layer answers a different question, and conflating them makes all of them worse:

- Working: *what are we talking about right now?*
- Episodic: *what happened, and why did it do that?*
- Graph: *what do we believe, and how is it connected?*
- Vector: *what else is like this?*
- Ledger: *what is actually true about money?*

A single store optimized for one of these is bad at the rest. In particular, the
ledger must never be approximate, and the vector store must never be authoritative.

## Access paths

```
                  ┌──────────────────────────────────┐
   agent asks ───►│  [[Recall Pathways|RECALL GATE]] │ ← cheap: is memory needed at all?
                  └────────────┬─────────────────────┘
                               │ yes
                  ┌────────────▼─────────────────────┐
                  │        HYBRID RETRIEVAL          │
                  │  vector ∪ graph ∪ recency        │
                  │  + priority (lessons always)     │
                  └────────────┬─────────────────────┘
                               ▼
                        ranked, deduplicated,
                        namespace-filtered results
```

The gate exists because most utterances need no memory at all. Paying for retrieval
on "what time does the market open?" is how a voice assistant becomes slow.

## Namespaces

Every agent reads and writes within declared namespaces ([[Agent Contract]]).

| Namespace | Single writer | Readable by |
|---|---|---|
| `shared` | orchestrator + consolidation | everyone |
| `<agent-id>` | that agent | that agent + declared readers |
| `ledger` | [[Agent — Position And PnL Accountant]] | execution + journal families |
| `lessons` | [[Agent — Insight Miner]] | everyone, **elevated recall priority** |

Single-writer namespaces prevent the class of bug where two agents disagree about
the same fact and both are "right."

## Sync with Obsidian

Bidirectional, with clear ownership:

- **Agents → vault**: ideas, journal entries, research notes, charts, lessons,
  strategy reports. Written continuously.
- **Vault → memory**: your edits are picked up on the nightly [[Memory Consolidation]]
  pass. If you correct a thesis or add a note to a lesson, the system learns it.
- **Conflict rule**: your edit wins. Always. If you changed a note the system also
  changed, yours is kept and the system's version is preserved in the note's history.

## What is never compressed

[[Memory Consolidation]] and [[Agent — Digest]] compress process, never decisions.
Permanently preserved verbatim:

- Every order, fill, and position change
- Every idea with its thesis and evidence
- Every risk decision with its inputs
- Every spoken confirmation
- Everything referenced by a journal note or a lesson

Everything else — the 78 screener runs, the routine health checks — can be collapsed.

## Acceptance criteria

- Recall gate keeps ≥80% of trivial utterances from touching retrieval.
- Retrieval p95 under 200 ms.
- A fact corrected in Obsidian is reflected in agent behaviour the next day.
- Nothing on the never-compress list is ever lost, verified by a long-run test.
- Namespace isolation holds: an agent cannot write outside its declared namespaces.

## Related

[[Recall Pathways]] · [[Memory Consolidation]] · [[Obsidian Vault Schema]] ·
[[Data Model Overview]] · [[Agent Contract]]
