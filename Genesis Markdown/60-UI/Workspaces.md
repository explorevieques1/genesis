---
title: Workspaces
tags: [ui, layout]
status: built
implemented_by:
  - ui/src/shell/pages.ts
  - ui/src/shell/TopBar.tsx
  - ui/src/shell/CommandBar.tsx
  - ui/src/workspace/modules.ts
  - ui/src/workspace/Workspace.tsx
  - ui/src/workspace/panels.tsx
  - ui/src/workspace/context.tsx
  - ui/src/workspace/dock.ts
  - ui/src/App.tsx
  - ui/src/workspace/panels/research.tsx
---

# 🪟 Workspaces

## Purpose

The surface is **an open canvas the trader commands**, with named starting
arrangements they can jump to. This note covers the shell: how pages are
declared, how workspaces are composed, and what the surface is still forbidden
from doing.

> [!important] The canvas opens empty — [[Operating Model]] §3
> The shell lands on a **blank workspace**: command line, safety floor, core
> sigil, nothing else. Not the Overview page, which reports what the system is,
> and not a dashboard of positions.
>
> That page is called **Home**. It was called "Canvas", which named the shape
> of the page rather than its job and collided with the research canvas — a
> real module you can spawn by code (`CA`). The principle keeps its name; the
> page does not.
>
> Both of those answer a question nobody asked, and the cost is identical: the
> first screen teaches the operator what the software is about, and a wall of
> unrequested telemetry teaches them that **things appear on their own** — which
> is exactly wrong for a system where a panel appearing means an agent decided
> something.
>
> The empty screen only works if the input is self-describing. Typing one
> character into the command line must reveal the surface — pages, panels,
> series, agents, every tool by name ([[Terminal]]). **Discoverability lives in
> the input, not in a pre-populated screen.**

It extends [[UI Stack]] §3, which specified Dockview and named the gap:
*"Fixed three-region layout with the same regions. No serialisable presets, so
Voice UX has nothing to target yet."* That gap is closed.

## A main category is a workspace

There are nine **main categories**, and each one *is* a workspace: a Dockview
dock with its own persisted arrangement, into which **any module can be
spawned**. Not a page with fixed contents, and not a bookmark into a shared
surface — nine independent spaces that happen to start out arranged for the
work their name describes.

`home` is the landing category: no dock, no panels, and a capability of `null`
because an empty page is meaningful in every state of the system.

Declared once in `ui/src/shell/pages.ts`. Nav, the command palette, the
`⌘1…⌘9` shortcuts and the seed layouts all read that list, so a category
cannot exist in one and be unreachable from another.

| Category | What it is for | Requires |
|---|---|---|
| **Home** *(default, built)* | Nothing. Where you start, and where you talk to Genesis. `⌘1` | — |
| Overview | What this system currently *is* — organs present, data held, work done | — |
| Charting | Price, the series held, and the charts Genesis has drawn | `marketdata.bars` |
| Research | Companies, filings, and the tool surface available to answer a question | — |
| Backtest | Run a strategy over stored bars and read the result | `backtest.engine` |
| Journal | Your notebook, the trades, and the graph between them | — |
| Automation | The cadences actually running; the workflow builder that is not built | `automation.workflows` |
| Fleet | The organism: body map, traces, memory, execution path | — |
| Settings | Microphone, data, agents, tools, approval mode | — |

**A page whose capability probes `built: false` is dimmed, not hidden.** Hiding
it would make the system look smaller than it is. Dimming says *"this exists as
a design and not as code"*, which is the true statement and the one that
matches the vault. The nav tooltip carries the probe's reason.

## Modules

A **module** is a panel with an identity: an id, a **two-or-three-letter short
code**, a title, and a `home` category (`workspace/modules.ts`).

Before this a panel had an id and nothing else. Its human title lived inside
whichever preset slot placed it, so `coverage` was "Coverage" on Charting and
"Data held" on Overview, and a panel no preset mentioned — `markup-specs`,
`trace`, `capability-map` — had no name at all: the palette de-hyphenated the id
and hoped. A thing you search for by code, group by category and spawn by name
needs a name of its own.

**`home` is a hint, not a cage.** It does exactly two jobs:

1. It seeds that category's first-run layout, so Charting opens with a chart in
   it and nothing has to be summoned before the software does anything.
2. It ranks the palette — in Settings, `AP` sorts above `CH`. `CH` still
   appears, and still opens there.

