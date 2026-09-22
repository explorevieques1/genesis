---
title: Glossary
tags: [meta]
---

# Glossary

| Term | Meaning in Genesis |
|---|---|
| **Agent** | A focused specialist with one job, its own prompt, tool allow-list, memory namespace, and cadence. See [[Agent Contract]]. |
| **Orchestrator** | Genesis itself — the senior analyst. Takes a request (typed or spoken), decides what would answer it, and puts the fleet on it. See [[Orchestrator]], [[Operating Model]]. |
| **Parity rule** | Anything Genesis can do, a person can do by hand, through the same door and the same audit line. [[Operating Model]] §2. |
| **Cadence** | When an agent runs: `on-demand`, `market-open`, `market-closed`, `cron`, or `event`. See [[Daemon And Cadence]]. |
| **Task Bus** | The priority queue all work flows through. Agents never call each other directly. See [[Task Bus]]. |
| **Idea** | A structured, ranked trade thesis with entry zone, invalidation, timeframe, and confidence. See [[Idea Schema]]. |
| **Invalidation** | The condition that proves an idea wrong. Every idea must have one — no invalidation, no idea. |
| **Markup Spec** | A declarative, re-renderable description of chart annotations (levels, zones, lines, labels). See [[Markup Spec]]. |
| **Risk Envelope** | The signed set of hard limits every order is checked against. See [[Risk Envelope]]. |
| **Portfolio heat** | Total open risk — the sum of (entry − stop) × size across all positions, as a % of equity. |
| **R / R multiple** | A trade's result expressed in units of its initial risk. Losing the full stop = −1R. |
| **MAE / MFE** | Maximum Adverse / Favourable Excursion — worst and best unrealized point of a trade. Feeds [[Agent — Insight Miner]]. |
| **Approval mode** | How much autonomy execution has: `advisory`, `confirm`, `auto-within-limits`, `halt`. See [[Approval Modes]]. |
| **Fence** | Wrapping untrusted external text (news, social, web) as data so it can never act as instructions. See [[MCP Gateway]]. |
| **Recall gate** | A cheap classifier deciding whether memory lookup is needed at all, before paying for retrieval. See [[Recall Pathways]]. |
| **Superseding** | A newer fact about an entity outranking and marking the older one stale. See [[Recall Pathways]]. |
| **Consolidation** | The nightly job that merges duplicates, promotes observations to beliefs, and summarises. See [[Memory Consolidation]]. |
| **Namespace** | The slice of memory an agent may read and write. Keeps News chatter out of Execution. |
| **Earcon** | A short non-verbal tone signalling state (heard / working / done / blocked). See [[Voice UX]]. |
| **Barge-in** | Talking over the assistant's speech and having it stop and listen. |
| **Walk-forward** | Optimizing on a rolling in-sample window and testing on the next out-of-sample window. Guards overfitting. See [[Agent — Optimizer]]. |
| **Deflated Sharpe** | A Sharpe ratio adjusted for the number of trials run — the honest number after a parameter sweep. |
| **Regime** | The prevailing market state (trend/range, vol level, risk-on/off) a strategy assumes. See [[Agent — Regime And Correlation]]. |
| **FVG** | Fair Value Gap — an imbalance left by a fast move; a common intraday level. |
| **ORB** | Opening Range Breakout — the high/low of the session's first N minutes. |
| **AVWAP** | Anchored VWAP — volume-weighted average price anchored to a chosen event. |
| **Drift** | Divergence between live results and the strategy's backtest expectation. Either regime change or a bug. See [[Agent — Backtest Vs Live Drift]]. |
| **Promotion** | The gated process moving a strategy from paper to live. See [[Paper To Live Promotion]]. |
| **Corpus** | The read-only library of cloned third-party repos used as reference. See [[Trading Corpus Index]]. |
| **MCP** | Model Context Protocol — the tool-server standard all external capability arrives through. See [[MCP Gateway]]. |
