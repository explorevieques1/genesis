---
title: Fleet View
tags: [ui]
status: building
implemented_by: [ui/src/views/BodyMap.tsx, ui/src/graph/useFleetGraph.ts, ui/src/graph/layout.ts, ui/src/graph/nodes/AgentNode.tsx, ui/src/graph/edges/FleetEdges.tsx, ui/src/views/TraceView.tsx, ui/src/types/fleet.ts, ui/src/store/useGenesis.ts]
---

# 🕸️ Fleet View

The live graph of the fleet: which agents are running, what they are working on,
and how information is moving toward the [[Orchestrator]].

[[Dashboard]]'s **agent grid** answers *is everything healthy?* — a static roster,
readable in one glance. The fleet view answers a different question: *what is
happening right now, and because of what?* Both exist. The grid is the instrument
panel; this is the view out of the window.

## The correction that shapes everything below

> [!important] Agents do not talk to each other
> [[Build Order]] §What not to do: *"Do not let any agent talk to another agent
> directly. [[Task Bus]] or memory only."* So there is no such thing as an
> agent-to-agent message to draw, and a viz that implies one is lying about the
> architecture.

Every edge in this graph is therefore one of exactly three real things:

| Edge | What it is | Drawn as |
|---|---|---|
| **Lineage** | a task spawned a child task on the [[Task Bus]] | solid, directional, animated in the direction of causation |
| **Memory** | one agent wrote what another read ([[Memory Fabric]]) | dashed, drawn only on read, fading — the write may be hours old |
| **Event** | a published [[Event Schema]] event a subscriber acted on | dotted, fanning from publisher to each subscriber that took a task from it |

Three edge classes, three visual weights, no ambiguity about which is which. The
distinction is not decorative — it is how the operator sees whether the fleet is
coordinating through the bus (intended) or through memory side-effects (usually the
bug you are hunting).

### The structure skeleton — added when the surface was rebuilt for legibility

The three classes above are *traffic*, and traffic only exists while the daemon
is running and busy. On a quiet morning — or with no daemon at all — the graph
was thirty disconnected boxes, and an operator could not see the system's shape.

So there is a fourth, non-traffic layer: a faint always-on **skeleton** drawn
from the topology the layout already computes — every agent to the
[[Orchestrator]], each MCP surface to its anchor agent, the memory fabric to the
core. One hairline weight, no animation, not selectable, not a legend entry. It
does not contradict *"agents do not talk to each other"*: every line runs to the
orchestrator, an MCP surface, or memory — exactly the paths the architecture
allows. It is wiring, not messages. The `wiring` toggle turns it off for a pure
traffic view.

## Layout

Layered left-to-right, matching [[System Overview]]'s topology so the screen and the
architecture diagram teach the same shape:

```
sources ──▶ MCP gateway ──▶ agent families ──▶ orchestrator ──▶ voice
                                  │
                             memory fabric
```

Layered, not force-directed. `elkjs` layered layout, computed once per topology
change and **cached** — agents keep their position between questions. A graph that
re-solves and wobbles every time a task lands is unreadable, and worse, it destroys
the operator's spatial memory of where the execution family sits.

Family grouping is spatial and fixed. [[Execution Family]] gets its own band with a
visible boundary, per [[Dashboard]]'s rule that anything touching money is
distinguishable at a glance.

### Two layouts, one rule — added when the surface was built

The rule above is the constraint; the arrangement is not. The implementation
carries **two** layouts and the cache rule governs both:

| Mode | Solver | What it is for |
|---|---|---|
| `organism` *(default)* | none — a deterministic radial function | The body map. Genesis at the centre, families as arcs fanning up from it — one arc per family, agents evenly spaced along it at a fixed angular pitch, each family's ring a fixed step outside the last. **Execution is the innermost band**, because it is the one that touches money. |
| `layered` | `elkjs`, layered, left-to-right | The topology above. What you switch to when the question is *where did this come from*. |

`organism` is the default because the first question a voice-first operator asks
of this screen is *is it alive and where is the work*, and a radial map answers
that pre-attentively in a way a left-to-right waterfall does not. The layered
view answers the second question better, so both exist rather than one winning.

It is **synchronous and closed-form** — an agent's position is a function of its
family and its index in the roster, so it cannot wobble, cannot fail to solve,
and is identical in every session. That is a stronger guarantee than the cache
gives `layered`, and it is why the radial one is the fallback when `elkjs` fails
rather than an empty canvas.

The viewport frames the **organism only**: the MCP surface and the memory fabric
are laid out deliberately outside the fit, one pan away. Fitting all of it shrinks
thirty agents past legibility, and a graph you cannot read is not a fleet view.

The centre node is **static** — a bold rectangle labelled `GENESIS` with the
in-flight count, nothing more. The animated [[Genesis Core]] is *not* drawn here:
running its particle canvas inside React Flow churned the whole graph, and the
300px node overlapped the inner band. The animated presence belongs on Home,
where it has a job; here, "Genesis at the centre" is a node like any other.
An earlier radial layout staggered agents across two sub-radii per band to fit
176px labels into a tight arc — that read as uneven and still overlapped at seven
agents. One arc, one row, a fixed angular pitch: even spacing and no collision
are now a property of the function, checked in dev by `warnOnOverlap`.

## Nodes

One node per agent, rendered as a React component so it can carry live detail:

- Agent id and family colour
- State: `idle` · `working` · `blocked` · `degraded` · `down` (same vocabulary as
  the [[Dashboard]] agent grid — one state machine, two renderings)
- Current task type (`verb.noun`) and elapsed time
- Today's cost, and `tier` from [[LLM Model Tiers]]
- A `tier: none` badge. **Reflexes look different from judgement.** Per
  [[Biological Design]], a spinal component is not a lesser agent, and the operator
  should be able to see at a glance which parts of the fleet cannot hallucinate

