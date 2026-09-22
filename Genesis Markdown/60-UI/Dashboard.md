---
title: Dashboard
tags: [ui]
status: building
implemented_by: [ui/src/App.tsx, ui/src/components/SafetyFloor.tsx, ui/src/components/KillSwitch.tsx, ui/src/components/EventStream.tsx, ui/src/components/SystemHealth.tsx, ui/src/shell/CommandBar.tsx, ui/src/shell/TopBar.tsx, ui/src/shell/pages.ts, ui/src/store/useGenesis.ts]
---

# 🖥️ Dashboard

The visual surface: where detail lives, where you approve trades, and where you
watch the fleet work.

> [!important] The dashboard is a *destination*, not the landing screen
> [[Operating Model]] §3 — **the canvas opens empty.** Nothing below appears on
> launch. Every panel here is something the trader asked for, by typing or by
> speaking, or something Genesis opened while answering a request — and in the
> second case the panel says which request opened it.
>
> This note used to open *"voice is primary; the dashboard is where detail
> lives"*. Voice is a **peer input**, not the door ([[Terminal]]): the typed
> sentence and the spoken one reach the same command table and the same
> orchestrator behind it. Unplugging the microphone removes no capability.

Lineage: [[Repo — gensis-agents]] `orchestrator/` (agent grid, activity feed, process
control) and [[Repo — Gensis Terminal Official]] (widget grid, Electron shell).

## Panels

### Agent grid
The static roster — *is everything healthy?* — readable in one glance. [[Fleet View]]
answers the other question, *what is happening and because of what?*, as a live
graph. Both exist; they share one state vocabulary.

Live status card per agent: `idle` / `working` / `blocked` / `degraded` / `down`,
last action in plain English, next scheduled run, today's cost. Start / stop /
restart per agent.

Colour by family so the [[Execution Family]] is visually distinct — you should be
able to tell at a glance whether anything touching money is unhealthy.

### Activity feed
Streaming, plain-English log of what every agent is doing. Not raw logs — the
`spoken_summary` field from each agent result ([[Agent Contract]]). Filterable by
agent, family, and severity.

This is the panel that makes the system feel alive rather than opaque.

### Idea board
The centrepiece. Ranked live ideas as cards:

- Symbol, direction, confidence, age, status
- Chart thumbnail from [[Agent — Chart Markup]]
- Thesis, one line; expandable to full evidence chain
- Entry zone, invalidation, R:R
- Conflicts, shown — not hidden behind a click
- Actions: **chart it** · **backtest it** · **draft order** · dismiss (with a reason
  that feeds [[Agent — Insight Miner]])

Dismissing with a reason is what lets the system learn which ideas you skip and
whether you were right to.

### Positions and risk
- Live P&L, per position and total — greyed and labelled when the quote is stale
- **Portfolio heat gauge** — the most important number on the screen
- Daily loss gauge with headroom
- Exposure by sector and correlation cluster
- Prop-firm rule bars when applicable ([[Prop Firm Rules]])
- **Approval mode, always visible** — and `live` mode in a colour you cannot miss

### Approval queue
Pending order proposals in [[Approval Modes|`confirm`]] mode. Each shows the full
risk check output, the countdown to expiry, and approve/reject buttons. Approving
here is equivalent to a spoken confirmation.

### Order ticket
The **only** place a human places a manual order — and it goes through
[[Pre-Trade Risk Engine]] exactly like an agent proposal ([[Safety Invariants]] #1).
No fast path exists.

### Chart pane
Interactive chart with the latest [[Markup Spec]] overlaid. Same spec the vault and
the vision model see ([[Charting Engine]]). You can hand-edit annotations; edits
create a child spec, they never mutate the original.

### Transcript
Full conversation history, searchable, with `trace_id` links into the
[[Episodic Log]] — click any exchange to see everything it caused.

### Memory viewer
Browse the [[Knowledge Graph]], journal, lessons, and beliefs. Pattern:
[[Repo — jarvis]] `desktop_app/memory_viewer.py`.

### Kill switch
Persistent, always visible, never behind a menu. Direct HTTP to the kill-switch
process — not through the task bus ([[Kill Switch]]).

## Every panel names its work

The differentiator against a terminal that merely *presents* data
([[Operating Model]] §1). Each panel carries, in its own chrome:

- **What produced it** — the agent or tool, by name, linked to its trace
- **As of when**, and whether that is live or stale
- **Why it is open** — the request that caused it, when Genesis opened it
- **Pin / dismiss.** Pinned panels survive the next question; unpinned ones are
  the working set for the question being asked

A panel that cannot answer *"who computed this and from what?"* is a Bloomberg
panel with a Genesis border on it.

Panels also **publish what they are showing** so the orchestrator can read the
open workspace instead of re-fetching the world ([[Operating Model]] §5). That
is the capability existing terminals do not have, and it is not a model problem
— their panels simply do not publish.

## Design principles

- **Glanceable.** The three numbers that matter — portfolio heat, daily loss
  headroom, approval mode — are readable from across the room.
- **Live mode is unmistakable.** A different colour scheme, not a small badge.
- **Degraded data looks degraded.** A stale P&L is visually distinct from a fresh
  one, never presented as confident ([[Error Handling And Degradation]]).
- **Dark theme**, matching the [[Charting Engine]] renders.
- **The safety floor is plain DOM.** Heat, daily-loss headroom, approval mode and the
  [[Kill Switch]] never depend on WebGL, canvas, or a live socket ([[UI Stack]] §6).
  Collapsed to one line while those numbers are em dashes; full readout in
  `Settings → Approval`, and it returns to the chrome in Phase 7.
- **No modal blocking.** The market doesn't wait for a dialog.
- **Everything links back.** Every number traces to the log entry that produced it.

## Transport

WebSocket stream off the [[Task Bus]] and [[Event Schema]]. The dashboard is a
**view**, never an authority — it holds no state that isn't in [[Memory Fabric]], so
a browser refresh loses nothing.

## Acceptance criteria

- Full fleet state visible without scrolling on a 1080p display.
- Agent status updates within 1 s of a change.
- Approving in the queue is functionally identical to a spoken confirmation.
- A manual order goes through the same risk path as an agent order, tested.
- Live mode is visually unmistakable from paper.
- Stale data is visually distinct.
- Refresh loses no state.

## Related

[[UI Stack]] · [[Fleet View]] · [[Genesis Core]] · [[Voice UX]] · [[Desktop Shell]] ·
[[Widget Catalog]] · [[Task Bus]] · [[Approval Modes]] · [[Kill Switch]] ·
[[Repo — gensis-agents]]
