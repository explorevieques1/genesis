---
title: Automation
tags: [ui, orchestration]
status: building
implemented_by: [src/genesis/automation/, src/genesis/automation/actions.py, src/genesis/automation/catalog.py, src/genesis/automation/templates.py, src/genesis/server/automation_routes.py, tests/automation/, ui/src/workspace/panels/workflow-builder.tsx, ui/src/graph/nodes/StepNode.tsx, ui/src/components/automation/wiring.ts, src/genesis/automation/__init__.py, src/genesis/automation/runner.py, tests/automation/test_routes.py, tests/automation/test_runner.py]
---

# ⚙️ Automation

## Purpose

A surface where a person composes **workflows** — steps wired together that
Genesis runs on a cadence or an event — without writing code. *"Every morning,
pull Tesla news and write me a synopsis"* is the canonical case.

**Building.** Built: store, compile, runner, routes, the `WB` canvas
(§Visual design) and a 125-node library in 17 categories (§Node library);
`automation.workflows` probes true. Not built: alerts spoken by voice (they are
stored and shown on the dashboard), and *"Genesis, set up a workflow…"*.

## What exists instead, and why it matters

Genesis already automates. Eleven agents declare real cadences in
`AgentDeclaration.cadence`, and the daemon runs them:

- `market-open: 30s` — the watchdog, while the market is open
- `market-closed: 86400s` — the insight miner, overnight
- `cron: 07:00, 16:30, 21:00, 23:00` — the digest's four daily passes
- `event: agent.down, agent.degraded` — the watchdog again, reactively

The Automation page renders these, grouped by trigger. They are not a mock of
what a workflow engine would do — they are a running schedule.

That framing is the design constraint. **A workflow engine is not greenfield.**
It is a way to author what `cadence` already expresses, and it must extend that
declaration rather than sit beside it as a second, parallel scheduler. Two
schedulers is two answers to "what is going to happen at 16:30", and the daemon
can only obey one.

---

> [!success] Ratified 2026-09-12
> The operator approved Q1–Q4 as below, plus: alerts via dashboard + voice;
> a chain with a pass/fail branch on checks; Genesis drafts saved disabled
> ([[Open Questions]] §20.1 → (b)).

## The shape: a workflow compiles to an agent

A saved workflow becomes one `AgentDeclaration` and one `WorkflowAgent`,
registered through `Daemon.register` — the same call every built agent goes
through. Nothing else is added to the run path.

| Workflow part | Becomes |
|---|---|
| `id` | declaration id `wf-<id>` |
| `trigger` | `cadence: (trigger,)` — the `Cadence` model, verbatim |
| `gather` step capabilities | `tools:` — bound by the gateway's existing allow-list |
| the step list | `WorkflowAgent.execute`, which walks it in order |
| — | `family: core`, `model_tier: none` |

So the one scheduler fires it, the one supervisor restarts it, the one bus
queues it under `idempotency_key cadence:wf-<id>:<type>`, and `CD` lists it
beside the declared cadences because it *is* a declared cadence. The only
difference is where the declaration came from.

A chain. Every step has one `next`; a `check` also has `on_fail`. No step is
the target of two edges and nothing loops, so the runtime walks a path — no
DAG engine. Fan-out and merge are deferred until a real workflow needs them.

## Step kinds

Five kinds; the fifth, `action`, is how the node library grows without the
schema growing. Full shape in [[Workflow Schema]].

| Kind | Does | Bounded by |
|---|---|---|
| `gather` | calls one read capability through the [[MCP Gateway]], keeps the fenced result as the step's output | the workflow grant (Q2) |
| `check` | asserts a fixed predicate on an earlier step's output; failing it fails the run loudly | a closed predicate set — no expression language |
| `refresh` | runs one named maintenance job (vault map, corpus index) | a closed registry in code |
| `run` | submits `<agent>.run` to the [[Task Bus]] with args | registered, non-execution agents only |
| `action` | runs one built-in node from `automation/actions.py` with typed settings | the node's own declared settings; unknown settings refused at save |

*"Tesla news → synopsis"* is `gather news.search {query: Tesla}` →
`check non_empty` → `run topic-researcher {subject: "Tesla news today"}`,
triggered `cron 07:00`.

## Answers to the open questions

### Q1. Where does a workflow live? — an append-only version log

`<memory_dir>/workflows.db`, one table:
`workflow_versions(workflow_id, version, body, author, at, note)`. A save
appends; nothing is updated in place. Current = highest version. Delete =
a tombstone version. Every run writes one line to the [[Episodic Log]]
(`automation.run.ok` / `automation.run.failed`) and a row to `workflow_runs`.

