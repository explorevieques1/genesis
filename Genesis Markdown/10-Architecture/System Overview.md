---
title: System Overview
tags: [architecture, moc]
status: spec
implemented_by: []
---

# System Overview

The whole picture in one note. Everything else is a zoom-in.

> [!important] Read [[Biological Design]] first
> Genesis is built as an **organism**, not as a chatbot with tools attached. The
> LLM is one organ; the agent is the whole loop — perception, memory, rhythm,
> reflex, action and homeostasis together.
>
> That note holds the biology → architecture map and the three principles the
> topology below is shaped by: the **reflex arc** (safety checks are spinal, not
> prompted), the **afferent/efferent split** (read and write paths are
> structurally different), and **proprioception before ambition** (never build an
> actuator before the sense that verifies it acted).

## Topology

```
                        ┌───────────────────────────────┐
              voice in  │        ORCHESTRATOR           │  voice out
        ┌───────────────►   (the main input)            ├───────────────┐
        │               │  • ElevenLabs STT / TTS       │               │
        │               │  • intent + task planner      │               ▼
   ┌────┴─────┐         │  • agent router / scheduler   │        ┌────────────┐
   │  User    │         │  • approval gate              │        │  Speakers  │
   │  (mic)   │         │  • conversation memory        │        └────────────┘
   └──────────┘         └───────────────┬───────────────┘
                                        │  TASK BUS (priority queue + events)
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼               ▼               ▼               ▼                ▼
 ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
 │ Research   │  │ Charting   │  │ Strategy   │  │ Execution  │  │ Journal    │
 │ family     │  │ family     │  │ family     │  │ + Risk     │  │ family     │
 │ (7 agents) │  │ (4 agents) │  │ (7 agents) │  │ (6 agents) │  │ (6 agents) │
 └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
       └───────────────┴───────┬───────┴───────────────┴───────────────┘
                               ▼
                  ┌─────────────────────────┐      ┌──────────────────────┐
                  │     MCP GATEWAY         │◄────►│  MCP servers          │
                  │  registry · selection · │      │  market data · broker │
                  │  runtime · fencing      │      │  TradingView · news · │
                  └───────────┬─────────────┘      │  Obsidian · Lithium   │
                              ▼                    └──────────────────────┘
       ┌───────────────────────────────────────────────────────────┐
       │                   MEMORY FABRIC                            │
       │  working · episodic · knowledge graph · vector · ledger    │
       │                    ↕ mirrors ↕                             │
       │                 OBSIDIAN VAULT                             │
       └───────────────────────────────────────────────────────────┘
                              ▲
       ┌──────────────────────┴────────────────────────┐
       │  TRADING CORPUS (read-only reference library)  │
       │  vectorbt · freqtrade · nautilus · qlib ·      │
       │  TradingAgents · FinRL · empyrical · …         │
       └───────────────────────────────────────────────┘
```

## The layers

| Layer | Note | Responsibility |
|---|---|---|
| *Framing* | [[Biological Design]] | Which organ is this, and is it reflex or judgement? |
| Voice | [[Voice Stack]] | Capture, wake, STT, TTS, barge-in, earcons |
| Coordination | [[Orchestrator]] | Intent → plan → route → gate → speak |
| Transport | [[Task Bus]] | Priority lanes, persistence, backpressure, events |
| Scheduling | [[Daemon And Cadence]] | The forever loop; open vs. closed behaviour; cron |
| Work | [[Agent Index]] | ~30 specialists |
| Tools | [[MCP Gateway]] | One registry, smart selection, fencing, allow-lists |
| Knowledge | [[Memory Fabric]] | Five layers + Obsidian mirror |
| Safety | [[Pre-Trade Risk Engine]] | One gate, no bypass |
| Surfaces | [[Dashboard]] · [[Voice UX]] · [[Desktop Shell]] | How you see and steer it |

## The two loops

Genesis is not "on during the day, off at night" — it has **two different jobs**.

### Market open
Reactive and fast. Watch levels, scan for setups, digest catalysts, track P&L,
propose and manage orders. Latency matters; depth does not.

→ [[Agent — News And Catalyst]], [[Agent — Screener]], [[Agent — Level Watcher]],
[[Agent — Sentiment]], [[Agent — Idea Synthesizer]], [[Agent — Position And PnL Accountant]],
[[Agent — Execution Quality]], [[Agent — Watchdog]]

### Market closed
Reflective and deep. Backtest, optimize, mine the journal, re-rank the universe on
fundamentals, detect regime shifts, prepare tomorrow. Depth matters; latency does not.

→ [[Agent — Fundamental]], [[Agent — Regime And Correlation]], [[Agent — Backtest Runner]],
[[Agent — Optimizer]], [[Agent — Insight Miner]], [[Agent — Performance Analyst]],
[[Agent — Backtest Vs Live Drift]], [[Agent — Digest]]

See [[Daemon And Cadence]] for the schedule.

## Request lifecycle

You say *"Genesis, find me a long setup in semis and chart it."*

1. **[[Voice Stack]]** — wake word fires, Scribe streams a transcript.
2. **[[Orchestrator]]** — intent = `directed`. Planner decomposes:
   `screen.sector(semis, long)` → `idea.synthesize` → `chart.markup`.
3. **[[Task Bus]]** — three tasks queued on the `user` lane, dependency-ordered.
4. **[[Agent — Screener]]** — pulls the semis universe through [[MCP Gateway]],
   runs the saved long scans, returns 6 candidates.
5. **[[Agent — Idea Synthesizer]]** — fuses with news, sentiment, regime; ranks;
   writes the top idea to the vault per [[Idea Schema]].
6. **[[Agent — Chart Markup]]** — computes levels, emits a [[Markup Spec]], renders a PNG.
7. **[[Orchestrator]]** — speaks a two-sentence summary; the chart appears on the
   [[Dashboard]]; the note lands in Obsidian.
8. **[[Episodic Log]]** — the whole chain is recorded, linkable from the idea note.

If you then say *"take it, half size"* — the chain continues into
[[Agent — Order Manager]], stops at [[Pre-Trade Risk Engine]], and returns to you
for confirmation per [[Approval Modes]].

## Invariants

The design is wrong if any of these break. See [[Safety Invariants]].

1. Agents never call each other directly — [[Task Bus]] or [[Memory Fabric]] only.
2. Every order passes [[Pre-Trade Risk Engine]]. Human orders too.
3. [[Kill Switch]] works with the LLM dead.
4. Untrusted text is never instruction.
5. Losing internet degrades to research-only; it never corrupts state.
