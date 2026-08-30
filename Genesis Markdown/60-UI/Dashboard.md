---
title: Dashboard
tags: [ui]
status: spec
implemented_by: []
---

# 🖥️ Dashboard

The visual surface. Voice is primary; the dashboard is where detail lives, where you
approve trades, and where you watch the fleet work.

Lineage: [[Repo — gensis-agents]] `orchestrator/` (agent grid, activity feed, process
control) and [[Repo — Gensis Terminal Official]] (widget grid, Electron shell).

## Panels

### Agent grid
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

## Design principles

- **Glanceable.** The three numbers that matter — portfolio heat, daily loss
  headroom, approval mode — are readable from across the room.
- **Live mode is unmistakable.** A different colour scheme, not a small badge.
- **Degraded data looks degraded.** A stale P&L is visually distinct from a fresh
  one, never presented as confident ([[Error Handling And Degradation]]).
- **Dark theme**, matching the [[Charting Engine]] renders.
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

[[Voice UX]] · [[Desktop Shell]] · [[Widget Catalog]] · [[Task Bus]] ·
[[Approval Modes]] · [[Kill Switch]] · [[Repo — gensis-agents]]
