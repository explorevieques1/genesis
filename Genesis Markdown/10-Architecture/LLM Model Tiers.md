---
title: LLM Model Tiers
tags: [architecture]
status: spec
implemented_by: []
---

# LLM Model Tiers

Route by task cost, not by habit. Most calls in a JARVIS system are trivial
classifications that should never touch a frontier model.

Pattern: [[Repo — jarvis]] `src/jarvis/llm/tiers.py`, `factory.py`, `backend.py`.

## The tiers

| Tier | Used for | Latency budget | Where |
|---|---|---|---|
| **nano** | wake/intent classification, echo detection, [[Recall Pathways\|recall gate]], lane routing | <100 ms | local (Ollama) |
| **small** | tool routing, planner step resolution, note formatting, summarisation, sentiment tagging | <500 ms | local or cheap hosted |
| **large** | orchestrator reasoning, [[Agent — Idea Synthesizer\|idea synthesis]], [[Agent — Strategy Author\|strategy authoring]], risk debate | 2–10 s | hosted (Claude class) |
| **vision** | [[Agent — Pattern Recognition\|chart pattern reading]], screenshot understanding | 2–10 s | hosted vision-capable |
| **embedding** | [[Vector Store]], corpus search | batch | local |

## Routing rules

- **Default down.** Start at the cheapest tier that can plausibly do the job; escalate
  on low confidence, never pre-emptively.
- **Keep the small chain warm.** The nano and small models stay loaded — cold-start
  latency destroys the [[Voice Stack]] budget.
- **Escalate explicitly.** A small-tier agent that can't decide returns
  `needs_escalation` rather than guessing. The orchestrator re-runs on large.
- **Vision is expensive.** Render once, ask once. Cache the interpretation against
  the [[Markup Spec]] id.
- **Never route untrusted text to a tool-enabled model without a fence.** See [[MCP Gateway]].

## Per-agent assignment

| Tier | Agents |
|---|---|
| nano | intent classification, recall gate (inside [[Orchestrator]]) |
| small | [[Agent — Screener]], [[Agent — Sentiment]], [[Agent — Digest]], [[Agent — Watchdog]], journal formatting |
| large | [[Agent — Market Analyst]], [[Agent — Idea Synthesizer]], [[Agent — Strategy Author]], [[Agent — Insight Miner]], [[Agent — Performance Analyst]], [[Agent — Fundamental]] |
| vision | [[Agent — Pattern Recognition]], [[Agent — Multi Timeframe]] |
| embedding | [[Vector Store]] writes, [[Memory Consolidation]] |
| **none** | [[Pre-Trade Risk Engine]], [[Kill Switch]], [[Agent — Position And PnL Accountant]], [[Agent — Risk Metrics]], [[Agent — Order Manager]] |

That last row is the important one. **Nothing safety-critical or arithmetic runs on
an LLM.** Risk checks, P&L, position sizing, and metrics are deterministic code with
unit tests. LLMs propose; deterministic code disposes.

## Cost control

- Per-agent token budget per day; exceeding it degrades the agent to a lower tier
  and logs it.
- Cache aggressively: same symbol + same bar + same prompt → cached result.
- Closed-market work batches; open-market work streams.
- The [[Dashboard]] shows spend by agent so an expensive agent is visible, not silent.

## Degradation

| Failure | Behaviour |
|---|---|
| Hosted large tier unavailable | escalate-to-large returns `degraded`; small tier answers with a labelled caveat |
| Local models unavailable | nano/small route to hosted-cheap; latency budget breaks, announce it |
| All LLMs unavailable | deterministic agents ([[Agent — Position And PnL Accountant]], [[Agent — Level Watcher]], [[Pre-Trade Risk Engine]], [[Kill Switch]]) keep working. **The system stays safe without any LLM.** |

## Acceptance criteria

- ≥90% of LLM calls in a typical session resolve on nano or small.
- No safety-critical decision has an LLM in its call path (prove by test).
- Killing the hosted endpoint leaves risk, P&L, and kill switch fully functional.

## Related

[[Voice Stack]] · [[Orchestrator]] · [[Agent Contract]] · [[Observability]] · [[Safety Invariants]]
