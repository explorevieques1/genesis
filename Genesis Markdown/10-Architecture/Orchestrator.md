---
title: Orchestrator
tags: [architecture, core]
status: spec
implemented_by: []
---

# Orchestrator

The only thing you talk to. A thin, always-warm coordinator — **deliberately not**
where heavy reasoning happens.

Reference architecture: [[Repo — jarvis]] (`listening/`, `reply/planner.py`,
`tools/selection.py`, `daemon.py`) and [[Repo — gensis-agents]] (`orchestrator/`).

## Responsibilities

| # | Job | Detail |
|---|---|---|
| 1 | **Listen** | Wake-word + ambient listening, VAD, echo rejection → [[Voice Stack]] |
| 2 | **Understand** | Classify each utterance: `directed` / `ambient` / `follow-up` / `stop` |
| 3 | **Plan** | Decompose a request into an ordered task list with owners |
| 4 | **Route** | Dispatch onto the [[Task Bus]]; hold cron jobs |
| 5 | **Gate** | Anything spending money passes [[Approval Modes]] before leaving |
| 6 | **Speak** | Stream a short spoken summary; push detail to [[Dashboard]] and the vault |
| 7 | **Remember** | Write turns, decisions, and outcomes to [[Memory Fabric]] |

What it does **not** do: fetch market data, compute indicators, reason about a
strategy, or place an order. It delegates all of it.

## Intent classification

Runs on the nano tier ([[LLM Model Tiers]]) so it's near-free and fast.

| Class | Trigger | Action |
|---|---|---|
| `directed` | Wake word present, or a follow-up window is open | Plan and dispatch |
| `ambient` | Speech with no wake word | Buffer into rolling context, do nothing |
| `follow-up` | Speech within N seconds of a reply, no wake word | Treat as directed, with prior context |
| `stop` / `halt` | "stop", "cancel", "halt", "flatten" | Interrupt TTS; `halt` → [[Kill Switch]] |
| `echo` | Matches what we just said | Discard |

The **ambient buffer** is what makes it feel like a third person in the room: when
you say "Genesis, what do you think?" it already knows what you were discussing.
(Pattern: [[Repo — jarvis]] `listening/transcript_buffer.py`, `intent_judge.py`.)

## Planning

For each `directed` utterance the planner emits a task list:

```yaml
utterance: "find me a long setup in semis and chart it"
tasks:
  - id: t1
    type: screen.sector
    agent: screener
    args: { sector: semiconductors, direction: long }
  - id: t2
    type: idea.synthesize
    agent: idea-synthesizer
    depends_on: [t1]
  - id: t3
    type: chart.markup
    agent: chart-markup
    depends_on: [t2]
    args: { timeframes: [1D, 1H] }
speak_after: t3
verbosity: brief
```

Rules:
- **Fail open** — if planning fails, hand the raw utterance to the large tier and
  let it call tools directly. Never leave the user unanswered.
- **Small models get direct-exec** — resolve one step at a time rather than
  planning the whole chain. (Pattern: [[Repo — jarvis]] `planner.spec.md`.)
- **Dependencies are explicit** — the [[Task Bus]] honours them.
- **Trivial requests skip planning** — "what time is it" needs no task list.

## Routing

The orchestrator picks the agent, not the tool. Agents pick their own tools through
[[MCP Gateway]]. This keeps the orchestrator's context small no matter how many
tools exist.

Its own tool surface is deliberately tiny and fixed — dispatch, observe, fleet
control, safety, and one escape hatch. Roughly fifteen tools, none of them domain
work. See **[[Orchestrator Tools]]** for the full surface and for how data moves
between agents without passing through here.

Routing inputs: task type → [[Agent Index]] capability table, current agent load,
agent health from [[Agent — Watchdog]].

If no agent fits, the orchestrator answers directly on the large tier — with tools
selected by the gateway router.

## Speaking

Spoken output is **short by default**. Detail goes to the [[Dashboard]] and the vault.

| Verbosity | Example |
|---|---|
| `terse` | "Four ideas. Top is NVDA long." |
| `brief` (default) | "Four ideas ranked. Top is NVDA long from 121, invalidation 118.40, confidence 0.72. Chart's on the dashboard." |
| `full` | Adds the thesis, the catalyst, and the two runners-up. |

Numbers are spoken carefully — see [[Voice UX]] for the number/ticker/price
pronunciation rules. Never speak a raw JSON dump.

## Conversation memory

The orchestrator owns [[Working Memory]]: the last N turns, the current task list,
what's on the [[Dashboard]] right now, and the ambient buffer. Rolls off by time
and size; summarised into the [[Episodic Log]] before it does.

Before answering, the [[Recall Pathways|recall gate]] decides whether deeper memory
is even needed. Most utterances need none — that's what keeps it fast.

## Approval gate

The orchestrator is the last stop before a live order leaves the system. It
enforces [[Approval Modes]]; the [[Pre-Trade Risk Engine]] enforces the numbers.
Both must pass. Neither can be skipped by an agent.

## Acceptance criteria

- Wake → first spoken word in under 1.5 s for a trivial request.
- Ambient conversation for 10 minutes produces zero unwanted actions.
- "Stop" cuts TTS mid-word in under 300 ms.
- A three-step plan dispatches, respects dependencies, and speaks once at the end.
- With the planner deliberately broken, requests still get answered (fail-open).
- Adding 50 MCP tools changes orchestrator latency by less than 10%.

## Related

[[Orchestrator Tools]] · [[Voice Stack]] · [[Task Bus]] · [[Approval Modes]] ·
[[LLM Model Tiers]] · [[Working Memory]] · [[Recall Pathways]] · [[Agent Index]]
