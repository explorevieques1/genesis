---
title: Terminal
tags: [ui, tools]
status: building
implemented_by:
  - ui/src/workspace/dock.ts
  - tests/test_tool_routes.py
  - src/genesis/server/tool_routes.py
  - ui/src/shell/catalogue.ts
  - ui/src/workspace/modules.ts
  - ui/src/workspace/panels/tool.tsx
  - ui/src/workspace/panels/watchlist.tsx
  - src/genesis/mcp/build.py
  - ui/src/workspace/panels/ask.tsx
  - ui/src/workspace/panels/help.tsx
  - ui/src/shell/CommandBar.tsx
  - src/genesis/server/conversation_routes.py
---

# ⌨️ Terminal

## Purpose

**Anything Genesis can do, a person can do by hand — through the same door.**

This is the **parity rule**, stated system-wide in [[Operating Model]] §2. The
terminal is where it is enforced, and it is the *primary* input to Genesis, not
an alternative one: the trader commands the system, and voice is a peer that
reaches the same table.

[[Voice UX]] built the spoken path and [[Workspaces]] built the surface it acts
on. Between them was a gap nobody had named: the 131-tool catalogue in
`Settings → Tools` was a *printed menu*. It listed what existed and offered no
way to run any of it. The only route to a tool was to say something to Genesis
and hope the router chose it.

That is the wrong shape for two reasons, and only the second is about
convenience.

1. **Speed.** Asking a model to pick a tool costs a second and a token budget
   to do something a person already knows the name of. A trader who wants
   `get_company_facts` for AAPL should type five characters, not compose a
   sentence.
2. **Verification.** A terminal where the model can reach further than its
   operator is one where the operator cannot check the model's work. If Genesis
   says a filing shows something, the person must be able to open that filing
   themselves, from the same catalogue, and see the same bytes.

So the terminal is the **commander's input**, not a fallback for a broken
microphone. The command line is one way in, voice is another, and they reach the
same gateway and produce the same audit line.

**A capability behind voice only is a bug, not a phase.** If the only route to a
working tool is to say a sentence and hope the router picks it, that tool is not
shipped — which was the state of the 131-tool catalogue, and the reason the
system felt like three use cases wearing a terminal.

## The three surfaces

| Surface | Reaches | Model involved |
|---|---|---|
| Command line (`⌘K`) | categories, modules by short code, series, agents, every MCP tool by name, the command table, config (settings modules, model tiers, notebook vaults) — filterable by kind with clickable chips or `Tab`; under Modules, a second chip row files modules by section (their `home` page — defaulting to the page you are on, grouped under headers for All), cycled with `⌥←/⌥→` | none |
| Typed command (`↵` on no match, `⌘↵` always) | the deterministic command table, then the orchestrator | only past the table |
| Voice | the same command table, then the orchestrator | only past the table |

Typing a tool's name opens that tool. Typing a module's short code spawns that
module.

### The transient path and the kept one

`⌘K`, a typed command and voice all answer **once**, into the shell's reply
strip, and forget. [[Ask Genesis]] (`AI`) is the same `POST /v1/command` with a
`conversation` id attached: a module you can dock anywhere, whose transcript
the daemon saves ([[Conversation Store]]). It adds no capability — same
endpoint, same table-first dispatch — only a memory.

`HLP` is the map for all of this: every module code and every command the
deterministic table knows, read live from `MODULES` and `GET /v1/commands` so
it cannot drift from what actually works. [[System Map]] (`MAP`) draws the same catalogue as a graph — built by the
same `useCatalogue` hook the palette lists, so a node is a palette row you can click. Opening a module from Home — which
has no dock — navigates to a workspace first and `dock.ts` replays the open.

### A match is an open. A miss is a command.

The two paths need to be distinguishable without a mode switch, and this is the
rule that does it. `DH` lights up Coverage and `↵` spawns it in the workspace
you are standing in — deterministic, no model, no round trip. *"why is Nvidia
down today"* matches nothing, the field says so, and `↵` sends it to
`POST /v1/command`, the same endpoint voice posts a transcript to.

The operator experiences this as *"did the list light up"*, which needs no
explaining. `⌘↵` still forces the command path when a query happens to collide
with a module name.

Search is ordinal: an exact short code first, then a prefix match on a module
belonging to the current category, then any prefix, then a substring, then the
description. Crude, and right often enough that a fuzzy matcher would be a
dependency buying very little.

## One panel, every tool

`ui/src/workspace/panels/tool.tsx` is a single component that renders **any**
tool's form from that tool's own JSON Schema.

This is the load-bearing decision. 131 hand-written panels would be 131 files
that rot the moment a server renames an argument — and the catalogue grows.
Instead the panel asks the daemon what the tool wants and builds the form from
the answer, so **a new MCP server becomes usable with no UI change at all**.