That answers the audit question directly: *who* is `author` (`operator` or
`orchestrator`), *when* is `at`, and *the diff* is two rows of the same
workflow — the panel renders it. A cadence in code is reviewed before it runs;
a workflow is reviewed after, which is acceptable **only because** Q2 and Q3
keep what a workflow can do inside a boundary that *is* code in a diff.

### Q2. What may a step do? — the workflow grant, enforced twice

`WORKFLOW_GRANT` is a frozen tuple of capability patterns in
`genesis/automation/grant.py`: read namespaces only (`news.*`, `market-data.*`,
`web.search`, `web.read`, `filings.*`, `macro.*`, `research.*`). Widening it is
a code change.

- **At save:** a `gather` whose capability the grant does not match is refused
  with a typed error. The workflow never exists.
- **At run:** the compiled declaration's `tools` are bound by
  `Gateway.grant`, the same `AllowList` every agent gets. A tampered row still
  cannot call outside it.

Not "any MCP tool", and not "whatever the invoking agent holds" — a workflow
has no invoking agent. It holds this grant and nothing more.

### Q3. Can a workflow reach an order path? — no, by import graph

- `genesis.automation` imports nothing under `genesis.execution`,
  `genesis.risk` or the execution MCP server. A test walks the import graph of
  every `genesis.automation` module and fails on any of them — [[Safety
  Invariants]] #1 and #12.
- The grant contains no `genesis-execution.*` pattern, and a test asserts it.
- `run` refuses any agent whose declaration family is `execution`.
- There is no approval step kind, so no workflow can compose "propose" with
  "approve".

### Q4. Editing a running workflow — version

A run reads its version once, at start, and finishes on it. The edit appends
version *n+1* and re-registers; `Scheduler.register` is already idempotent by id
and keeps run history, so the edit does not make it due again. Refusal would
make a `market-open: 30s` workflow effectively uneditable.

## Restart and delete

- **Boot** registers every non-tombstoned workflow from the store. The store is
  the only source, so a deleted workflow cannot come back.
- **Delete** appends the tombstone and calls `Daemon.unregister`.
- **No double-fire.** Cron history is in memory, so any cron agent — the Digest
  included — used to fire again after a same-day restart. Fixed in the daemon,
  not in automation: a cron dispatch records `at` + `fired_on` in its task args,
  and `Daemon.register` seeds `Scheduler.seed_cron` from the bus.
- **Edits and deletes from the UI** are queued with `Daemon.call_soon` and
  applied on the loop's thread under the fleet lock. With no daemon in the
  server's process, the save stands and the reply says `scheduled: false`.

## Parity

Every WB action is a route (`/v1/automation/...`). The orchestrator authors
through the same save route with `author: orchestrator`; the route forces its
drafts disabled, and `/enable` refuses any author but `operator`.
**Not built yet:** the `commands.py` entry that hands *"set up an automation
to…"* to the orchestrator.

## Node library

The palette is served from code (`/v1/automation/catalog`), never kept in the
UI, so a node the canvas offers is a node the runtime runs. Four sources:

| Source | What | Count |
|---|---|---|
| **Tool nodes** (`catalog.py`) | curated read capabilities; each is a `gather` with its capability fixed, and its form is built from the tool's live JSON Schema | 69 |
| **Built-in nodes** (`actions.py`) | deterministic, `tier: none` actions with declared settings | 51 |
| **Classic nodes** | check, vault map, corpus index, call any tool, run any agent | 5 |
| **Processes** | your own `on-demand` workflows, callable as one step | yours |

Categories: market data · signals & alerts · news & sentiment · fundamentals &
analysts · SEC filings · calendars & macro · screeners · technical analysis ·
research & agents · journal & performance · watchlists · logic & flow ·
transform data · output & notify · maintenance · custom & processes.

**Built-in highlights.** Signals compute locally from bars with
`charting/indicators.py` — price above/below, big daily move, RSI/SMA/EMA/ATR/ADX
threshold, moving-average cross, volume spike, range breakout. Gates read the
market calendar — session, weekdays, time window — plus text contains, compare a
field, count, *only if changed since last run*, cooldown, stop, fail. Transforms:
take N, filter, sort, get a field, extract symbols, dedupe, compose text. Agents:
research, summarise, regime, ideas, chart markup, multi-timeframe, data viz,
digest, performance, insights, drift, news brief. News: collect news, recent
headlines ([[News]]). Writes: send alert, write to notebook, add/remove
watchlist symbols, update price history, collect news.

**Rules the library keeps.**

- **Pass/fail nodes.** Any node with `branches` has two exits; its failure is a
  branch, not a failed run.
