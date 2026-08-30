---
title: Vector Store
tags: [memory]
status: spec
implemented_by: []
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

Local. `sqlite-vec` (keeps everything in the one SQLite file alongside the other
layers) or LanceDB (better at scale, separate store). Embedding model runs locally
([[LLM Model Tiers]] embedding tier).

For a personal trading system the corpus dominates the volume; memory itself stays
small for years. Don't over-engineer this layer.

## Acceptance criteria

- Retrieval p95 under 100 ms at expected volume.
- Namespace filtering applied pre-scoring, verified by test.
- Model version recorded per vector; a mismatch is detected and refused, not averaged.
- Re-embedding runs without downtime — old index serves until the new one validates.
- No secret or raw untrusted text is ever embedded, verified by a scanning test.

## Related

[[Memory Fabric]] · [[Recall Pathways]] · [[Knowledge Graph]] ·
[[Repo — Lithium Codebase]] · [[Trading Corpus Index]]
