---
title: How To Use This Vault
tags: [meta]
---

# How To Use This Vault

This vault is **the specification**, not the project. Code lives elsewhere
(see [[Build Order]] §0). Every note here is written so an agent — or you —
can read one file and know what to build.

## For Claude Code

When asked to build a piece of Genesis:

1. Read [[System Overview]] once for orientation.
2. Read **only** the specific note(s) for the component. Each agent note is
   self-contained: purpose, inputs, outputs, tools, cadence, prompt sketch,
   acceptance criteria.
3. Follow linked notes only when the note says to.
4. Obey [[Conventions]] for logging, spec files, and file layout.
5. Never load a whole third-party repo — see [[Trading Corpus Index]] for the
   token-discipline rule.

## Note types

| Tag | Meaning |
|---|---|
| `#moc` | Map of content — an index, not substance |
| `#architecture` | A system component |
| `#agent` | One agent's full specification |
| `#mcp` | A tool server |
| `#memory` | A memory layer or pathway |
| `#risk` | Safety-critical. Changes here need extra care. |
| `#schema` | A data contract — build to this exactly |
| `#ui` | A user surface |
| `#repo` | An existing codebase on this machine |
| `#meta` | About the vault itself |

## Reading an agent note

Every note in `20-Agents/` follows the same eight sections:

1. **Purpose** — one paragraph, what it is for
2. **Cadence** — when it runs (see [[Daemon And Cadence]])
3. **Inputs** — what it consumes
4. **Outputs** — what it produces, and where it writes
5. **Tools** — its MCP/tool allow-list (see [[MCP Gateway]])
6. **Memory namespace** — what it can read and write (see [[Memory Fabric]])
7. **System prompt sketch** — the shape of its instructions
8. **Acceptance criteria** — how you know it works

If you're adding an agent, copy that shape. See [[Agent Contract]].

## Graph view

Turn on the graph and colour by tag:
- `#agent` — the fleet
- `#risk` — should be a tight, heavily-linked cluster near [[Pre-Trade Risk Engine]]
- `#schema` — should be linked *from* many notes and link *to* few

If a `#risk` note is loosely connected, something bypasses the gate. That's a bug
in the design, not the graph.

## Canvas

`99-Canvas/Genesis System.canvas` renders the topology. Open it in Obsidian
(Canvas core plugin) for the visual map.

## Recommended plugins

Dataview (queries in [[Agent Index]] and [[Obsidian Vault Schema]]), Canvas (core),
Graph analysis. None are required — every note reads fine as plain markdown.
