---
title: Research Directory
tags: [memory, research]
status: built
implemented_by: [src/genesis/research/store.py, src/genesis/research/schema.py, src/genesis/research/findings.py, src/genesis/company/resolve.py, src/genesis/server/reads.py, ui/src/workspace/panels/research.tsx, tests/orchestrator/test_findings.py]
---

# 🗂️ Research Directory

Where everything the [[Research Family]] finds goes, and stays. The Research
page in the terminal is a view of this; so is `50-Research/` in the vault.

## Two writes, one call, in this order

**SQLite is the record.** It is what the UI lists, what
[[Agent — Idea Synthesizer]] reads back as evidence, and what survives someone
reorganising their vault. A folder of markdown is a lovely thing to read and a
terrible thing to query — and *"which notes about semis are still inside their
half-life"* is a query.

**The vault is the mirror**, written after the row commits. A failed file write
degrades the result; it never loses the research. The reverse order would leave
a note on disk with no row: invisible to everything that reads.

## The note

| Field | Why it is not optional |
|---|---|
| `sources` | [[Research Family]]: every claim cites its source. A `topic` note with none is refused at construction |
| `half_life_hours` | Every claim carries one. Evidence past it is **downweighted, not deleted** — `weight()` halves each half-life |
| `confidence` | Capped at 0.5 when `degraded`, by the type rather than by a prompt |
| `caveats` | A `degraded` note with no stated reason is refused |
| `kind` | `topic` · `regime` · `idea` · `symbol` · `finding` — each has one writer and one place in the vault |

## Supersession

One note per `(kind, subject)` is *current*; earlier versions are kept and
readable. Researching Gann twice deepens one note rather than scattering four,
and a directory where yesterday's read silently vanished is one nobody trusts
to check their own reasoning against.

## Findings — the prompt tree

One sentence is several pieces of work. *"Analyse Adobe's earnings — has the
price drifted from fair value?"* is planned by the [[Orchestrator]] as typed
tasks, and each finished task about a company is kept as a `finding`:

| Field | Value |
|---|---|
| `subject` | `"<TICKER>:<task type>"` — e.g. `ADBE:company.valuation`. One current finding per company per intent |
| `trace_id` | The prompt's trace. `?trace=<id>` returns everything one prompt produced |
| `summary` | The agent's own `spoken_summary` |
| `data` | `symbol`, `intent`, `args`, `result` (the agent's data, dropped past 4,000 chars), `evidence` (note ids the task wrote) |
| `half_life_hours` | The evidence note's, else 24 |
| `created_by` | The agent that did the work |

The writer is `PlanRunner` (`research/findings.py`), not an agent. Everything in it is **reflex**:
- **Which company.** The task's `symbol`/`ticker`/`subject`/`company` arg, resolved against the S&P 500 snapshot. No match or an ambiguous one means no finding.
- **Recall.** Before planning, the companies the sentence names (`subjects_in`, a deterministic name/ticker match) are looked up and their findings handed to the planner and the reasoner as context.
- **Reuse.** A task whose finding is **fresh** is not dispatched; its stored summary is spoken with *"As of …"*. Fresh means not degraded, and younger than both its half-life and 24 hours (`REUSE_MAX_HOURS`: a note stays worth reading for months, but a price-versus-value answer changes daily).
- **What reuse skips.** A task another task depends on is always rerun, because dependents read results off the bus.
- **Refresh.** The words *refresh*, *rerun* or *again*, or `--fresh`, skip reuse. Typed and spoken alike.
- **Change.** A rerun whose finding replaced an older one appends *"Last time (date): …"*.

The `analyse <company>` command applies the same freshness rule to the current
`symbol` note.

## Vault layout

Per [[Obsidian Vault Schema]]:

```
50-Research/themes/<subject>.md     topic notes
50-Research/symbols/<TICKER>.md     symbol notes
50-Research/daily/YYYY-MM-DD.md     the regime read
50-Research/findings/<TICKER>/<intent>.md  findings
10-Ideas/YYYY/MM/<symbol>-<date>.md ideas (Idea Synthesizer's folder)
```

## Every note is projected into the graph

One hook, in :meth:`ResearchStore.put`, rather than three agents each
remembering to do it — an agent that forgets writes a note the
[[Research Canvas]] can never show, and the omission is invisible until someone
goes looking for a node that should exist.

| Note kind | Entity | Edges written |
|---|---|---|
| `topic` | `thesis` | `derived_from` → a `document` per cited source |
| `idea` | `idea` | `derived_from` → the notes it cited · `applies_to` → its symbol |
| `regime` | `regime` | — |
| `finding` | `thesis` | `applies_to` → its symbol · `derived_from` → the notes the task wrote |

References only. The graph gets the note's **id**, never its prose, so there is
one copy of the research and the canvas follows a pointer to reach it.

`ResearchStore.backfill()` projects notes written before the graph existed, and
is free to re-run: every write upserts on a stable key.

A graph that will not open is a **caveat, not a lost pass** — the note is
already committed, and the failure is collected next to the vault mirror's,
where the caller already looks for degradations.

## Read API

`GET /v1/research/notes` — the listing, current versions only, bodies omitted.
Filters: `kind`, `subject`, `q` (full-text), `history=<subject>`, `trace=<id>`.
`GET /v1/research/notes/{id}` — one note in full, with its sources.

## Related

[[Memory Fabric]] · [[Research Family]] · [[Agent — Topic Researcher]] ·
[[Obsidian Vault Schema]] · [[Idea Schema]] · [[Knowledge Graph]] ·
[[Research Canvas]]
