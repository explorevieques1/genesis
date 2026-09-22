---
title: Orchestrator
tags: [architecture, core]
status: building
implemented_by: [src/genesis/orchestrator/answer.py, src/genesis/orchestrator/record.py, src/genesis/orchestrator/verbosity.py, src/genesis/orchestrator/intent.py, src/genesis/orchestrator/loop.py, src/genesis/orchestrator/answers.py, src/genesis/orchestrator/build.py, src/genesis/orchestrator/planner.py, src/genesis/orchestrator/plan.py, src/genesis/orchestrator/registry.py, src/genesis/orchestrator/runner.py, src/genesis/research/findings.py, src/genesis/orchestrator/tools.py, src/genesis/orchestrator/toolbridge.py, src/genesis/orchestrator/reasoner.py, src/genesis/llm/anthropic_backend.py, tests/orchestrator/test_plan.py, tests/orchestrator/test_planner.py, tests/orchestrator/test_reasoner_tools.py, tests/orchestrator/test_voice_planning.py, tests/test_voice_loop.py, ui/src/workspace/panels/automation.tsx]
---

# Orchestrator

The **senior analyst**. A thin, always-warm coordinator — **deliberately not**
where heavy reasoning happens.

> [!important] It advises. It does not command
> [[Operating Model]] is the framing this note assumes. The trader is the head
> trader; the orchestrator takes a question, decides what would answer it, puts
> the fleet on it, and comes back with a briefing. It has full motor control of
> the *software* and no authority over the *trader*.
>
> It is also **not** the only thing you talk to, and the earlier version of this
> line saying so was the root of a real product failure: capabilities ended up
> reachable only by speaking to the router. Every capability here is reachable
> by hand through [[Terminal]] — the **parity rule** — and the typed sentence
> and the spoken one are the same path.

Reference architecture: [[Repo — jarvis]] (`listening/`, `reply/planner.py`,
`tools/selection.py`, `daemon.py`) and [[Repo — gensis-agents]] (`orchestrator/`).

## Responsibilities

| # | Job | Detail |
|---|---|---|
| 1 | **Listen** | Wake-word + ambient listening, VAD, echo rejection → [[10-Architecture/Voice Stack]] |
| 2 | **Understand** | Classify each utterance: `directed` / `ambient` / `follow-up` / `stop` |
| 3 | **Plan** | Decompose a request into an ordered task list with owners |
| 4 | **Route** | Dispatch onto the [[Task Bus]]; hold cron jobs |
| 5 | **Gate** | Anything spending money passes [[Approval Modes]] before leaving |
| 6 | **Speak** | Stream a short spoken summary; push detail to [[Dashboard]] and the vault |
| 7 | **Remember** | Write turns, decisions, and outcomes to [[Memory Fabric]] — `orchestrator/record.py` |

What it does **not** do: fetch market data, compute indicators, reason about a
strategy, or place an order. It delegates all of it.

## The loop

Every non-trivial request runs the same seven steps. They are listed here
because skipping 1, 5 or 6 is what makes a capable system feel broken.

| # | Step | Where |
|---|---|---|
| 1 | **Understand**, and say it back before starting | §Intent classification |
| 2 | **Resolve** the entities — *"Nvidia"* → `NVDA` | §Entity resolution |
| 3 | **Decide** which tools and which agents answer it | §Planning, §Routing |
| 4 | **Dispatch**, honouring dependencies | [[Task Bus]] |
| 5 | **Track** the work, and show it while it runs | [[Fleet View]] |
| 6 | **Persist** the result as an artifact | [[Memory Fabric]] |
| 7 | **Present** the briefing, with the work attached | §Speaking |

**Acknowledgement precedes work.** A multi-minute research pass that answers
with silence is indistinguishable from a hang, so step 1 speaks — *"starting the
research agents now, I'll write the findings to your journal"* — before step 4
dispatches anything.

**A deliverable outlives the conversation.** *"Save it in my journal"* is the
common case. Long-running work lands as a vault note, a markup spec, a backtest
report — something addressable tomorrow. Findings that exist only in a
transcript have not been delivered.

