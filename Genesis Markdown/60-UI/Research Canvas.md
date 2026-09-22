---
title: Research Canvas
tags: [ui, research, memory]
status: built
implemented_by: [src/genesis/research/canvas.py, src/genesis/memory/graph.py, src/genesis/server/canvas_routes.py, ui/src/views/ResearchCanvas.tsx, ui/src/graph/nodes/EntityNode.tsx, tests/research/test_canvas.py]
---

# 🕸️ Research Canvas

## Purpose

A node canvas for research: documents, filings, charts, notes and the links
between them, laid out spatially — Obsidian's graph, for market work, **with
Genesis able to read and write it**.

**Built.** `src/genesis/research/canvas.py` over `src/genesis/memory/graph.py`,
`/v1/canvas/*`, and `ui/src/views/ResearchCanvas.tsx`. `genesis canvas` is the
parity path.

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

## What was built

### The store is the feature

`CanvasStore` holds **membership and position only** — a row is
`(canvas, entity, x, y, pinned, added_by)`. The nodes themselves are
[[Knowledge Graph]] entities, and those are references to records that already
exist. Three refusals follow:

- **It does not hold content.** To read a node you follow its entity's `ref` to
  the store that owns it. Copying a research note onto a canvas would make the
  canvas a second, staler copy of it.
- **It does not invent edges.** Lines are graph edges, recorded by whoever
  asserted them.
- **It refuses a node with nothing behind it.** An entity that is not in the
  graph cannot be placed, so an empty box is unreachable rather than merely
  unlikely.

### Drawing a line is asserting something

`assert_edge` writes a real [[Knowledge Graph]] edge under the `operator`
namespace, not a canvas-local decoration. Dragging a link between two nodes is a
claim about the world — *this idea derives from that filing* — and a claim
belongs where every agent can read it. A canvas-local line would be a claim only
one picture knows about, which is the browser-only failure again in miniature.

`retract_edge` is the mirror, and the asymmetry is the point: **you may only
undraw a line you drew.** An edge under an agent's namespace is provenance it
observed or a relationship it measured, and letting a mouse drag delete that
would make the graph's namespaces decorative. The refusal is stated, with the
namespace that owns the edge named in it — to stop seeing such a line you remove
one of its nodes, and the graph keeps what it learned. Same trade `delete` makes
for a whole canvas.

Unlike `supersede`, a retraction leaves no tombstone. An edge is an assertion,
and a retracted assertion that still renders is worse than one that is gone;
entities are what history is kept for.

The UI offers a deliberate subset of the edge vocabulary. `supersedes`,
`held`/`broke` and `correlates_with` are *measured* by agents from data;
offering them for hand-drawing would let a person assert by hand a fact whose
whole value is that it was computed.

### Genesis writes it too

`open_for(query)` is the method behind *"show me what you found"*: seeds from
the ids a research pass just wrote when the caller has them, otherwise from a
label search. An empty result still creates the canvas — *"nothing in the graph
matches this"* is a real answer, and returning nothing is indistinguishable from
a broken button.

## Deviation — layout is shared, not per viewer

This note permits layout to live per viewer. It does not.

Genesis arranges this canvas too: an agent that adds a node during an overnight
pass has to put it somewhere, and a position only one browser can see is a
position the agent cannot have chosen. One operator, one shared arrangement, and
it is a thing you and Genesis both edit — which is what makes it a second brain
rather than a drawing.

The cost is that an agent could undo your arrangement, so it cannot: a node a
person has moved is **pinned**, and `arrange()` never touches a pinned node.

## Deviation — the server does not force-lay-out

`arrange()` places unpinned nodes in concentric rings by entity type. Weak, and
honest: deterministic, stable across loads, and grouped by what things *are*. A
force simulation on the server would be a second layout engine competing with
the renderer's, and neither would win.

### The gestures, and what each one commits

React Flow supplies the manipulation; every gesture that changes something posts
it and re-renders from the reply. Nothing is optimistic, because a refusal has
to leave the picture showing what is actually recorded.

| Gesture | Commits |
|---|---|
| Drag a node (or a shift-boxed group) | `move` on release — one write per node, not per frame |
| Drag handle → handle | `link`, in the kind the toolbar has selected |
| Drag an edge end onto another node | `unlink` then `link` — a refused retraction leaves the old edge and invents no second one |
| Select an edge, Delete (or *unlink*) | `retract_edge` |
| Select nodes, Delete | `remove` — off the canvas, still in the graph |

Two refusals happen in the browser because they are not claims about the world
at all: a self-edge, and a duplicate of a line already drawn in the same kind —
which the graph would silently swallow, making the gesture look like it worked.
Everything else is the server's call.

Selection is React Flow's and is mirrored into this view's state rather than
owned by React Flow, because the node array is derived from server state on
every render: a `select` change that is not applied is a selection that vanishes
on the next reload.

The keystroke is never the only way. *unlink* is a button in the edge inspector
and `genesis canvas --link`/`--unlink SRC KIND DST` is the hand path, for the
same [[Operating Model]] parity reason the rest of the page has one — a
capability reachable only by knowing a keyboard shortcut is a capability half
the operators do not have.

## Not built

- **Charts as nodes.** The note's opening line includes them. A `MarkupSpec`
  entity type exists in the graph's vocabulary (`level`), but nothing projects
  markup specs into the graph yet — that is [[Agent — Chart Markup]]'s write,
  listed under [[Knowledge Graph]] §Writes and not yet made.
- **Canvas nodes for journal lessons and trades.** Same reason: the projection
  hook lives in [[Research Directory]], and the journal has its own store with
  its own graph view. One projection at a time.

## Related

[[Memory Fabric]] · [[Recall Pathways]] · [[Company Data Model]] ·
[[UI Stack]] · [[Fleet View]] · [[Workspaces]]
