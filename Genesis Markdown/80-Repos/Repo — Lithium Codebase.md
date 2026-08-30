---
title: Repo — Lithium Codebase
tags: [repo]
---

# Repo — Lithium Codebase

`/home/gzacc2002/Projects/Lithium Codebase/`

**A local-first engineering knowledge base, already built.** Rust, ten crates, 109
tests, builds clean. Collects open-source repositories onto your own hardware,
extracts their structure, and serves them to a coding agent as searchable reference.

Its own README: *"architecture, patterns and idioms to learn from, not code to
paste."* That is precisely the relationship Genesis has with
[[Trading Corpus Index|the corpus]].

## The pipeline

```
discovery → clone → analyse → chunk → embed → index → hybrid search → MCP
```

Runs end to end, driven from the CLI or a desktop dashboard. Everything on one
machine — no cloud services, no API keys beyond a GitHub token for discovery.

Desktop app: five screens (Dashboard, Repositories, Add, Search, Settings) with a
fixed-rate coalescing progress ticker — UI cost is a function of wall-clock time,
never engine throughput. That's a good pattern for [[Dashboard]] progress reporting
during long [[Agent — Optimizer]] runs.

## Why Genesis should use it

The [[Vector Store]] note flags this as a decision ([[Open Questions]] §9), and the
recommendation is clear: **use Lithium for corpus retrieval rather than rebuilding it.**

- It already does chunking, embedding, indexing, and hybrid search over cloned repos
- It already exposes an **MCP server** — so it plugs into [[MCP Gateway]] directly
- It's local, Rust, and fast
- It's tested and building clean

Split the responsibility:

| Store | Purpose | Characteristics |
|---|---|---|
| **Lithium** | Corpus and code retrieval | Large, static, re-indexed weekly |
| **Genesis [[Vector Store]]** | Memory recall | Small, hot, written continuously |

Different access patterns. One store optimized for both would be mediocre at both.

## The known gap

From its README: the in-process ONNX embedding backend is **not wired up**
(`lithium-embed/src/onnx.rs` documents how to enable it). Use `backend = "ollama"`,
which works today, or `"null"` for a model-free smoke test.

For Genesis this is fine — the Ollama backend matches [[LLM Model Tiers]]'s local
embedding tier anyway.

Also noted: the GUI currently links the pipeline in-process rather than talking to a
daemon; the daemon split is specified but only partly implemented. Irrelevant if
Genesis consumes it through the MCP server.

## Integration

1. Point Lithium at `/home/gzacc2002/Projects/` — the corpus is already cloned there
2. Index with the Ollama embedding backend
3. Register its MCP server in [[MCP Gateway]]
4. Allow-list it to the [[Strategy Family]] and to Claude Code

Then "how does freqtrade handle drawdown protection?" is a semantic search rather
than a grep, and the [[Trading Corpus Index]] token-discipline rule gets much easier
to follow — you retrieve the right chunk instead of opening the wrong file.

## Also read

`docs/ARCHITECTURE.md` — the engine design. Worth reading for the pipeline structure
even if you don't adopt the code.

## Related

[[Vector Store]] · [[Trading Corpus Index]] · [[MCP Gateway]] ·
[[MCP Server Catalog]] · [[Open Questions]] · [[Repo Map]]