Node visual weight tracks activity, not importance. An idle agent recedes; a working
one is lit. With thirty agents the screen must answer "where is the work" pre-attentively.

### Activity phase is derived, not a sixth state — added when the surface was built

An operator wants to see more than `working`: is it *reading*, *thinking*,
*acting*, or *checking that the act landed*? Those are genuinely different organs
doing genuinely different things ([[Biological Design]]), and the difference is
worth showing.

It is **not** a new agent state. The state vocabulary stays the daemon's five
(`AgentState` in `src/genesis/agents/base.py`), and the UI derives a *phase* from
the task verb in flight:

| Phase | Derived from | Reads as |
|---|---|---|
| `perceiving` | `read` `scan` `watch` `fetch` `arm` `recall` | afferent — cheap, safe, retryable |
| `thinking` | anything else, on a component with a model tier | the LLM organ |
| `acting` | `write` `place` `cancel` `modify` `create` `render` | efferent — authorised, ordered, audited |
| `verifying` | `check` `verify` `reconcile` `compare` | proprioception |

Two consequences worth stating, because both are load-bearing:

- A `tier: none` component **never renders as `thinking`.** It computes; showing
  it deliberating would be the UI asserting a model sits in a path the
  architecture forbids one in.
- Each phase has a distinct **glyph**, not only a colour, so the vocabulary
  survives greyscale and a red-green deficiency — the same rule
  [[Genesis Core]] sets for its five states.

Inventing a sixth *state* here would have put the UI's vocabulary out of step
with the daemon's and the note's, which is spec drift by another name.

## Edges in motion

The thing that makes it a fleet view rather than a diagram: when you ask Genesis
something, **a token travels the edge**.

- One particle per task, released at dispatch, arriving at completion. Travel time
  is the real task duration, so a slow agent is visibly slow — the edge stays
  occupied. This is a latency display disguised as an animation
- Edge intensity tracks tasks in flight, not cumulative volume
- A `blocked` or failed task drops its particle at the point of failure and leaves a
  marker there until acknowledged. **Failures do not simply stop animating** — a
  silent absence is the one thing this view must never render

## Trace mode

The centrepiece, and the reason [[Observability]] §Tracing already stores what this
needs. Select any utterance in the [[Dashboard]] transcript — or say *"show me what
you just did"* — and the graph filters to a single `trace_id`.

Everything outside the trace dims. What remains is the causal chain from the words
you said to every task, tool call, memory write and event that descended from them,
replayable on a scrub bar at real speed or compressed.

This is the same data [[Episodic Log]] holds permanently, so trace mode works on a
question from three weeks ago exactly as it works on the live one. Live is just the
trace whose end has not been written yet.

## Events

The fleet view needs task lifecycle events that [[Event Schema]] does not yet
enumerate. Added there under **System health**, in one commit with this note:

| Event | Data | Priority |
|---|---|---|
| `task.dispatched` | task id, parent task id, agent, task type | low |
| `task.started` | task id, agent | low |
| `task.completed` | task id, agent, wall_ms, cost | low |
| `task.failed` | task id, agent, failure class (`transient`/`degraded`/`fatal`) | normal |
| `agent.state_changed` | agent, from, to, reason | normal |
| `memory.read` | agent, namespace, written_by, age_ms | low |

`parent_task_id` is what makes lineage edges drawable at all; without it the graph
can show activity but not causation, which is half the value.

All six are `speak: false` and ride the **low-priority lane**. Fleet telemetry must
never contend with an `order.filled` ([[Task Bus]] lanes). If the low lane is shed
under load, the fleet view degrades and the trading path does not — the correct
trade, made explicitly.

## Instrument once, render twice

Emit these as **OpenTelemetry spans** following the GenAI semantic conventions, not
as a bespoke UI feed. One span per task; `parent_span_id` carries lineage; span
links carry the memory and event edges; `trace_id` is the one already defined in
[[Observability]].

A collector then fans the same stream to two consumers:

- **[[Fleet View]]**, over the [[Dashboard]] socket
- **A local trace UI** — Arize Phoenix or Langfuse, self-hosted, for debugging

The second one is free, and it is the difference between debugging thirty agents in
a purpose-built waterfall and debugging them in your own half-finished graph. Build
the graph for the operator; use the off-the-shelf tool for yourself.

Local-first holds: the collector and the trace UI run on the machine. Nothing about
the fleet leaves it.

## Not a control surface

The fleet view **shows**. Start / stop / restart stay on the [[Dashboard]] agent
grid, over HTTP, with the confirmation and audit line those actions carry
([[UI Stack]] §7).

The reason is specific: this is a canvas with pan, zoom, and thirty small targets.
An accidental drag that stops the [[Pre-Trade Risk Engine]]'s upstream feed is a
class of mistake the surface should be incapable of, not merely unlikely to permit.

## Acceptance criteria

- Thirty agents and their edges hold ≥ 50 fps during a full pre-market brief.
- A node's state reaches the screen within 1 s of the change ([[Dashboard]] parity).
- Node positions are stable across questions; nothing re-lays-out under load.
- Trace mode reconstructs a three-week-old utterance from [[Episodic Log]] alone.
- A failed task leaves a visible marker; nothing fails silently.
- Shedding the low-priority lane degrades this view and nothing else.
- No control action is reachable from this surface.
- Lineage, memory and event edges are distinguishable without the legend.

## Related

[[Dashboard]] · [[UI Stack]] · [[Genesis Core]] · [[Task Bus]] · [[Event Schema]] ·
[[Observability]] · [[Episodic Log]] · [[Agent Contract]] · [[Biological Design]] ·
[[Memory Fabric]] · [[LLM Model Tiers]]
