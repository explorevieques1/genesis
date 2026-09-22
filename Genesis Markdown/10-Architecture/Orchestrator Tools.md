---
title: Orchestrator Tools
tags: [architecture, core]
status: built
implemented_by: [src/genesis/orchestrator/tools.py, src/genesis/orchestrator/runner.py, tests/orchestrator/test_runner.py, tests/orchestrator/test_tools.py]
---

# Orchestrator Tools

The [[Orchestrator]]'s own tool surface — how it drives the fleet.

Everything here is **fleet control**. No market data, no indicators, no charting,
no orders. The orchestrator picks the *agent*; agents pick their own tools through
[[MCP Gateway]].

## The governing constraint

[[Orchestrator]]'s acceptance criteria are wake → first spoken word in under 1.5 s,
and *"adding 50 MCP tools changes orchestrator latency by less than 10%."*

Both hold only if this list stays **small and fixed — sixteen tools.** Every
domain tool added here is one the planner must weigh on every single utterance.
That is how a voice assistant becomes slow, and it is not recoverable by tuning.

> [!warning] The test for whether a tool belongs here
> *Could an agent do this instead?* If yes, it does not belong. The orchestrator
> delegates; it does not fetch.

## Dispatch

| Tool | Signature | Notes |
|---|---|---|
| `dispatch` | `(tasks[]) → plan_id` | Submits a whole **DAG at once**, not one call per task. Fan-out and joins come free. |
| `cancel` | `(plan_id \| task_id, reason)` | Reason propagates — [[Task Bus]] cancels dependents with the parent's reason attached, never silently |
| `await` | `(plan_id, timeout_ms) → partial state` | Blocks *briefly*. On timeout returns what's done so far. Implemented as `await_plan` — `await` is a Python keyword. |

Two things `dispatch` decides itself, never the planner: the **lane is always
`user`**, and the **idempotency key is derived from the plan's content** — so
dispatching an identical plan while the first is in flight adopts the live tasks
instead of duplicating them, while dispatching it again after it finished runs it
again. Asked twice while it runs is one scan; asked again tomorrow is a new scan.

`dispatch` taking a list is the load-bearing choice. A `run_agent()`-per-call API
forces sequential round-trips through the planner and makes parallel work
impossible to express.

## Observe

| Tool | Returns |
|---|---|
| `task_status(ids[])` | States only — no payloads |
| `fleet_status()` | Every agent's `status()` in **one call**, not thirty |
| `queue_depth()` | Lane depths, so it can warn you when `research` is shedding ([[Task Bus]]) |

## Results — pass references, not payloads

| Tool | Returns |
|---|---|
| `result_summary(task_id)` | The agent's own `spoken_summary` — one or two sentences, already number-formatted for [[Voice UX]] |
| `result(task_id, fields[])` | Named fields, projected. Never the whole object. |

This is where multi-agent systems usually rot. If [[Agent — Screener]] returns 40
candidates and the orchestrator holds them in order to hand them to
[[Agent — Idea Synthesizer]], the payload is now in the latency path and the
context budget is gone by the third turn.

**The orchestrator moves ids and summaries. Never rows.** The only payload it
should ever hold is `spoken_summary`, because saying that out loud is its job.

## Fleet control

`start_agent` · `stop_agent` · `restart_agent` · `set_cadence(agent, interval)`

Mostly for [[Agent — Watchdog]] recovery, and for you saying *"stop scanning,
it's noisy."* Cadence changes are transient and revert at the next
[[Daemon And Cadence|market-open transition]] unless written to config.

## Safety

| Tool | Notes |
|---|---|
| `request_approval(proposal_id)` | Routes to [[Approval Modes]] |
| `tighten_autonomy(mode)` | **Tighten only.** [[Safety Invariants]] §9 — loosening autonomy is a [[Dashboard]] action, never by voice, never by an agent. The tool physically cannot express a loosening. |
| `halt()` | Straight to [[Kill Switch]]. **Bypasses the bus** — the bus may be the broken thing. |

`halt()` is the one tool that must work when nothing else does. No LLM in the
path, no queue, no dependency on agent health.

## Escape hatch

`tool_search(query)` — when no agent fits the request, the gateway routes tools
directly and the orchestrator answers on the large tier. This is the planner's
**fail-open** rule ([[Orchestrator]]): never leave the user unanswered.

Pattern: [[Repo — jarvis]] `tools/builtin/tool_search.py`.

## How data actually moves between agents

Three mechanisms, none of which route payloads through the orchestrator:

| # | Mechanism | Where it's defined |
|---|---|---|
| 1 | **`depends_on` DAG** — the bus sequences; intermediate data never surfaces | [[Task Bus]] |
| 2 | **Memory namespaces** — `read: [shared, screener]` on the consumer's declaration. The handoff is a *permission*, not a message. | [[Agent Contract]] |
| 3 | **Result handles** — `markup_spec_id`, not the spec | [[Agent Contract]] result shape |

A worked example — *"find me a long setup in semis and chart it"*:

```
dispatch([
  {id: t1, agent: screener,         type: screen.sector},
  {id: t2, agent: idea-synthesizer, type: idea.synthesize, depends_on: [t1]},
  {id: t3, agent: chart-markup,     type: chart.markup,    depends_on: [t2]},
])
→ await(plan, 2000)  → still running → speak "on it"
→ on plan.done       → result_summary(t3) → speak
```

The orchestrator saw one id and one sentence. The 40 candidates and the markup
spec never entered its context.

## Three behaviours to get right

### Fan-out / fan-in
*"Check semis, energy, and financials"* → three parallel `screen.sector` tasks and
one join. Free if `dispatch` takes a DAG.

### Never block on slow work
A backtest takes minutes. Dispatch → `await` ~2 s → *"running it now, I'll tell you
when it's done"* → speak on the completion event ([[Event Schema]]). **Voice must
never hang on a task.**

### Fail honestly
When a dependency fails, dependents are cancelled with reasons preserved, so the
orchestrator can say *"screener couldn't reach the feed, so there's no chart"*
rather than going quiet. ([[Error Handling And Degradation]],
[[Safety Invariants]] §10)

## Acceptance criteria

- The orchestrator's tool count stays ≤ 16, and the surface is *closed*: a test
  compares the class's public members against a frozen name list, so adding a
  tool fails a test rather than quietly costing latency forever.
  (The tables above list sixteen; an earlier draft of this line said fifteen,
  which never matched them. Sixteen is the real number.)
- A three-step plan dispatches in **one** `dispatch` call.
- Three independent tasks run in parallel, not in sequence.
- No task payload larger than a `spoken_summary` ever enters orchestrator context —
  asserted by logging context size per turn.
- `tighten_autonomy` cannot express a loosening; the attempt fails a type check,
  not a runtime check.
- `halt()` succeeds with the [[Task Bus]] stopped and every LLM endpoint unreachable.
- A failed dependency produces a spoken explanation naming the actual cause.
- A 4-minute backtest never blocks a subsequent voice request.

## Related

[[Orchestrator]] · [[Task Bus]] · [[Agent Contract]] · [[MCP Gateway]] ·
[[Approval Modes]] · [[Safety Invariants]] · [[Kill Switch]] · [[Event Schema]] ·
[[Error Handling And Degradation]] · [[Agent Index]] · [[Repo — jarvis]]
