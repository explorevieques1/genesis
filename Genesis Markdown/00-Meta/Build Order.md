---
title: Build Order
tags: [meta, plan]
---

# Build Order

Ten phases. Each ends with something demonstrable. Do not start a phase until the
previous one's exit criteria pass.

Resolve [[Open Questions]] before Phase 1.

---

## Phase 0 — Decide and scaffold

- Answer [[Open Questions]]: broker, asset class, prop-firm rules, language, vault location.
- Recommended: **Python core** (matches [[Trading Corpus Index|the corpus]]) +
  **Node/Electron dashboard** (matches [[Repo — Gensis Terminal Official]]).
- Repo layout, `pyproject.toml`, config loader ([[Config And Secrets]]), logging
  ([[Observability]]), test + eval harness (pattern: [[Repo — jarvis]] `EVALS.md`).

**Exit:** `genesis --version` runs; config loads; one passing test.

---

## Phase 1 — Skeleton

Build the spine with zero intelligence in it.

- [[Daemon And Cadence]] — the forever loop, market calendar, cron
- [[Task Bus]] — priority lanes, persistence, retry
- [[Agent Contract]] — base class: `start / stop / status / run_task`
- [[Memory Fabric]] — SQLite schemas for [[Working Memory]], [[Episodic Log]], [[Trade Ledger]]
- Supervision: crash → backoff restart → degraded state

Reference: [[Repo — jarvis]] daemon, [[Repo — gensis-agents]] `shared/agent-base.js` + `task-queue.js`.

**Exit:** a no-op "echo agent" registers, is scheduled, runs on a cadence, survives a kill -9, and its runs appear in the [[Episodic Log]].

---

## Phase 2 — Orchestrator voice loop

Make it talk. No agents yet.

- [[Voice Stack]] — mic → VAD → wake word → ElevenLabs Scribe STT
- Intent classification (directed / ambient / follow-up / stop)
- [[Orchestrator]] planner — decompose into a task list
- ElevenLabs streaming TTS + barge-in + earcons
- [[Working Memory]] conversation buffer

Reference: [[Repo — jarvis]] `listening/`, `reply/planner.py`, `output/`.

**Exit:** you say "Genesis, what time does the market open?" and hear a spoken answer. Ambient conversation is ignored. Saying "stop" cuts speech mid-word.

---

## Phase 3 — MCP gateway

- [[MCP Gateway]] — registry, smart tool selection, persistent per-server runtime
- Untrusted-content fencing
- Per-agent allow-lists
- Wire first servers: market data, Obsidian, filesystem, time

Reference: [[Repo — jarvis]] `tools/registry.py`, `tools/selection.py`, `tools/external/mcp_runtime.py`.

**Exit:** 100+ tools registered, the router selects a relevant handful per task, and adding a server does not slow or degrade replies.

---

## Phase 4 — Read-only agents (prove autonomy)

The first real intelligence. Nothing here can spend money.

- [[Agent — Market Analyst]]
- [[Agent — News And Catalyst]]
- [[Agent — Screener]]
- [[Agent — Chart Markup]]
- [[Agent — Idea Synthesizer]]
- [[Obsidian Vault Schema]] writing — ideas and daily research notes

**Exit:** leave it running overnight and through one session. In the morning the
vault has a daily brief and ≥3 ranked ideas with theses, invalidations, and charts —
none of which you asked for.

---

## Phase 5 — Backtest agents

- [[genesis-backtest-mcp]] — one call, full result
- [[Agent — Strategy Author]] · [[Agent — Backtest Runner]] · [[Agent — Risk Metrics]] · [[Agent — Optimizer]]
- [[Strategy Schema]] as the contract between them

Reference: vectorbt, `backtesting.py`, freqtrade hyperopt, `empyrical/stats.py` — see [[Trading Corpus Index]].

**Exit:** "Genesis, backtest that idea over five years" returns spoken headline
metrics plus a full tearsheet in the vault, with walk-forward and an out-of-sample holdout.

---

## Phase 6 — Dashboard

- [[Dashboard]] — agent grid, activity feed, idea board, chart pane, transcript
- WebSocket stream off the [[Task Bus]] and [[Event Schema]]

Reference: [[Repo — gensis-agents]] orchestrator, [[Repo — Gensis Terminal Official]] widgets.

**Exit:** you can watch the whole fleet work in real time without reading a log.

---

## Phase 7 — Execution (paper only)

The dangerous phase. Build the gate before the gun.

Order of construction is deliberate:
1. [[Trade Ledger]] and [[Agent — Position And PnL Accountant]]
2. [[Risk Envelope]] and [[Pre-Trade Risk Engine]] — **before** any broker code
3. [[Kill Switch]] — standalone process, no LLM in the path
4. [[Agent — Broker Adapter]] (paper keys) and [[Agent — Order Manager]]
5. [[genesis-execution-mcp]] wrapping all of it
6. [[Approval Modes]] — ship in `advisory`, then `confirm`

**Exit:** paper orders fill; every one passed the gate; the ledger reconciles
against the broker; "Genesis, halt" cancels everything in under a second.

---

## Phase 8 — Journal and learning

- [[Agent — Trade Journal]] — every fill becomes a vault note with entry/exit charts
- [[Agent — Performance Analyst]] · [[Agent — Insight Miner]] · [[Agent — Backtest Vs Live Drift]]
- [[Knowledge Graph]] + [[Memory Consolidation]] nightly job

**Exit:** after two weeks of paper trading, the system tells you something true
about your trading that you did not already know.

---

## Phase 9 — Go live

- [[Paper To Live Promotion]] gate satisfied by exactly one strategy
- Tightest possible [[Risk Envelope]]
- [[Approval Modes|`confirm`]] mode, spoken confirmation required
- Daily reconciliation alerting

**Exit:** one live trade, fully logged, fully auditable from spoken word to fill.

---

## Phase 10 — Autonomy

- [[Approval Modes|`auto-within-limits`]] for setups with proven live edge
- Expand the fleet: [[Agent — Sentiment]], [[Agent — Fundamental]],
  [[Agent — Regime And Correlation]], [[Agent — ML Signal]], [[Agent — Multi Timeframe]]
- [[Agent — Prop Firm Guard]] if trading a funded account

**Exit:** the system trades a proven setup unattended inside its envelope, and
tells you about it afterwards.

---

## What not to do

- Do not build execution before the risk engine.
- Do not go live before [[Paper To Live Promotion]] passes.
- Do not add agents in Phase 4 beyond the five listed — prove the loop first.
- Do not let any agent talk to another agent directly. [[Task Bus]] or memory only.