**Every piece of a plan is remembered.** Step 6 includes the pieces, not just
the deliverable. Each finished task about a company becomes a `finding`, keyed
by company and task type and linked to the prompt's trace. Before step 3, the
stored findings for the companies named are recalled into the planner's
context, and a task whose finding is still fresh is answered *"As of …"*
instead of being dispatched again. All three decisions are reflex: which
company, how old, whether reusable. See [[Research Directory]] §Findings.

## Entity resolution

Between understanding and planning sits a step a chat interface does not have:
**turning what the trader said into what the tools take.**

Traders speak in names. *"Why is Nvidia down today?"* must become `NVDA` before
a single tool is chosen, and today it cannot — `company/symbols.py` `normalise()`
validates a symbol and rejects a company name.

This is a **reflex, not judgement** ([[Biological Design]]): a lookup against a
real source (EDGAR company tickers, the exchange listing), deterministic and
auditable. Asking a model *"what is Nvidia's ticker"* is the wrong tier and will
one day answer `NVDIA` with total confidence.

- Ambiguity is **surfaced, never resolved silently**. Two matches ask; zero
  matches say so. A silently wrong ticker is a chart of the wrong company that
  looks completely normal.
- What was resolved is **shown** — `NVDA — NVIDIA Corp` — so a mis-resolution
  costs one glance, not one trade.
- **Not everything is a symbol.** *"Gann"* is a research subject, *"semis"* a
  sector, *"my worst week"* a journal query. Classification comes before lookup,
  and "this is not a symbol" is a common, valid answer.

Identity lives in [[Company Data Model]]; this is its caller.

## Motor control of the surface

The orchestrator opens modules into the current workspace and sets their
subject — through the **same** dock API a person drives ([[Operating Model]]
§5). One
function, two callers, no private channel, and the human can do everything it
does by hand.

It opens and sets. It does not close a panel a person opened, and it never
computes pixel geometry ([[Workspaces]]). Everything it opens is labelled with
the request that opened it: a panel that appeared unexplained is
indistinguishable from a bug.

**Partly built.** A command's answer opens the panel it belongs in, through
the same `revealPanel` a person's click uses: a note opens `notebook`, a screen
opens `screener`, a canvas opens `research-canvas` (`ui/src/App.tsx` `onReply`).
Not built: a general directive from the orchestrator's own tool loop to open
*any* module and set its subject.

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

### How the rules are enforced — built 2026-08-31

The answer ladder is **reflex → plan → large tier**, and each rung only pays for
itself when the one above declines:

| Rung | Component | Cost |
|---|---|---|
| Verbosity command | `verbosity.py` — "be terse" | no model |
| Deterministic answer | `answers.py` — calendar, clock | no model |
| Plan | `planner.py` → `plan.py` → `runner.py` | one small-tier call |
| Fail open | `reasoner.py` | one large-tier call |

**The model's plan is never trusted.** `plan.py` parses it into a strict schema
and rejects cycles, dangling and self references, duplicate ids, unknown agents,
task types an agent does not handle, oversized args, and any unknown key. What
survives has been checked by deterministic code, which is the [[Biological
Design|reflex arc]] applied to planning: the safety property cannot live in the
prompt, because an utterance can quote anything.

Two constraints are structural rather than instructed:

- **A plan cannot name an execution agent.** `registry.py` refuses to hold one,
  so the catalogue the model sees never mentions the risk engine, the order
  manager, the broker adapter or the kill switch — and validation rejects the
  family again by name. Voice reaches execution through [[Approval Modes]] and
  the [[Pre-Trade Risk Engine]], never through a planned task.
- **A plan cannot choose a lane.** `dispatch` assigns `Lane.USER`, always. There
  is no field in the plan schema to put `execution` in.

**An empty catalogue costs nothing.** With no agents registered the planner
declines *before* the model call. That is the state until Phase 4, and it means
the planning path can be wired in now for zero tokens per turn.

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

### The tool surface — built 2026-09-03

That last line is the whole of the fail-open path, and until now it was the half
of the design that did not exist: the gateway had a hundred tools and the
orchestrator had no way to call one. `toolbridge.py` is the translation, and
`AnthropicBackend.converse` is the loop that drives it.

| Piece | Job |
|---|---|
| `toolbridge.py` | `ToolSpec` → Anthropic schema; `tool_use` → `Gateway.call` |
| `anthropic_backend.py` `converse` | the tool-use loop, with both circuit breakers |
| `reasoner.py` | picks tools-or-not, owns the persona and the turn budget |