- **Repeat for each.** A node with an `each` setting can run once per input item
  (at most 50) — *"for every symbol in my watchlist, is RSI < 30?"* The branch
  passes if any item passed, and carries only those that did.
- **`trigger` input.** Any step may read the data the run started with — the
  event that fired it, or the caller's data when the workflow runs as a process.
- **Processes run inline**, under the caller's agent id, at most three deep, and
  never a workflow already on the stack. A workflow that runs a process binds the
  whole read grant, since the process can change after the caller is saved.
- **Templates fill named slots only** — `{count} {symbols} {items} {text} {date}
  {time} {workflow}` and the input's top-level fields. No attribute access, no
  indexing: a regex over bare names, not `str.format`.
- **Judgement nodes declare their tier.** *News brief* runs `news_catalyst.write_brief`
  — the same function the News page's brief button calls — on the large tier.
  A workflow holding one compiles with that `model_tier`, not `none`, so the
  body map never shows a model-using workflow as a reflex. Its output is marked
  `untrusted` (model text derived from articles) and saved to the notebook with
  `output.note` in `replace` mode.
- **Writes are marked.** `writes` nodes wear a badge on the canvas. Alerts land
  in `workflow_alerts` and the [[Episodic Log]] and show under *recent alerts* in
  `CD`; each has an optional cooldown. **Voice delivery is not built.**
- **What a write returns is how it is found again.** `output.note` returns its
  path, `news.brief` its brief id, `journal.observe` its observation id — and
  [[Feed|`FD`]] turns those keys into the way in. A new destination joins the
  feed by returning an id, not by the feed learning about it.
- **`journal.observe`** writes one `Observation` to the journal store — the
  non-trade record the [[Agent — Insight Miner|Insight Miner]] aggregates
  ([[Journal Family]] §Four record types). A workflow that writes a note for a
  person usually writes one of these for the miner: the note holds the words,
  the observation holds the pointer.
- **`news.ideas` is what makes a brief's ideas exist.** A brief ends with
  `trade_ideas` — a bias, symbols, a reason and an invalidation — and until this
  node they lived inside the brief's JSON: readable in a note, invisible to
  everything that ranks, sizes or measures. It promotes them into the *one* idea
  store ([[Agent — Session Plan]]), authored `news-catalyst`, where the plan
  ranks them beside the trader's own and the gate sizes them. Idea Schema is
  applied to a model's output exactly as to a person's: an idea with no
  invalidation, or no symbol, is **dropped and counted**, never patched with a
  guess. A `watch` bias has no side, so it is stored as a finding — nothing that
  sizes will ever see it.
