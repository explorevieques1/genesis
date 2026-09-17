---
title: Vector Store
tags: [memory]
status: building
implemented_by: [src/genesis/memory/vectors.py, tests/memory/test_vectors.py]
---

# Vector Store

Semantic similarity over everything the system has written or read. The "what else is
like this?" layer.

## What gets embedded

| Content | Chunking |
|---|---|
| Ideas — thesis and reasoning | one chunk per idea |
| Journal notes — including your reflections | note-level + section-level |
| Research notes and daily briefs | section-level |
| Catalyst summaries | one per catalyst |
| Chart descriptions from [[Markup Spec]] `why` fields | one per spec |
| Lessons | one per lesson |
| Strategy descriptions and backtest commentary | one per strategy version |
| **Corpus chunks** — the trading reference library | see below |

## The corpus half

The [[Trading Corpus Index]] is a large read-only library of cloned repositories.
Embedding it makes "how does freqtrade handle drawdown protection?" answerable
semantically rather than by grep.

**Strong recommendation:** use [[Repo — Lithium Codebase]] for this rather than
building it. It already does discovery → clone → analyse → chunk → embed → index →
hybrid search → MCP, in Rust, locally, with a working desktop UI. That is exactly
this job, already built. See [[Open Questions]] §9.

Split the responsibilities:
- **Lithium** — corpus and code retrieval (large, static, re-indexed weekly)
- **Genesis vector store** — memory recall (small, hot, written continuously)

Different access patterns; one store optimized for both would be bad at both.

## Retrieval

Vector search alone is a poor default for this system. It is one input to hybrid
retrieval ([[Recall Pathways]]):

```
score = w1·vector_similarity
      + w2·graph_proximity        ← [[Knowledge Graph]]
      + w3·recency
      + w4·priority               ← lessons and active invalidations always surface
```

Pure semantic similarity retrieves the *most similar* memory, which is frequently
not the *most relevant* one. A trade from eight months ago that reads similarly is
less useful than yesterday's lesson about the same setup.

## Practical rules

- **Store the source, not just the embedding.** Re-embedding on a model change must
  not require re-deriving the text.
- **Version the embedding model.** Mixed-model vectors in one index produce silently
  wrong results — the worst kind.
- **Re-embed on model change**, as a scheduled job, with the old index kept until the
  new one is verified.
- **Never embed secrets or raw untrusted content.** Fenced news text is summarised
  before embedding, never embedded verbatim ([[MCP Gateway]]).
- **Deduplicate.** The same daily brief phrasing appearing 200 times pollutes
  retrieval; near-duplicate detection at write time.
- **Namespace filtering happens before scoring**, not after — an agent must not even
  see results outside its declared namespaces ([[Agent Contract]]).

## Implementation

**Built 2026-09-17** — `src/genesis/memory/vectors.py`, `~/.genesis/vectors.db`.

Plain SQLite with `float32` blobs and cosine in numpy, not `sqlite-vec` and not
LanceDB. The note's own last line is the reason: memory stays small for years,
an exhaustive scan of a few thousand unit vectors is sub-millisecond, and an
extension or a second store buys index structure this layer will not need for a
long time. The corpus half stays [[Repo — Lithium Codebase]]'s job, which is
where the volume actually is.

`ponytail:` the scan is O(n) per search. At six figures of chunks, add
`sqlite-vec` behind the same `VectorStore.search` signature.

The embedder is `bge-small-en-v1.5` ONNX on CPU, one thread, CLS-pooled and
unit-normalised, loaded on first use rather than at construction. Install it
once with `genesis memory install-embedder`; the files live in
`~/.genesis/models/<model>/` beside the databases.

**There is no fallback embedder, deliberately.** A hash or random "embedding"
would make every acceptance criterion here pass while returning nonsense, and
nonsense that scores 0.83 is worse than an empty result. With no model
installed the store raises `degraded` and names the missing file, and
`genesis memory search` distinguishes *"nothing is similar"* from *"nothing is
embedded"* from *"there is no model"* -- three different answers that all look
like "no results".

### What the store enforces

| Rule | How |
|---|---|
| Namespace filtering before scoring | a `WHERE namespace IN (...)` clause; `search` has **no default namespace**, so it cannot accidentally search everything |
| Model versioned per row | `model` column; `search` filters to the current model, `stale()` counts the rest, `reembed()` moves them |
| Mixed models never averaged | a vector from another model is invisible to search rather than scored against |
| Store the source | the chunk text is a column; re-embedding never re-derives it |
| Deduplicate | content hash, plus cosine ≥ 0.98 within the same namespace and kind |
| Nothing untrusted verbatim | a `Fenced` object handed to `write` raises; `embeddable` is `False` by construction |
| No secrets | the log's own `redactor` scrubs on the way in, never after |

### Not built

- **Hybrid scoring.** `score = w1·vector + w2·graph + w3·recency + w4·priority`
  is [[Recall Pathways]]', and this layer is the first of its four inputs to
  exist. Vector-only recall is available now and is *not* the default retrieval
  path for exactly the reason this note gives.
- **The corpus half.** See [[Repo — Lithium Codebase]] and [[Open Questions]] §9.
- **Re-embedding without downtime.** `reembed()` moves rows in batches and both
  halves stay searchable by their own model, which is the no-hole version of
  that requirement rather than the no-downtime one.

## Acceptance criteria

- Retrieval p95 under 100 ms at expected volume.
- Namespace filtering applied pre-scoring, verified by test.
- Model version recorded per vector; a mismatch is detected and refused, not averaged.
- Re-embedding runs without downtime — old index serves until the new one validates.
- No secret or raw untrusted text is ever embedded, verified by a scanning test.

## Related

[[Memory Fabric]] · [[Recall Pathways]] · [[Knowledge Graph]] ·
[[Repo — Lithium Codebase]] · [[Trading Corpus Index]]
