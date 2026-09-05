---
title: Workspaces
tags: [ui, layout]
status: built
implemented_by:
  - ui/src/shell/pages.ts
  - ui/src/shell/TopBar.tsx
  - ui/src/shell/CommandBar.tsx
  - ui/src/workspace/presets.ts
  - ui/src/workspace/Workspace.tsx
  - ui/src/workspace/panels.tsx
  - ui/src/workspace/context.tsx
  - ui/src/App.tsx
---

# 🪟 Workspaces

## Purpose

The surface is **eight pages, each with named panel layouts a person can
rearrange**. This note covers the shell: how pages are declared, how workspaces
are composed, and what the surface is still forbidden from doing.

It extends [[UI Stack]] §3, which specified Dockview and named the gap:
*"Fixed three-region layout with the same regions. No serialisable presets, so
Voice UX has nothing to target yet."* That gap is closed.

## Pages

Declared once in `ui/src/shell/pages.ts`. Nav, the command palette, the
`⌘1…⌘8` shortcuts and the workspace switcher all read that list, so a page
cannot exist in one and be unreachable from another.

| Page | What it is for | Requires |
|---|---|---|
| Overview | What this system currently *is* — organs present, data held, work done | — |
| Charting | Price, the series held, and the charts Genesis has drawn | `marketdata.bars` |
| Research | Companies, filings, and the tool surface available to answer a question | — |
| Backtest | Run a strategy over stored bars and read the result | `backtest.engine` |
| Journal | Trades, lessons, and the graph between them | `journal.store` |
| Automation | The cadences actually running; the workflow builder that is not built | `automation.workflows` |
| Fleet | The organism: body map, traces, memory, execution path | — |
| Settings | Microphone, data, agents, tools, approval mode | — |

**A page whose capability probes `built: false` is dimmed, not hidden.** Hiding
it would make the system look smaller than it is. Dimming says *"this exists as
a design and not as code"*, which is the true statement and the one that
matches the vault. The nav tooltip carries the probe's reason.

## Workspaces

A **preset** is a name plus a list of panels (`workspace/presets.ts`). The
*arrangement* is Dockview's serialised state, saved per preset id in
`localStorage` the moment a person drags anything. So a preset is a starting
point, not a cage: "Analysis" means *your* analysis layout after the first time
you adjust it, and `reset` is a real, discoverable action.

This is the shape [[UI Stack]] §3 asked for, and the reason for it:

> Presets live in config; the voice path selects among them and may create one,
> **never computes pixel geometry**.

A voice path that computed geometry would be a language model doing arithmetic
about pixels — plausibly wrong, and unusable when wrong. Selecting from a named
set is classification, which is what it is good at.

Presets today: Charting (Focus, Analysis) · Backtest (Report, Compare) ·
Research (Company, Canvas) · Journal (Graph, Ledger) · Fleet (Organism,
Forensics) · Settings (System, Data) · Automation (Schedule) · Overview
(System).

## Failure isolation

Paint order is [[UI Stack]] §6's order, and the independence is structural
rather than promised:

1. The safety strip and kill switch — plain DOM, siblings of the workspace in
   the tree, importing nothing from it.
2. The banner and navigation.
3. The dock, in which **every panel is wrapped in its own error boundary**.

So a charting library that throws on a malformed series shows one failed
rectangle. It cannot blank the workspace, and it cannot reach the risk numbers.

> This was found the hard way. A snapshot field the server did not send reached
> `money()`, threw, and React unmounted the whole tree — heat, headroom,
> approval mode and the kill switch, all gone, because one string was
> `undefined`. The formatters are now total, the floor has its own boundary, and
> the snapshot's shape is pinned by a test.

## What the surface still never does

Unchanged from [[UI Stack]] §9 and [[Safety Invariants]], and worth restating
because eight pages is more surface to get this wrong on:

- No order path. There is no ticket, no broker route, and a test asserts no
  POST route's path even *looks* like one.
- No UI-side risk logic. A verdict comes from the Pre-Trade Risk Engine or it is
  not shown.
- No approval-mode control. Settings displays the mode and says where it is
  changed — [[Safety Invariants]] #9 requires an explicit, logged action, and a
  dropdown in a settings panel is the frictionless version of the thing that
  rule exists to prevent.
- No polling. Reads happen on mount; movement arrives on the event socket.
- No store of record. A refresh loses nothing because there is nothing to lose.

## Related

[[UI Stack]] · [[Dashboard]] · [[Fleet View]] · [[Genesis Core]] ·
[[Widget Catalog]] · [[Voice UX]] · [[Biological Design]] · [[Safety Invariants]]