- **`news.ideas` also reads the brief's prose, not only its trade ideas.** A
  brief ends with two or three trades and *mentions a dozen companies*; the
  mentions are where the reading actually happened. `extract` (in
  `news/symbols.py`) resolves them against the tradeable universe — tagged
  symbols first, then `$CASHTAG`s, then company names from the holdings file's
  own `{ticker: name}` map. **Never a model**: Operating Model §4 says nobody
  knows the ticker, and a model asked to extract them returns `MOON` with
  confidence. What it refuses is the point: English words that are tickers
  (`ALL`, `KEY`, `IT`, `NOW`), index names that are also companies (*"Nasdaq
  100 rebalance"* is not a story about NDAQ's shares), anything outside the
  universe, and a company named once in passing.
- **An extracted idea takes its invalidation from the chart.** The story is the
  thesis; the structural stop is what would prove it wrong. That inversion is
  what makes it an idea rather than a headline with a ticker attached — and it
  means a symbol whose chart cannot be read produces *nothing*, because there
  would be no invalidation. A symbol the brief argues both ways on becomes a
  watch item, never a coin toss.
- **`journal.tearsheet` runs the review here; `agent.performance` queues it.**
  Both reach the [[Agent — Performance Analyst|Performance Analyst]] and they are
  not interchangeable. `agent.*` nodes *dispatch*: they hand a task to the bus and
  return the receipt "handed to performance-analyst", so a step chained after one
  receives that sentence and not the work. A weekly review that ended in
  `output.note` therefore wrote a receipt into the notebook — which is why the
  Sunday review existed for weeks and never appeared in anyone's notes. When the
  next step needs the *words*, the node must be synchronous, like `news.brief`.
- **`market.index-movers`** returns both tails of an index in one step — gainers
  *and* losers — because steps take a single input and there is no merge node.
  Membership is the fund's holdings file ([[Index Movers]]), never a model's
  recollection.

## Tool output and untrusted data

Most servers return JSON as text, not MCP structured content, so the runner
parses it — otherwise filter, sort and count would see nothing. A fenced
(untrusted) result keeps its fenced text and is marked `untrusted`: parsed fields
feed deterministic nodes and templates, and are **stripped before anything is
handed to an agent**, which receives the fenced text only ([[MCP Gateway]] §fence).
A tool error inside the fence (`Error calling tool …`) or a `success: false`
payload fails the step rather than passing as data.

Tool nodes can **repeat for each** input item too, filling one named argument
(`each_arg`) — e.g. `filings.recent` once per watchlist symbol, `identifier` from
each. String arguments accept date slots: `{date} {yesterday} {tomorrow}
{week_ago} {week_ahead}`.

## Templates

`automation/templates.py` — code, reviewed in a diff. The `WB` dropdown groups
them by job; choosing one opens an **unsaved, disabled copy** with its own id.
Nothing is scheduled until the operator saves and enables it.

| Job | Templates |
|---|---|
| Pre-market prep | Morning news synopsis · Gap and catalyst scan · Earnings week heads-up · Economic calendar brief |
| Intraday monitoring | Watchlist oversold alert · Price level alert · Big mover watch · Breakout scanner · Headline keyword watch |
| After the close | Daily movers · End-of-day wrap · Insider and filing sweep |
| Overnight & weekly | Data refresh · Weekly review · Housekeeping |
| Reviews | Weekend news review |

Two of these carry a **weekday gate as their first step**, and it is not a
stylistic choice: [[Agent Contract|`Cadence`]] has no weekday field, so a
workflow's `cron` fires every day. *Weekly review* (Sun 10:00) and *Weekend
news review* (Sun 17:00) are daily crons that stop at `logic.days [sun]`.
Anything here that reads as "on Sundays" is a daily trigger plus a gate — a
template with the day only in its description would run seven times a week.
| Reusable processes | Scan a list for setups · Alert and log · Market open gate |

Tool arguments were taken from each server's live schema on 2026-09-13, and
three templates were run live against real tools. What that found is now in the
templates:

- `screen.gainers` needs `provider: yfinance` (no key) and reports
  `percent_change` as a fraction — 5% is `0.05`.
- `calendar.earnings` needs an FMP key; the earnings template uses the built-in
  *Upcoming earnings* node (Yahoo, per ticker) instead.
- `calendar.economic` timed out via FRED-through-OpenBB; the brief uses FRED's own
  `macro.release-calendar` with a `{date}`..`{week_ahead}` window.
- `filings.recent` ignores `days` when given a company, so the sweep enforces a
  *Keep dates in window* step on `filing_date`.

`tests/automation/test_templates.py` holds every template to: an enabled server
for each tool, a built agent for each dispatch, a known process for each call.
That test found the research family missing from `server/fleet.py`
`AGENT_PACKAGES` — the Fleet View and every agent picker had been blind to the
three built research agents. Fixed.

## Visual design

n8n's editor with Obsidian Canvas's spatial feel. `@xyflow/react`, already a
dependency: [[UI Stack]] §5 reserved React Flow for [[Fleet View]];
[[Research Canvas]] was the second sanctioned consumer, this is the third.

- **Toolbar** — workflow picker, name, version · author · when, Enabled toggle,
  Run now, History, Runs, Save.
- **Palette (left)** — Triggers (schedule, market session, event); Steps
  (gather, check, refresh, run); later alert and indicator. Click or drag to add.
- **Canvas** — dotted background, pan/zoom, minimap. A trigger node, then step
  nodes; a check has two source handles, `pass` and `fail`. A connection that
  would fan out, merge or loop is refused with the reason. A node the trigger
  cannot reach is dimmed: *"not connected — won't run"*.
- **Inspector (right)** — the selected node's settings as closed choices (a
  capability dropdown filtered by the grant, agents from the live roster), and
  its output from the last run.
- **Run badges** — each node shows ok / failed / skipped from the latest run.
- **History** — versions with author and time; two selected → a diff; restore
  loads an old body as an unsaved draft, so restoring is itself a new version.
- **Clicking** a palette item appends it to the chain and wires it, taking the
  previous step as its input; **dropping** one places it unwired.
- **Genesis drafts** open with a banner naming the sentence they came from, and
  Enable stays the operator's button.

Layout is saved in the workflow body (`layout`), server-side, never in the
browser — the [[Research Canvas]] rule. The canvas opens empty.

## Related

[[Workflow Schema]] · [[Feed]] · [[Orchestrator]] · [[Daemon And Cadence]] ·
[[Agent Contract]] · [[MCP Gateway]] · [[Safety Invariants]] · [[Workspaces]]
