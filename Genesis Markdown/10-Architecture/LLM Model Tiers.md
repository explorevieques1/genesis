---
title: LLM Model Tiers
tags: [architecture]
status: building
implemented_by: [src/genesis/llm/backend.py, src/genesis/llm/anthropic_backend.py, src/genesis/llm/openai_compat.py, src/genesis/llm/usage.py, src/genesis/llm/tiers.py, src/genesis/cli.py, src/genesis/llm/parse.py, tests/llm/test_anthropic_tool_loop.py, tests/llm/test_bad_request.py, tests/llm/test_ollama_status.py, tests/llm/test_providers.py]
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

## Development tiers

The tier table above is the **production** assignment. Development is a separate
question it does not answer, and answering it badly costs real money: exercising
the orchestrator against `claude-opus-5` bills the operator for every loop
iteration of work that is testing plumbing, not reasoning.

So `backend` on each tier names a provider, and the same tier table can be
pointed somewhere free. `config-dev.example.yaml` is that profile, selected by
`GENESIS_CONFIG` — a whole config file, not a flag, because most callers reach
config through a bare `load_config()` and a profile that applies to only part of
the process is worse than none.

| Backend | Cost | Where it is fit for | Caveat |
|---|---|---|---|
| `anthropic` | paid | everything, including live | the production path |
| `ollama` | free | `small` — tool routing, summarisation, note formatting | **measured 2026-09-07:** `qwen2.5:3b` warm p50 **352 ms**, cold load 16.5 s. Off the voice path |
| `gemini` | free tier | `large`, `vision` in development | **Google trains on free-tier prompts.** Flash/Flash-Lite only since Pro left the free tier in April 2026; ~15 rpm, 1500/day |
| `groq`, `openrouter` | free tier | same | same class of trade |

### The dev-only guard is structural

A free tier that trains on its prompts must never see a live thesis, position,
or P&L. That is not a comment in a config file — `_tier_backend` **refuses to
build** a `dev_only` provider when the broker is live, and every provider in
`PROVIDERS` carries the flag. Under [[Biological Design]] §reflex arc this is
spinal: "remember to switch the profile back" is exactly the instruction a
reflex exists to replace.

The profile split is what makes that refusal rare rather than routine. Editing
the tier table in `~/.genesis/config.yaml` directly is the configuration where
one forgotten edit runs a development model against real money.

### Switching a tier

One function, two doors ([[Operating Model]] §parity rule):

```
genesis config set-tier large gemini gemini-flash-latest   # typed
POST /v1/settings/models/set                               # the Models panel
```

Both call `llm/tiers.py::set_tier`, which validates by loading the merged config
back before it writes, and writes atomically. **A tier change takes effect on
daemon restart** — fleets bind their backends once at construction — and both
doors say so rather than showing a green tick over a daemon still talking to the
old provider.

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

**Token accounting is built; enforcement is not.** `llm/usage.py` records every
call — provider-reported token counts, never a local estimate, because a budget
enforced against our own tokeniser is a budget that disagrees with the invoice.
`MeteredBackend` wraps every tier, and the meter swallows its own storage errors:
instrumentation that can take down the thing it measures is a worse bug than a
gap in the data. Read it with `genesis config usage` or the **Models** panel.

**`daily_token_budget` refuses now** (2026-09-17, `llm/usage.py` `Budget`). The
sense came first on purpose — never build an actuator before the sense that
verifies it acted ([[Biological Design]] §proprioception) — and this is the
regulator that was waiting on it.

- One ceiling per *day*, shared by every tier. Per-tier budgets would let the
  large tier eat the day and leave the small tier a number it can never reach.
- The day's spend is read from the meter once and tracked in memory as calls
  land. A `SELECT SUM(...)` before every call would put a disk read on the hot
  path; the in-memory count can only drift *low*, which makes the ceiling
  slightly generous rather than slightly arbitrary.
- Past the ceiling, a hosted call raises **`degraded`**, never `fatal`. Every
  deterministic path — risk, the accountant, the level watcher, the kill switch
  — has no model in it and keeps working, which is the whole point of
  `tier: none`. Spoken: *"I've spent today's model budget, so I'm working
  without a model."*
- An unreadable meter does **not** close the tier. Refusing every call because
  the *counter* broke would take the system down to protect a cost limit.
- `daily_token_budget: 0` disables the ceiling; the meter still records.

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

## Every provider, through one builder

`genesis.llm.tiers.build_tier` constructs a tier and returns it metered, or
returns `None` and a note saying why. Two callers: `cli._tier_backend` for the
fleets, and [[Orchestrator|build_ladder]] for the answer ladder.

It is one function because it was two. The CLI copy learned `gemini`, `groq`,
`openrouter` and `ollama`; the ladder's copy built `anthropic` inline and noted
*"large tier backend 'gemini' is not wired yet"* for everything else. So a free
tier answered on the command line and the terminal said **"I can't reach my
reasoning model right now"** — the same capability present through one door and
absent through another, which [[Operating Model]] §1 exists to forbid.

## Gemini thinks out of your token budget

`gemini-flash-latest` reasons before it writes, spends that reasoning from the
**same `max_tokens`** the answer comes from, and returns none of it. Measured
live at the Reasoner's own default of 300:

| request | finish | visible tokens | result |
|---|---|---|---|
| plain | `length` | 11 | cut off mid-sentence |
| `reasoning_effort: "none"` | `stop` | 64 | complete |

At smaller budgets it returns an **empty string with a 200**. So the provider
entry sends `reasoning_effort: "none"` on every call, and
`OpenAICompatBackend` refuses an empty completion rather than passing `""` up
as an answer — Conventions §Errors, and an empty string is a confabulation when
the model never spoke.

`reasoning_effort` is a **per-model** capability, not a per-provider one:
`gemini-flash-latest` needs it, and `gemini-flash-lite-latest` rejects the same
request with `400 invalid argument` and cannot run at all. The provider table
only knows the provider, so the backend sends it, and on a 400 drops it and
retries — once, then remembers. A model list would go stale the next time
Google ships a name.

Its free tier also returns `503 "high demand"` constantly — two failures in
three calls on an idle key. A 503 is retried twice with a short backoff; a 429
is not, because a quota is spent rather than busy and retrying spends it
faster. Both quotas are per-model: `gemini-flash-latest` runs out long before
`gemini-flash-lite-latest`, which is why the flash-lite switch is offered
first in `MT`.

## A local tier can look configured and be dead

A hosted tier without a key says so on the settings panel. Ollama has no key to
be missing and no vendor to be down, so `ollama pull` never having been run is
invisible — and a `small` tier pointed at an unpulled `qwen2.5:3b` answers every
planning request with a 404 while the panel shows a green **local** chip. That
is what took the planner down on this machine, and nothing on the surface said
so.

`backend.ollama_status()` asks Ollama's own model list over loopback. Free,
instant, and no vendor involved — which is why it is safe to run on a settings
render where probing a *hosted* tier would bill the operator for opening a
panel. The panel shows the answer as the blocker chip: *"ollama has no models
pulled — run `ollama pull qwen2.5:3b`"*.


## Related

[[10-Architecture/Voice Stack]] · [[Orchestrator]] · [[Agent Contract]] · [[Observability]] · [[Safety Invariants]]