It forbids nothing. Confining a module to its home is what turned nine
categories into nine screens, and the whole reason this is a terminal rather
than a set of tabs is that a person mid-research can have the journal, a chart,
the graph and the statistics open in one space.

Charting seeds `LD` beside the chart, not `SR`: picking a symbol means
picking an IBKR contract, and the bar store as a whole is what a backtest reads,
so `SR` lives on Backtest.

One module is deliberately *not* in its category's seed: `TV` embeds
TradingView's own chart on a public tier-3 feed ([[Charting Engine]]), and a
panel showing data Genesis did not collect should be opened on purpose rather
than appear because you clicked Charting.

**A module may be open many times in one workspace.** Two charts side by side
is the ordinary case, not an edge one: NVDA against the index is two `CH`s, and
this run against last week's is two `EQ`s. So `openPanel` mints a fresh
instance id per open. The exception is a tool panel, which passes a stable
`tool:<id>` — typing a tool's name twice should return you to the form you
filled in, not hand you an empty one beside it.

Codes are unique, and *checked*: `modules.ts` throws at load if two modules
claim the same code or alias. A short code that opens the wrong panel is worse
than no short code.

| | | | | |
|---|---|---|---|---|
| `CH` Chart | `LD` Live data *(`live`)* | `IN` Instrument | `CV` Coverage *(`DH`)* | `MK` Markup |
| `TV` TradingView | | | | |
| `SG` Strategy | `EQ` Equity | `ST` Statistics | `TR` Trades | `HI` History *(`RR`)* |
| `SR` Series | | | | |
| `CA` Canvas | `RD` Research | `RN` Note | `CO` Company | `TS` Tools |
| `NOT` Notebook | `NOD` Nodes | `JG` Graph | `JE` Entries | `JP` Patterns |
| `CD` Cadences | `WB` Workflow builder | `FD` Feed *(`feed`, `findings`, `inbox`)* | | |
| `BM` Body map | `IS` Inspector | `EV` Events | `MM` Memory | `XP` Execution path |
| `TC` Trace | `CM` Capabilities | `VO` Voice | `AG` Agents | `DA` Data |
| `AP` Approval | `MT` Model tiers | `MAP` System map *(`system map`, `function map`)* | | |

## Seeds, and clear space

A **seed** is one arrangement per category, used once (`SEEDS` in
`modules.ts`). Out of the box a category opens with its own modules already
running. The moment anything is dragged, split, opened or closed, Dockview's
serialised layout is saved under that category's id in `localStorage` and the
seed is never consulted again — geometry authored by a person, recalled without
being asked for.

**Named layout presets are gone.** They were fourteen arrangements behind a
switcher, and they had the wrong shape for this: a preset is a menu of layouts
somebody else designed, where what a trading terminal wants is a space you fill
yourself. Their one real job was to give the voice path a target other than
pixel geometry —

> Presets live in config; the voice path selects among them and may create one,
> **never computes pixel geometry**. — [[UI Stack]] §3

— and that constraint survives intact. The target is now **a module code plus a
category**: `open CH in charting` is still classification, which a model is
good at, and still not arithmetic about pixels, which it is not.

**Clear space** is the broom, in the top bar. It closes every panel in the
current workspace and leaves it empty. Deliberately *not* "reset to default":
what a person wants after filling a category with fourteen panels is an empty
one, and the way back is to spawn what they want by code — which is cheaper
than remembering which preset was called what. The empty layout persists like
any other.

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

## Genesis is a participant in this workspace

The orchestrator opens panels and sets their subject through the **same**
`openPanel` the command line uses ([[Operating Model]] §5). It is a second
caller, not a second channel — which is what makes the parity rule checkable
rather than aspirational.

Two constraints on the model's side of it:

- **It opens and sets. It does not close.** A panel a person opened is theirs.
- **Every panel it opens says why** — the request and the trace that caused it.
  A panel that appeared unexplained is indistinguishable from a bug, and this
  surface is one where a bug that looks like an opinion is expensive.

Not built: the orchestrator has no efferent path to the UI yet.

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

[[Operating Model]] · [[UI Stack]] · [[Terminal]] · [[Dashboard]] · [[Fleet View]] · [[Genesis Core]] ·
[[Widget Catalog]] · [[Voice UX]] · [[Biological Design]] · [[Safety Invariants]]