Four properties are structural rather than instructed:

- **The surface is per utterance, not per process.** The router picks eight
  tools for what was actually said. 101 schemas in a prompt is ~20k tokens
  before the trader has spoken, which fails the latency criterion below on the
  first turn. The escape hatch for a bad guess is `find_more_tools`, capped at
  three uses per turn — an uncapped search tool is a loop made of rephrasings.
- **Naming a capability does not grant it.** The bridge resolves only names it
  offered *this turn*; anything else returns an error listing what is actually
  available. A model cannot reach a tool by guessing its name, which is the
  same guarantee `registry.py` gives for agents.
- **The loop has two circuit breakers**, a turn cap and a wall-clock deadline,
  both checked before every request. [[Biological Design]] names a loop with no
  circuit breaker as one of the four ways these systems actually fail, and this
  one sits on the voice path where unbounded is heard as silence.
- **A call always produces a result.** A failed tool comes back with `is_error`
  rather than being dropped — a `tool_use` block with no `tool_result` is both
  an API error and a model that starts inventing numbers.

**Reads only, and not because the prompt says so.** The surface comes from the
gateway's `orchestrator` allow-list, which grants no execution, no broker, no
order. This is the [[Biological Design|afferent/efferent]] split at the tool
layer: the voice has a sensory surface and no motor one, and [[Safety
Invariants]] §1 is unaffected because there is nothing here to route around.

**What is still missing:** the orchestrator answers from tools, but the *planner*
still declines every utterance because no agent is registered. Tools are the
fail-open rung; agents are the rung above it, and Phase 4 builds them.

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
- A typed sentence and the identical spoken one produce the same plan, the same
  panels and the same audit line.
- *"Why is Nvidia down today?"* resolves `NVDA` without a model call.
- A multi-minute request is acknowledged in under 2 s and visible while it runs.
- Ambient conversation for 10 minutes produces zero unwanted actions.
- "Stop" cuts TTS mid-word in under 300 ms.
- A three-step plan dispatches, respects dependencies, and speaks once at the end.
- With the planner deliberately broken, requests still get answered (fail-open).
- Adding 50 MCP tools changes orchestrator latency by less than 10%.

## The prompt must not claim tools the backend cannot call

`converse` — the tool-use loop — exists on the Anthropic backend and on no
other. Every hosted free tier arrives through `OpenAICompatBackend`, which has
none, so its answers are written without a single tool call.

The reasoner used to append `TOOL_RULE` whenever the *router* offered tools,
regardless of whether the backend could call them: *"you have tools, use them
rather than guessing; every number you speak must come from a tool call in this
turn"* — to a model with no way to make one. On Gemini that turned *"when was
Apple founded"* into **"I do not have access to company history tools"**, which
is neither true nor a refusal anybody asked for. It now sends `NO_TOOLS_RULE`
on that path: answer from general knowledge where that is honest, and otherwise
say you cannot reach the data.

## The failure has to name itself

`UNREACHED` — *"I can't reach my reasoning model right now"* — was the sentence
for a missing key, a spent free-tier quota and a vendor having a bad minute.
Three problems, three different fixes, one indistinguishable symptom, and the
reason was already in hand when it was thrown away.

The reasoner keeps `last_error` and the ladder appends it, so the trader hears
*"…right now gemini rate limited (free tier quota)"* and knows to switch tiers
rather than to go looking for a broken install. It rides in `fields["reason"]`
too, so the surface has it as data.

## A question that continues past the symbol is not a lookup

The deterministic table's `company` pattern took the first word after *"what
is"*, so **"what is a stock split"** answered with Agilent (`A`) and **"what is
the market doing"** answered with `MARKET` — both in the confident voice of a
real profile. That is [[Operating Model]] §4's *"nobody knows the ticker"*
failure arrived at by a regex rather than by a model: ambiguity guessed instead
of surfaced. The symbol now has to end the sentence, and anything longer goes to
the orchestrator, which is what those two sentences wanted in the first place.

## Related

[[Operating Model]] · [[Terminal]] · [[Orchestrator Tools]] · [[10-Architecture/Voice Stack]] · [[Task Bus]] · [[Approval Modes]] ·
[[LLM Model Tiers]] · [[Working Memory]] · [[Recall Pathways]] · [[Agent Index]]
