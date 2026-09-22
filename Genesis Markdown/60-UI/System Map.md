---
title: System Map
tags: [ui, graph]
status: built
implemented_by:
  - ui/src/views/SystemMap.tsx
  - ui/src/shell/catalogue.ts
---

# 🗺️ System Map

## Purpose

`MAP` draws everything the command line can reach: pages, modules, commands,
config, series, agents and tools. It shows how they connect, and **every node
is a link**. Clicking a node does exactly what choosing that row in ⌘K does.

It shows structure and acts only as a palette would. It adds no capability of its own. Like
[[Fleet View]], it is inspection plus the ordinary doors. There is no start,
stop or edit here.

## One catalogue, two surfaces

The nodes come from `useCatalogue` (`ui/src/shell/catalogue.ts`), which is the
same hook [[Terminal]]'s palette lists. Each item carries its palette `run`,
so the map cannot show a thing the palette cannot open. Settings modules
appear once on the map, although the palette lists them under both Modules and
Config.

A command's help line is an example, not a literal. Clicking one opens ⌘K with
the line typed and the Commands filter on, and nothing fires until the operator
presses ↵. The map hands the line over through a `genesis:palette` window
event that the shell listens for.

## Links, and where each is read from

| Link | From → to | Source |
|---|---|---|
| home | page → module | `MODULES[].home` |
| seeded | page → module seeded there from another home | `SEEDS` |
| opens | series → `CH`, tier → `MT`, vault → `NOT`, workflow agent → `WB` | the item itself |
| about | command → module it answers into | `COMMAND_ABOUT` (hand-kept) |
| shows | module → agent whose work it shows | `MODULE_AGENTS` (hand-kept; mirrors `MODULE_LINKS` in `scripts/build_connection_graph.py`) |
| uses | agent → tool | the agent's declared `tools`, matched on tool id or capability |
| reads | agent → agent | the agent's `memory.read` |

A link whose far end did not load, such as an agent not in the running fleet,
is dropped rather than drawn to nothing. If a read fails, the legend names it.

## Layout

The map has five blocks, left to right: **Doors** (pages, commands, config),
**Series**, **Modules** (grouped by home page, in nav order), **Agents**
(grouped by family) and **Tools** (grouped by MCP server). A block wraps into
another column after 34 rows, and a group never leaves its title at the foot
of a column. Agent families and tool servers are ordered by the mean row of
whatever links to them, so a server sits across from the agents that call it.

elkjs layered was tried and rejected. At 264 nodes it produces four columns
about 5,000 px tall, and the map is unreadable at any zoom that fits it.

Positions are computed once per topology. Hovering highlights a node, its
neighbours and their links, and dims everything else. Search dims whatever does
not match. Neither moves a node.

## Related

[[Terminal]] · [[Workspaces]] · [[Fleet View]] · [[Operating Model]] · [[Agent Index]]
