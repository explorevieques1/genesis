---
title: Research Canvas
tags: [ui, research, memory]
status: spec
implemented_by: []
---

# 🕸️ Research Canvas

## Purpose

A node canvas for research: documents, filings, charts, notes and the links
between them, laid out spatially — Obsidian's graph, for market work, **with
Genesis able to read and write it**.

**Not built.** `research.canvas` probes false; there is no `genesis.research`
module.

## Why it is not a front-end-only feature

A canvas could be built entirely in the browser with `localStorage` in an
afternoon. That is precisely why it has not been.

The requirement is *"Genesis has access to it"*. A canvas whose nodes exist only
in one viewer's browser is invisible to the agent that is supposed to use it:
it cannot cite a node, add one from a research pass, or notice that two threads
of enquiry converged. It would be a drawing tool that happens to sit inside a
trading platform.

So the canvas needs a **store the daemon can read and write**, and that store is
the actual feature. The rendering is the easy half.

## What it should be built on

Not a new graph store. [[Memory Fabric]] already specifies a Knowledge Graph
layer, and a research canvas is a *view* of that graph with positions attached —
not a parallel one. Two graphs of what Genesis knows is the same error as two
schedulers or two implementations of expectancy.

Concretely:
- Nodes reference existing entities — a `CompanyProfile`, a `MarkupSpec`, a
  journal `Lesson`, an episodic entry — rather than duplicating their content.
- Edges are typed and recorded, never inferred from embedding similarity. The
  journal graph already follows this rule and the reason transfers: a graph
  built from similarity looks identical to one built from provenance and means
  something entirely different.
- Layout (x, y, zoom) is presentation and may live per viewer.

## Rendering

React Flow is reserved by [[UI Stack]] §5 for [[Fleet View]]. This is a second
legitimate use of it — addressable nodes with React content, panned and zoomed —
and that reservation should be relaxed to name both, rather than the canvas
quietly adopting a third graph library.

The force-directed journal view is *not* this: it is a canvas-drawn d3-force
graph for a thousand undifferentiated dots, which is a different problem with a
different answer.

## Related

[[Memory Fabric]] · [[Recall Pathways]] · [[Company Data Model]] ·
[[UI Stack]] · [[Fleet View]] · [[Workspaces]]
