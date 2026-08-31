---
title: Genesis Agent — Home
tags: [moc, genesis]
status: design
---

# 🜲 Genesis Agent

> A JARVIS-style, always-on trading intelligence system. One voice-driven
> orchestrator commands a fleet of specialist agents that research markets,
> mark up charts, backtest ideas, write to Obsidian, and execute trades —
> while the market is open **and** closed.

**Status: design only. No code yet.** This vault is the spec Claude Code builds from.

Start here → [[How To Use This Vault]] · [[Biological Design]] · [[System Overview]] · [[Agent Index]] · [[Build Order]]

Coding this out? → [[Working With Claude Code]] · [[Vault Map]]

---

## The four pillars

| Pillar | Entry point | One line |
|---|---|---|
| 🎙️ **Voice** | [[Orchestrator]] | The only thing you talk to. ElevenLabs in and out. |
| 🤖 **Agents** | [[Agent Index]] | ~30 specialists, each with tools, cadence, and a memory namespace. |
| 🧠 **Memory** | [[Memory Fabric]] | Five layers. Obsidian is the human view, graph+vector is the machine view. |
| 🛡️ **Risk** | [[Pre-Trade Risk Engine]] | One gate. No bypass. Separate process from the LLM path. |

---

## Map of content

### 00 — Meta
- [[How To Use This Vault]] — conventions, tags, how to read a spec
- [[Build Order]] — the 10-phase plan, what to code first
- [[Working With Claude Code]] — how this vault drives the build
- [[Vault Map]] — generated name → path index for all notes
- [[Open Questions]] — decisions needed before phase 1
- [[Glossary]] — terms used throughout
- [[Conventions]] — code, logging, and spec-file house style

### 10 — Architecture
- [[Biological Design]] — **the organising metaphor**: which organ is this, reflex or judgement?
- [[System Overview]] — topology diagram, the whole picture
- [[Orchestrator]] · [[10-Architecture/Voice Stack]] · [[Approval Modes]]
- [[Task Bus]] · [[Daemon And Cadence]] · [[Agent Contract]]
- [[LLM Model Tiers]] · [[Charting Engine]] · [[Markup Spec]]
- [[Observability]] · [[Config And Secrets]] · [[Error Handling And Degradation]]

### 20 — Agents
- [[Agent Index]] — the full fleet table
- Families: [[Research Family]] · [[Charting Family]] · [[Strategy Family]] · [[Execution Family]] · [[Journal Family]]

### 30 — MCP
- [[MCP Gateway]] — registry, smart tool selection, persistent runtime, fencing
- [[MCP Server Catalog]] — what to integrate
- Custom: [[genesis-execution-mcp]] · [[genesis-charting-mcp]] · [[genesis-memory-mcp]] · [[genesis-backtest-mcp]]

### 40 — Memory
- [[Memory Fabric]] — the five layers
- [[Working Memory]] · [[Episodic Log]] · [[Knowledge Graph]] · [[Vector Store]] · [[Trade Ledger]]
- [[Recall Pathways]] · [[Memory Consolidation]] · [[Obsidian Vault Schema]]

### 50 — Risk
- [[Safety Invariants]] — the ten non-negotiables
- [[Pre-Trade Risk Engine]] · [[Risk Envelope]] · [[Kill Switch]] · [[Prop Firm Rules]] · [[Paper To Live Promotion]]

### 60 — UI
- [[Dashboard]] · [[Voice UX]] · [[Desktop Shell]] · [[Widget Catalog]]

### 70 — Schemas
- [[Data Model Overview]] · [[Idea Schema]] · [[Trade Journal Schema]] · [[Strategy Schema]] · [[Order And Fill Schema]] · [[Markup Spec Schema]] · [[Event Schema]]

### 80 — Repos
- [[Repo Map]] — every relevant repo on this machine
- [[Trading Corpus Index]] — the read-only reference library and how to use it

### 99 — Canvas
- `Genesis System.canvas` — open in Obsidian for the visual map

---

## The one-paragraph version

You speak. The [[Orchestrator]] hears you via [[10-Architecture/Voice Stack]], classifies intent,
plans a task list, and dispatches onto the [[Task Bus]]. Specialist agents pick up
work, reach tools through the [[MCP Gateway]], and write everything they learn into
the [[Memory Fabric]] — which mirrors into an Obsidian vault you can read and edit.
Anything that would place an order stops at the [[Pre-Trade Risk Engine]] and then
at your chosen [[Approval Modes|approval mode]]. Meanwhile the [[Daemon And Cadence|daemon]]
never stops: open-market loops scan and watch levels, closed-market loops backtest,
mine the journal, and prepare tomorrow's brief.
