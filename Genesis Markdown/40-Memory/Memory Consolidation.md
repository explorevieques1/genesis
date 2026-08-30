---
title: Memory Consolidation
tags: [memory]
status: spec
implemented_by: []
---

# Memory Consolidation

The nightly job that keeps memory useful rather than merely large. Runs at 21:00 ET
alongside [[Agent — Digest]] ([[Daemon And Cadence]]).

Without it, memory grows monotonically and retrieval quality falls — the system
"remembers" more and knows less.

## The passes

### 1. Roll off working memory
Summarise the day's [[Working Memory]] into [[Episodic Log]] entries. Extract durable
facts into the [[Knowledge Graph]]. Discard the transient.

### 2. Merge duplicate entities
The same thing referred to differently becomes one entity:

- Levels within a tick tolerance on the same symbol → one `level`, touch counts summed
- The same thesis phrased differently → one `thesis`, both phrasings kept as aliases
- The same setup under two names → one `setup`

Merging preserves both sources. It is not deletion — it is recognition.

### 3. Promote observations to beliefs
An observation confirmed repeatedly becomes a `belief` ([[Knowledge Graph]]) with a
confidence derived from its confirmation-to-contradiction ratio.

Threshold: minimum observations, and a majority confirming. One confirmation is a
coincidence.

### 4. Weaken and retire
- Beliefs contradicted lose confidence
- Beliefs not confirmed within a decay window are marked `weakening`, then `retired`
- Ideas past their timeframe without triggering are closed as `expired`
- Levels whose spec is past its relevance window are retired from
  [[Agent — Level Watcher]]

A belief nobody has confirmed in six months is not knowledge. The graph should say so.

### 5. Absorb your Obsidian edits
Scan the vault for changes since the last pass. If you corrected a thesis, annotated
a lesson, or added a note to a journal entry, it is read back into memory.

**Your edit always wins.** If the system also changed that note, yours is kept and
the system's version is preserved in history. This is what makes the vault a real
two-way surface rather than a log you happen to be able to read.

### 6. Compact the episodic log
Collapse repetitive process rows, preserving the never-collapsible list
([[Episodic Log]]).

### 7. Re-embed what changed
New and modified content is embedded into the [[Vector Store]]. Near-duplicates are
detected and skipped rather than accumulated.

### 8. Integrity checks
- Rebuild positions from fills; compare to stored ([[Trade Ledger]])
- Verify every fill has an `approval_id`
- Verify no orphaned entities or dangling edges in the graph
- Verify vault ↔ memory link integrity

Failures here are alerts, not silent fixes. A consolidation job that quietly repairs
inconsistencies hides the bug that caused them.

## Guarantees

**Never lost, ever:**
orders · fills · position changes · risk decisions with their inputs · spoken
confirmations · ideas with their theses and evidence · lessons · anything a journal
note or lesson references · anything on a `trace_id` that ended in a trade.

**Freely compressible:**
routine health checks · screener runs with no hits · cache hits · heartbeats · tool
calls whose results were never used · ambient speech that was never addressed.

The rule, stated once: **compress process, preserve decisions.**

## Failure behaviour

Consolidation is best-effort and must never corrupt. If a pass fails:

- The pass is skipped, logged, and retried tomorrow
- Partial work is rolled back — no half-merged entities
- Repeated failure of the same pass raises an alert
- The system runs correctly on un-consolidated memory; it just retrieves less well

Never let a consolidation bug take down trading.

## Acceptance criteria

- Runs nightly in under 10 minutes at expected volume.
- Nothing on the never-lost list is ever removed, verified by a long-running test.
- Vault edits are reflected in agent behaviour the next day, tested end to end.
- A deliberately failed pass rolls back cleanly and leaves memory usable.
- Integrity check failures alert rather than silently repair.

## Related

[[Memory Fabric]] · [[Knowledge Graph]] · [[Episodic Log]] · [[Vector Store]] ·
[[Obsidian Vault Schema]] · [[Agent — Digest]]
