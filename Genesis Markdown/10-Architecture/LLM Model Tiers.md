---
title: LLM Model Tiers
tags: [architecture]
status: building
implemented_by: [src/genesis/llm/backend.py]
---

# LLM Model Tiers

Route by task cost, not by habit. Most calls in a JARVIS system are trivial
classifications that should never touch a frontier model.

Pattern: [[Repo — jarvis]] `src/jarvis/llm/tiers.py`, `factory.py`, `backend.py`.

## The tiers

| Tier | Used for | Latency budget | Model | Where |
|---|---|---|---|---|
| **nano** | wake/intent classification, echo detection, [[Recall Pathways\|recall gate]], lane routing | <100 ms | *none — deterministic code* | local CPU |
| **small** | tool routing, planner step resolution, note formatting, summarisation, sentiment tagging | <500 ms | `claude-haiku-4-5` | hosted |
| **large** | orchestrator reasoning, [[Agent — Idea Synthesizer\|idea synthesis]], [[Agent — Strategy Author\|strategy authoring]], risk debate | 2–10 s | `claude-opus-5` | hosted |
| **vision** | [[Agent — Pattern Recognition\|chart pattern reading]], screenshot understanding | 2–10 s | `claude-opus-5` | hosted |
| **embedding** | [[Vector Store]], corpus search | batch | `bge-small-en-v1.5` (ONNX) | local CPU |

Model assignment is fixed by [[Open Questions]] §4 — no GPU on the build machine, so
nothing generative runs local. Pricing at time of decision: Haiku 4.5 $1/$5 per MTok
(200K context), Opus 5 $5/$25 per MTok (1M context).

**The nano tier is not a model.** A hosted round-trip is 300–800 ms at best, so the
`<100 ms` budget cannot be met by any network call. Wake word, intent, echo detection
and the recall gate are keyword/regex plus a small ONNX classifier on CPU. This
removes an LLM from the voice hot path rather than relocating it.

## Measured latency (2026-08-30)

The nano tier's <100 ms budget is **not achievable on the current machine**.
Measured with `qwen2.5:3b` on CPU via Ollama, asked for a one-word intent class:

| Utterance | Latency | Answer |
|---|---|---|
| "Genesis, what time does the market open?" | 6469 ms | `followup` (wrong) |
| "yeah I think semis are extended" | 1811 ms | `followup` (wrong) |
| "and what about SPY" | 1319 ms | `followup` (right by luck) |

13–65x over budget, and wrong. Two consequences, both already in code:

1. **Intent classification is deterministic** — reflex table, echo overlap,
   wake-word substring, follow-up timestamp — and resolves in 0.1–3 ms. See
   [[Orchestrator]] and `src/genesis/orchestrator/intent.py`. This is the
   [[Biological Design]] reflex arc applied exactly as written: most things
   reached for a model are reflexes.
2. **The residue defaults to `ambient`** — speech that no deterministic rule
   claims is treated as the room talking, and nothing happens. Uncertainty
   resolves to inaction, which is the fail-closed direction here.

An optional nano judge can be injected for installs with a genuinely fast local
tier. It is off by default, may only promote `ambient` → `directed`, and is never
consulted before a reflex. **No model can sit between the operator and the kill
switch.**

## Wiring the hosted tiers

`src/genesis/llm/anthropic_backend.py`. Three Opus 5 API facts that are 400s
rather than warnings, recorded because each one costs an afternoon otherwise:

- **No `temperature` / `top_p` / `top_k`.** Removed on the 4.6+ family. The
  `Backend` protocol still carries `temperature` for the local backends, so the
  Anthropic backend accepts and drops it.
- **No `budget_tokens`.** Thinking is adaptive; depth is `output_config.effort`.
  On Opus 5 thinking is *on by default* — omitting the parameter runs adaptive.
- **Identity-linked keys need `anthropic-workspace-id`** on every request. Without
  it every call fails with a 400 whose message reads like a malformed body. Set
  `ANTHROPIC_WORKSPACE_ID`; ordinary keys must not send it.

Effort defaults to `low` on the voice path. The budget is *"wake → first spoken
word in under 1.5 s"*, and thinking longer is paid in silence the operator hears.
Research agents off the voice path should raise it.

## Routing rules

- **Default down.** Start at the cheapest tier that can plausibly do the job; escalate
  on low confidence, never pre-emptively.
- **Keep the nano chain warm.** The ONNX classifier and the embedding model stay
  loaded — cold-start latency destroys the [[10-Architecture/Voice Stack]] budget.
  The small tier is hosted, so its cost is one HTTP round-trip: reuse the client,
  keep the connection pooled, and cache the system prompt prefix.
- **Escalate explicitly.** A small-tier agent that can't decide returns
  `needs_escalation` rather than guessing. The orchestrator re-runs on large.
  Small and large are the same SDK and the same message format, so escalation is a
  model-string swap — see [[Agent Contract]].
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
  and logs it. Enforced in-flight with `output_config.task_budget` — a ceiling the
  model paces itself against, distinct from `max_tokens`, which just truncates.
- Cache aggressively: same symbol + same bar + same prompt → cached result. Use
  prompt caching for the in-flight half — frozen system prompt and deterministic
  tool list first, volatile bar data after the last breakpoint, or nothing caches.
  Verify with `usage.cache_read_input_tokens`; a persistent zero means a silent
  invalidator (a timestamp, an unsorted dict) sits in the prefix.
- Closed-market work batches through the Batch API at 50% cost; open-market work
  streams.
- The [[Dashboard]] shows spend by agent so an expensive agent is visible, not silent.

## Degradation

| Failure | Behaviour |
|---|---|
| Hosted large tier unavailable | escalate-to-large returns `degraded`; small tier answers with a labelled caveat |
| Large tier returns `stop_reason: "refusal"` | HTTP 200 with no usable content — **not** an exception. Check `stop_reason` before reading `content`, or the loop hangs silently. Server-side `fallbacks` routes around it automatically |
| Local models unavailable | nano/small route to hosted-cheap; latency budget breaks, announce it |
| All LLMs unavailable | deterministic agents ([[Agent — Position And PnL Accountant]], [[Agent — Level Watcher]], [[Pre-Trade Risk Engine]], [[Kill Switch]]) keep working. **The system stays safe without any LLM.** |

## Acceptance criteria

- ≥90% of LLM calls in a typical session resolve on the small tier (`claude-haiku-4-5`).
- Zero LLM calls on the nano path — wake, intent and the recall gate never hit the
  network (prove by test: assert no HTTP client is reachable from that call path).
- No safety-critical decision has an LLM in its call path (prove by test).
- Killing the hosted endpoint leaves risk, P&L, and kill switch fully functional —
  and leaves wake/intent working, since nano is local.

## Related

[[10-Architecture/Voice Stack]] · [[Orchestrator]] · [[Agent Contract]] · [[Observability]] · [[Safety Invariants]]