Argument shapes come from the live handshake, never from config. [[MCP
Gateway]]'s rule, restated in `mcp/discovery.py`: *a server is authoritative
about the shape of its arguments and nothing else.* Config knows a tool is
called `get_company_facts`; only the server knows whether it wants a CIK or a
ticker.

The form renders four kinds of control — enum, boolean, number, text — and
falls back to a JSON textarea for anything else. Deliberately not a
schema-form library: that is a dependency for a handful of tools that take a
ticker and a date.

## The gateway is built on first use

`GET /v1/mcp/tools` still reports the *declared* catalogue from config and
still opens no sessions. It must stay cheap, because a page load reads it.

`GET /v1/mcp/tool/{id}` needs a connected gateway, and building one spawns a
subprocess per server. Paying that at daemon start-up makes `genesis serve`
look broken; paying it on a page load makes a read the most expensive thing in
the system. **Opening a tool panel is the honest moment to pay it** — a person
asked for one specific tool, and waiting is what they expect. Built once,
behind a lock, then instant.

## The operator is an agent

Hand-driven calls are attributed to `operator`, which has its own entry in
`ALLOW_LISTS` (`mcp/build.py`).

Not `orchestrator`. The grants are deliberately the same *shape* — that
symmetry is the whole design — but the caller is not the same, and a log that
cannot tell a person from a model cannot answer *"who did this?"* on the one
day it matters.

The operator's grant is the orchestrator's **reading** surface. Not copied
across: `vault.*` writes, `chart.*` (it drives the desktop chart), and
`research.*` (minutes per call, and it costs credits — a spend that belongs on
a lane, not behind Enter).

## What a hand-driven call may not do

**No mutating tool runs from the command line.** Not yet, and not without the
approval gate.

A surface whose muscle memory is *type, Enter* is precisely where an accidental
write happens. [[Biological Design]] §afferent ≠ efferent is the reason this is
structural rather than a matter of care: writes need idempotency keys,
authorisation, ordering and complete audit, and a search bar has none of them.

The refusal exists **twice, independently**:

1. `tool_routes.py` rejects any spec the catalogue marks `mutating`.
2. The `operator` allow-list contains no write pattern, so `Gateway.call`
   would reject it anyway.

Deleting either one does not open the path. That is the property a safety rule
should have, and it is the same reasoning [[Safety Invariants]] #1 uses for the
order path — which this route also cannot reach, for a third reason: no
execution capability is in the catalogue at all.

## Modules are not owned by categories

[[Workspaces]] made a preset the *default* arrangement for a page. It was still
the *only* arrangement available to it: a panel was reachable only from the
page whose preset named it, which made eight pages into eight cages — the
journal graph could not sit beside a chart no matter how much you wanted it to.

Every main category is now a workspace, and the command line spawns any module
into whichever one you are standing in, by short code, as many times as you
want. A module's `home` category ranks it in the palette and seeds that
category's first run; it confines nothing.

`dock.ts` holds the live `DockviewApi` so the shell can open into a dock it is
not a child of — wiring, never state; the layout itself is still Dockview's,
serialised per category.

## Still to build

These are not nice-to-haves. Each one is a rule in [[Operating Model]] that the
code does not yet satisfy, so each is a defect with a spec behind it.

- **Name resolution.** *"Nvidia"* must reach `NVDA` — deterministic lookup,
  ambiguity surfaced, resolution shown ([[Operating Model]] §7). Traders do not
  speak in tickers and must never be made to.
- **Symbol linking — named groups.** Panels joining a named link group, so
  setting a ticker in one sets it in all of them — the `🔗 GOOG US` chip.
  Genesis joins those groups as a participant, not an owner. *Built so far:*
  one unnamed app-wide group, `symbolLink()` in `ui/src/workspace/context.tsx`.
  `SCR`, `WL`, `HM`, `CO` and `TV` all publish to it and follow it — a pick or
  a typed symbol in any one moves the rest; `CO` looks up a ticker the store
  lacks through `X profile`. `CH` is outside it (holds no bars for most names).
  Still missing: names, the chip, and panels opting out.
- **Terminal context for the model.** Panels publishing what they are showing,
  so *"why is MSFT down today"* can read the news panel already open. This is
  the thing existing terminals cannot do, and it is not a model problem — their
  panels simply do not publish.
- **Natural language falling through to the orchestrator.** `POST /v1/command`
  matches the deterministic table and stops. An unmatched sentence should reach
  the orchestrator rather than returning *"I didn't catch a command in that"*.
- **Writes, behind the approval gate** — from the command line. Order writes now
  exist, in the `TRD` panel and `/v1/exec/*` only, every one spending a
  [[Pre-Trade Risk Engine]] approval ([[Execution Family]] build state).

## Related

[[Operating Model]] · [[Workspaces]] · [[UI Stack]] · [[Voice UX]] · [[MCP Gateway]] ·
[[MCP Server Catalog]] · [[Widget Catalog]] · [[Biological Design]] ·
[[Safety Invariants]]
