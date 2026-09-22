---
title: Nodes
tags: [ui, module, memory]
status: built
implemented_by: [src/genesis/notebook/links.py, src/genesis/server/notebook_routes.py, ui/src/workspace/panels/nodes.tsx, src/genesis/notebook/__init__.py, tests/test_notebook.py]
---

# Nodes — `NOD`

Obsidian's graph view over the [[Notebook]] vault. Every note a dot, every
`[[link]]` a line, and the shape of what you have been thinking about visible
without reading any of it.

Home category: [[Workspaces|journal]].

## It is not the Research Canvas, and not the journal graph

Three graphs now exist and they are three different datasets. Getting this
wrong would produce a fourth store nobody asked for.

| Module | Nodes are | Edges are | Arranged by |
|---|---|---|---|
| [[Research Canvas]] `CA` | Knowledge Graph entities | asserted KG edges | a person and Genesis, saved |
| Journal graph `JG` | entries, lessons, symbols | recorded provenance | force layout, not saved |
| **Nodes `NOD`** | **files in a vault** | **wikilinks in their text** | **force layout, not saved** |

`CA` is a *place* — positions are stored, because Genesis puts things there
too. `NOD` is a *reading* of the vault: derived entirely from the files, saved
nowhere, correct the instant a file changes. Nothing is stored by this module.
There is no `nodes.db` and there must not be one.

**The link graph is not projected into the [[Knowledge Graph]].** It is already
in the files; a copy in the graph store would be a second truth that goes stale
the moment someone edits a note in Obsidian. If an agent later needs to cite a
notebook note *alongside* a research note, project references only — never the
links, which stay derived.

## The renderer already exists

`ui/src/components/graph/ForceGraph.tsx` — canvas, d3-force, subtractive
selection, simulation halts when alpha decays. It takes `{nodes, edges,
palette, selectedId, onSelect}` and the journal graph already feeds it. `NOD`
feeds it a different array. No second graph library, no React Flow (reserved
for [[Fleet View]]), no new canvas code.

## What is a node

Obsidian's filter set, minus what it would cost more than it is worth:

| Node kind | Shown | Toggle |
|---|---|---|
| note | always | — |
| unresolved link | a `[[target]]` that resolves to no file | on, default on |
| tag | a `#tag` in a note's body | on, default off |
| attachment | a non-markdown file linked by a note | on, default off |
| orphan | a note with no links either way | on, default on |

Node radius is degree — a note twenty things link to is bigger. Colour is by
kind, from family tokens, so a node here and a node in `JG` mean the same
thing visually.

**Not built:** groups (colour-by-search-query), the animate time-lapse, arrows,
and the four force sliders. Each is a preference panel over a picture that is
already readable. Add groups first if any of them is missed; the forces are
tuned in `ForceGraph` and one set of numbers that works beats four sliders that
have to be re-fiddled every session.

## Local graph

The half of Obsidian's graph that earns its place. Given a focus note and a
depth of 1–3, BFS over the link index and render only what is reachable —
incoming and outgoing, both, filterable to one. Clicking a node in `NOT` sets
the focus; clicking a node here opens it in `NOT`.

Depth is capped at 3. A depth slider that reaches "everything" is the global
graph with extra steps.

## Data

One route, `GET /v1/notebook/graph`, over the same link index [[Notebook]]
computes backlinks from — one parse of the vault, two consumers. Returns
`{available, nodes, edges}` in the standard envelope; an unopened or missing
vault is `available: false` with the path, not an empty graph, because a graph
with no dots and a vault that does not exist look identical and are not.

Search filtering happens server-side over the same index; the browser never
receives a vault it then filters down.

## Acceptance criteria

- Creating `[[Foo]]` in a note and reloading shows a dimmed unresolved node.
- Creating `Foo.md` turns that node solid without any other action.
- Deleting a note removes its node and its edges, with no orphaned edge.
- Clicking a node opens it in `NOT`; clicking a note in `NOT` focuses it here.
- A missing vault reports absent with its path, not an empty graph.
- The simulation stops when it settles — verified by an idle CPU reading.

## Related

[[Notebook]] · [[Research Canvas]] · [[Knowledge Graph]] · [[UI Stack]] ·
[[Workspaces]] · [[Obsidian Vault Schema]]
