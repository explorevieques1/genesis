# Seed prompt — Automation: the workflow builder (`WB`) + step runtime

Paste into a fresh Claude Code session in VS Code, opened at
`~/Projects/Genesis Agent/`. **Start in plan mode (shift+tab twice).**

---

You are designing and then building the Automation surface for Genesis: a node
canvas where I compose workflows — run a process, check data integrity, gather
data, refresh a module on a daily cadence — and the daemon runs them. Think n8n,
shaped by Genesis's constraints rather than n8n's.

## Read exactly these, in this order, and stop

1. `Genesis Markdown/60-UI/Automation.md` — the spec, and its four open
   questions. This note currently says the builder must NOT be built until
   questions 1–3 are answered. Answering them is the first half of this job.
2. `Genesis Markdown/10-Architecture/Daemon And Cadence.md`
3. `Genesis Markdown/50-Risk/Safety Invariants.md` — invariant #1 in particular
4. `Genesis Markdown/10-Architecture/MCP Gateway.md` — allow-lists and the fence
5. `Genesis Markdown/90-Graph/Modules/Module WB — Workflow builder.md` and
   `Module CD — Running cadences.md`
6. `Genesis Markdown/60-UI/Workspaces.md` — where the `automation` home page lives

Then read the code that already does this work — do not re-derive it:

- `src/genesis/daemon/scheduler.py` and `src/genesis/daemon/daemon.py`
- `src/genesis/agents/base.py` — `Cadence`, `AgentDeclaration`
- `src/genesis/server/capabilities.py:271` — the `automation.workflows` probe
  already exists and already points at `genesis.automation.workflow`. That
  import path is the contract; making that probe return true is the exit.
- `src/genesis/server/canvas_routes.py` — the house pattern for a surface that
  writes: afferent/efferent split, small single-fact writes, store from config
- `ui/src/components/graph/ForceGraph.tsx` and one existing panel under
  `ui/src/workspace/panels/`

## The constraint that decides the design

**There is exactly one scheduler.** `Automation.md` is explicit: a workflow
engine is not greenfield, it is a second way to author what
`AgentDeclaration.cadence` already expresses. A saved workflow must compile to
`Cadence` objects and register into the existing `Scheduler`. If your plan
contains a second run loop, a second cron parser, or a second answer to "what
happens at 16:30", it is the wrong plan — say so and restart it.

Corollaries, all structural rather than documented:

- **No order path.** The automation module imports no execution code at all, the
  way `canvas_routes.py` imports none. Not a rule in a docstring — an import
  graph that makes `propose_order` unreachable from a workflow step. Safety
  Invariants #1.
- **Steps are drawn from a capability set, never from "any MCP tool".** A
  workflow that can compose arbitrary tool calls routes around the gateway's
  allow-lists. Resolve `Automation.md` Q2 concretely: which set, whose
  allow-list, enforced where.
- **A workflow is data; a cadence is code in a diff.** Q1 is an audit question,
  not a storage question. Whatever you propose must answer: who changed this
  workflow, when, and can I see the diff.
- **Q4 — editing a running workflow.** Version, or refuse. Pick one and defend
  it in two lines.

## Be lazy about the runtime

The laziest thing that works is very likely: a workflow is an ordered list of
typed steps (a graph the UI draws, a list the runtime executes), stored as
JSON/YAML, compiled to `Cadence`, executed by the daemon that already exists.
Justify anything beyond that before you build it. Specifically do **not** add:
a DAG execution engine, a new database if an existing store fits, a retry
framework, a plugin system, a new graph library (`@xyflow/react` is already a
dependency — note in the spec that `Nodes.md` reserved React Flow for Fleet
View and that this is the second sanctioned consumer), or an expression
language. Branching and fan-out are speculative until I ask for them; linear
steps with a condition step covers the four cases below.

The four step kinds I actually want, and nothing else in v1:

| Step | Does |
|---|---|
| gather | pull data through an existing tool/adapter into a store |
| check | assert something about data already stored; fail loudly |
| refresh | re-run a module's build/index step (e.g. the vault map, a cache) |
| run | dispatch an existing agent or command that already exists today |

## Deliverables from plan mode, before any code

1. A rewrite of `Genesis Markdown/60-UI/Automation.md` that answers Q1–Q4 —
   as a **proposal marked for my ratification**, not as settled fact. Anything
   you cannot answer from the vault goes to `00-Meta/Open Questions.md` with the
   options and your recommendation. Do not guess design; that is my call.
2. The step schema, as it will live in `70-Schemas/`.
3. The compile path: workflow JSON → `Cadence` → `Scheduler.register`, named
   file by file, with what changes in `daemon.py`.
4. The file list you will touch, with the new module rooted at
   `src/genesis/automation/`.
5. Where this sits against `00-Meta/Build Order.md`. Be honest: Automation is a
   Phase 6 surface and the repo is mid-Phase 4 with the Research Family and the
   watchlist unbuilt. Tell me what this delays. I may run it as a side track
   anyway, but I want the cost stated, not smoothed over.

**Stop there and wait for me.** Do not write code until I approve the plan and
ratify the answers to Q1–Q4.

## House rules

- Spec-pointer header comment on every new file (`# Spec: Genesis Markdown/...`).
- Spec and code change in the same commit; if a note and the code disagree,
  fix the note first.
- Run `build_vault_map.py` after touching the vault.
- `Decimal` for money, never float.
- Fail honestly: a capability that is not built reports `available: false` with
  the spec note that describes it — never an empty success.
- One runnable check per piece of non-trivial logic, in the existing test style
  under `tests/`. Scheduler tests drive time as an argument; do the same.
- Never the word "jarvis" in Genesis code or docs.

## Exit criteria

- `automation.workflows` probes **true** and the Automation page stops reporting
  itself unbuilt.
- A workflow authored in the canvas fires from the daemon's existing scheduler,
  and `CD` (running cadences) shows it beside the eleven declared cadences with
  no visual or structural distinction between them.
- A test proves a workflow step cannot reach an order path — by import graph,
  not by assertion on a string.
- Deleting a workflow removes its registration; a daemon restart does not
  resurrect it or double-fire it.
