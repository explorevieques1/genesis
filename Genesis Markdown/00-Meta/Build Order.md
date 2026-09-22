---
title: Build Order
tags: [meta, plan]
implemented_by: [tests/daemon/test_entry_point.py]
---

# Build Order

Ten phases. Each ends with something demonstrable. Do not start a phase until the
previous one's exit criteria pass.

Resolve [[Open Questions]] before Phase 1.

> [!important] The order is biological, not arbitrary
> [[Biological Design]] explains *why* the phases fall this way. The spine and
> heartbeat come first (Phase 1) because nothing can live without them. Senses
> come before hands: read-only agents in Phase 4, execution not until Phase 7.
> Within Phase 7 the ledger and the risk engine are built **before** any broker
> code, because **proprioception comes before ambition** — never an actuator
> before the sense that verifies it acted.
>
> When planning work inside a phase, ask the same question the design note asks:
> *which organ is this, and is it reflex or judgement?* Reflexes are cheap,
> deterministic and safe, and most things you were about to give a model to are
> reflexes.

---

## Phase 0 — Decide and scaffold

- Answer [[Open Questions]]: broker, asset class, prop-firm rules, language, vault location.
- Recommended: **Python core** (matches [[Trading Corpus Index|the corpus]]) +
  **Node/Electron dashboard** (matches [[Repo — Gensis Terminal Official]]).
- Repo layout, `pyproject.toml`, config loader ([[Config And Secrets]]), logging
  ([[Observability]]), test + eval harness (pattern: [[Repo — jarvis]] `EVALS.md`).

**Spike — do this first, it takes 30 minutes and gates a whole component:** launch
TradingView Desktop with `--remote-debugging-port=9222` and try to attach over CDP.
If the port opens, [[genesis-tradingview-mcp]] is viable and §11 stands. If not,
the charting surface falls back to lightweight-charts in the [[Dashboard]]. Record
the answer in the MCP note before Phase 3.

**Exit:** `genesis --version` runs; config loads; one passing test; the CDP spike
has a definite yes/no.

---

## Phase 1 — Skeleton

Build the spine with zero intelligence in it.

- [[Daemon And Cadence]] — the forever loop, market calendar, cron
- [[Task Bus]] — priority lanes, persistence, retry
- [[Agent Contract]] — base class: `start / stop / status / run_task`
- [[Memory Fabric]] — SQLite schemas for [[Working Memory]], [[Episodic Log]], [[Trade Ledger]]
- Supervision: crash → backoff restart → degraded state

Reference: [[Repo — jarvis]] daemon, [[Repo — gensis-agents]] `shared/agent-base.js` + `task-queue.js`.

**Exit:** a no-op "echo agent" registers, is scheduled, runs on a cadence, survives a kill -9, and its runs appear in the [[Episodic Log]].

---

## Phase 2 — Orchestrator voice loop

Make it talk. No agents yet.

- [[10-Architecture/Voice Stack]] — mic → VAD → wake word → ElevenLabs Scribe STT
- Intent classification (directed / ambient / follow-up / stop)
- [[Orchestrator]] planner — decompose into a task list
- [[Orchestrator Tools]] — the ~15 fleet-control tools it drives everything with
- ElevenLabs streaming TTS + barge-in + earcons
- [[Working Memory]] conversation buffer

Reference: [[Repo — jarvis]] `listening/`, `reply/planner.py`, `output/`.

**Exit:** you say "Genesis, what time does the market open?" and hear a spoken answer. Ambient conversation is ignored. Saying "stop" cuts speech mid-word.

### Status — 2026-08-30

**Built and verified end-to-end** (synthesised speech in, spoken answer out):
mic capture + ring buffer, VAD, local wake gate, Scribe STT with local fallback,
streaming ElevenLabs TTS with barge-in and a fallback chain, echo filter, the
spinal reflex table, deterministic intent classification, [[Working Memory]],
the trivial-answer path, and `genesis voice`.

The exit criterion passes: the question is answered aloud, two sentences of
ambient conversation produce zero speech and never leave the machine, and
"Genesis, halt" fires the reflex in ~0.1 ms.

**Not built:** nothing that Phase 2 owes. See the closing audit below.
- Barge-in is mitigated, not solved: without acoustic echo cancellation a loud
  speaker in an untreated room can still trigger a false interrupt. Headphones
  or AEC closes it.

### Status — 2026-08-31: planner and tool surface built

The two remaining Phase 2 components are done and tested:

- **[[Orchestrator Tools]]** — all sixteen, as a closed surface a test asserts
  against. `dispatch` submits a whole DAG in one call; results move as ids and
  `spoken_summary` only; `tighten_autonomy` cannot express a loosening;
  `halt()` works with the [[Task Bus]] closed.
- **[[Orchestrator]] planner** — utterance → validated task DAG → dispatch →
  brief await → one spoken sentence, with fail-open on every failure path.
  Slow work is acknowledged and announced when it lands, so voice never hangs
  on a task.

Also built, because the tools needed them: `set_cadence` as a transient
scheduler override that reverts at the next session transition, and a fix to
the bus — its read methods did not take the connection lock, so a cross-thread
read during a write returned half-written rows.

**The planner has nothing to plan for until Phase 4**, and says so cheaply: with
an empty agent catalogue it declines *without calling a model*. Registering the
[[Agent — Screener]] in Phase 4 is what switches planning on; no further change
to the orchestrator is needed.

### Status — 2026-08-31: Phase 2 audit closed

An audit against [[10-Architecture/Voice Stack]], [[Voice UX]], [[Orchestrator]]
and [[Working Memory]] found ten gaps. Seven are now built, three are recorded
decisions rather than omissions.

**The three that were structural:**

1. **`genesis daemon` exists.** There was no entry point — [[Daemon And Cadence]]
   was reachable only from the test suite, so a plan dispatched by voice landed
   in a durable queue with no consumer, which from the operator's side is
   indistinguishable from a hang. `genesis voice` now also hosts a daemon
   in-process by default (`--no-daemon` to defer to a separate one).
2. **Turns are recorded.** `orchestrator/record.py` writes every turn to the
   [[Episodic Log]] — intent, path, latencies, why a plan was declined, and the
   bus trace of any plan it dispatched, so one utterance is one thread. Ambient
   speech is counted, never quoted.
3. **Rolloff and restore are wired.** Turns aging out of [[Working Memory]] are
   preserved rather than dropped, and a restart restores a summary. Continuity
   is manufactured, per [[Biological Design]]; before this it simply was not.

**Also built:** [[Voice UX|earcons]] (all seven, with the distinguishable-blind
criterion asserted on the waveforms), switchable [[Voice UX|verbosity]], the
unprompted-speech policy with a presence signal, and a real 101-utterance
[[Voice Stack|intent eval]] replacing the skipped placeholder.

**Two bugs the audit found**, both fixed: `TaskBus` read methods did not take the
connection lock, so a cross-thread read during a write returned half-written
rows; and `"stop stop stop"` did not fire the stop reflex, because the
bare-command length rule had no case for emphatic repetition — the worst possible
place for that function to be strict.

**Recorded as decisions, not gaps:**

- **STT is batch, not streaming.** The pipeline diagram claimed partials; it
  never had them. The note now says batch in both places.
- **The [[Recall Pathways|recall gate]] is not built.** It routes to three
  memory layers, two of which do not exist. See the note.
- **Barge-in still lacks AEC.** Mitigated, not solved. Headphones close it.

Three bugs the live test caught, all fixed and regression-tested: Whisper
rendering "halt" as "Holt" (the kill phrase silently did not fire); the
follow-up window answering human-to-human conversation; and "what's the stop?"
being read as the stop command.

---

## Phase 3 — MCP gateway

- [[MCP Gateway]] — registry, smart tool selection, persistent per-server runtime
- Untrusted-content fencing
- Per-agent allow-lists
- Wire first servers: market data, Obsidian, filesystem, time
- [[genesis-tradingview-mcp]] — desktop control and the tier-2 data read path
  ([[Market Data Sources]]), if the Phase 0 spike came back yes

Reference: [[Repo — jarvis]] `tools/registry.py`, `tools/selection.py`, `tools/external/mcp_runtime.py`.

**Exit:** 100+ tools registered, the router selects a relevant handful per task, and adding a server does not slow or degrade replies.

### Status — 2026-09-02: the gateway spine is built

Steps 1–3 of [[MCP Gateway Build Plan]] — registry with capability dedup,
enforced per-agent allow-lists, and the persistent per-server runtime with its
one silent reconnect. `src/genesis/mcp/`, 59 tests.

**The fence is built** (step 4), and **six servers are live** (step 7):
obsidian, filesystem, git, time, fetch and a curated slice of tradingview.
Brave web search is wired and waiting on a key. 26 tools registered, 613 tests.

A note can be written into the vault by voice-adjacent code today, fenced web
content cannot escape its wrapper, and an out-of-allow-list call never opens a
session. Alpaca and market-data stay disabled pending [[Market Data Sources]].

Still owed by this phase: the router and `toolSearch`, the cache, and
[[genesis-tradingview-mcp]] for desktop chart control.

### Status — 2026-09-03: Phase 3 complete

Steps 5, 6 and 7 of [[MCP Gateway Build Plan]] are built, and step 8 is built as
far as it honestly can be. **56 tools from 11 servers, 738 tests.**

- **The router and `toolSearch`** — deterministic, per [[Biological Design]]
  §reflex arc. Four ranking rules and the reasoning are in [[MCP Gateway]]
  §smart tool selection; scored by a real eval over a 111-tool catalogue.
- **The cache and rate limiting** — the two stages `gateway.py` had been naming
  in comments. Bar boundaries ask the market calendar rather than dividing by
  86400; stale is served only on the failure path, labelled, and only for 15
  minutes.
- **Five more servers**: `sec-edgar`, `fred`, `arxiv`, `markitdown`, `github`.
  Filings, macro, papers and documents — the four primary sources
  [[Agent — Fundamental]] and [[Agent — News And Catalyst]] need in Phase 4.
- **[[genesis-tradingview-mcp]]**, read and navigation half. The markup half is
  blocked on [[genesis-charting-mcp]], and *proprioception before ambition* says
  that is the right order anyway.

### Correction — 2026-09-03: the market-data deferral was wrong

The paragraph that stood here deferred **everything** that serves prices, on
the grounds that [[Market Data Plane]] gives one server sole ownership of
`market-data.*`. That bottlenecked production for no good reason, and the
reasoning is worth keeping because the mistake is easy to repeat.

**"Market data" was doing too much work as a phrase** — real-time tick,
delayed quotes, closed EOD bars, fundamentals, macro series and screening are
six different things with six different costs, and the deferral only ever
justified the first. Fundamentals are not market data. Neither are dividends,
analyst estimates, an earnings calendar, or a screener.

And [[Market Data Plane]] itself says *"v1 needs no live feed at all"* —
batch-first on closed bars, because Genesis is an analyst and the human is the
trader. **The expensive thing was never in scope, and the free things were
being gated on it.**

The real concern underneath was a capability *contest*: three servers claiming
`market-data.quote` and the router silently picking a defensible-but-wrong one.
That is settled by deciding owners — a judgement call, not an open question —
and the tie-break is cost: needs nothing beats needs a free key beats needs a
paid key. See [[MCP Server Catalog]] §free market data for the ownership table.

**Now wired, all free:** `yfinance` (twenty years of daily bars, no key),
`openbb` (calendars, forward estimates, discovery screens, OECD/IMF macro, no
key), `maverick` (screening and technical analysis, no key), `stock-market`
(Finnhub, free key). `alpha-vantage` turned out to be **superseded** — its
unique value was an earnings calendar at 25 calls a day, and openbb serves the
same calendar free and unmetered.

> [!done] Resolved 2026-09-03 — the criterion is met, curated.
> **103 tools from 14 servers**, and not by registering plumbing. Wiring the
> free market-data surface — openbb, yfinance, maverick, Finnhub — added 49
> curated tools that answer questions nothing else in the catalogue could:
> earnings calendars, screens, forward estimates, twenty years of daily bars.
> Selection was re-verified at that size: **16 of 16** at rank 1.
>
> So the number is no longer in tension with the design. It was reached the way
> it was supposed to be — by the catalogue growing useful, not by it growing.
> The question below is left for the record, because the reasoning is what
> matters if the number is ever in tension again.

> [!question] The exit criterion said "100+ tools registered", and briefly should not have.
> Both numbers below are real, measured on the shipped config:
>
> - **Registered whole, the catalogue reaches 104 tools** and clears the
>   criterion. FRED contributes 33, of which 28 walk its own category/tag/source
>   taxonomy; arxiv contributes 19, of which 12 manage a local paper library.
> - **Curated, it is 56** — and selection is *right*, where at 104 the router
>   found the correct server every time and the correct tool almost never,
>   because a server's keywords are equally true of all of it and 33 tied tools
>   fell to alphabetical order.
>
> A bigger catalogue made the system worse. That is not a surprise, it is
> [[MCP Gateway]] §2 demonstrated on our own config — and it means the number
> was a proxy for *"a catalogue large enough that selection matters"*, which 56
> tools across 11 servers already is.
>
> **Proposed:** replace "100+ tools registered" with the two things it was
> standing in for — *the router is scored by an eval over 100+ tools*, and
> *adding a server does not slow or degrade replies*. Both hold today. Left as
> a question rather than edited in, because changing an exit criterion to match
> what was built is exactly the move that needs a person to agree to it.

---

## Phase 4 — Read-only agents (prove autonomy)

The first real intelligence. Nothing here can spend money.

- [[Agent — Market Analyst]]
- [[Agent — News And Catalyst]]
- [[Agent — Screener]]
- [[Agent — Chart Markup]]
- [[Agent — Idea Synthesizer]]
- [[Obsidian Vault Schema]] writing — ideas and daily research notes

**Exit:** leave it running overnight and through one session. In the morning the
vault has a daily brief and ≥3 ranked ideas with theses, invalidations, and charts —
none of which you asked for.

---

### Status — 2026-09-04: the Charting Family is built

Five agents, not four. `src/genesis/charting/` and
`src/genesis/agents/charting/`.

- **[[Markup Spec]] is a real object** — immutable, lineage-linked, stored in
  SQLite behind triggers that refuse UPDATE and DELETE. `diff_spec` re-renders a
  three-month-old spec against today's bars, which is only possible because the
  spec provably has not changed.
- **[[Charting Engine]]** — deterministic renders (Agg, bundled font, stripped
  metadata), so the same spec and bars produce byte-identical PNGs. That is what
  the vision cache and the journal's re-renderability both rest on, and it is
  asserted by test rather than hoped for.
- **Level computation** with the note's four editorial rules: strength scored
  multiplicatively, confluence merged at 0.25 ATR, proximity in ATR, and the
  always-include set.
- **[[genesis-charting-mcp]]**, all six of its tools plus `render_analytics`.
  Every tool takes a symbol or a spec id and **none takes bars** — a tool
  argument is written by a model, so an argument big enough to hold two hundred
  bars is two hundred rows of context spent before the first level is computed.
- **[[genesis-tradingview-mcp]]'s markup half** — compile, don't click. No price
  becomes a pixel anywhere in the path, and the write is verified by reading the
  chart's own legend back.

> [!warning] Deviation from this phase's own rule, taken deliberately
> *"Do not add agents in Phase 4 beyond the five listed."* [[Agent — Data Viz]]
> is a sixth, and it exists because the questions that motivated the work —
> *"bar chart of the top performing sectors"*, *"the fed funds rate over twenty
> years"* — are charting questions with no level to draw. Routed to
> [[Agent — Chart Markup]] they produce a candle chart of a percentage.
>
> The rule's purpose is to prove the loop before widening the fleet, and that
> purpose is untouched: Data Viz reads the same gateway, returns the same result
> shape, and is supervised by the same daemon. The count went up; nothing about
> the loop got less proven.

### Status — 2026-09-06: three of the Research Family are built

[[Agent — Topic Researcher]], [[Agent — Market Analyst]] and
[[Agent — Idea Synthesizer]], over a new [[Research Directory]] —
`src/genesis/research/` and `src/genesis/agents/research/`.

- **The [[Research Directory]] is the substrate**, and it is a store rather than
  a folder: SQLite is the record, `50-Research/` in the vault is the mirror. A
  subject supersedes rather than duplicates, and every note carries sources, a
  half-life and a confidence the type refuses to let a degraded note inflate.
- **A topic note with no sources cannot be constructed.** That is the phase's
  "prove autonomy" criterion applied to research: an agent that can write
  confidently from its own memory has not proven anything.
- **`genesis research` is the parity half** — subject, `--regime`, `--ideas`,
  `--list`, `--show`. Same agents, same directory, same audit line as a
  dispatched task.
- **`genesis serve` now runs the fleet in-process**, so a sentence typed into
  the terminal's command line reaches the same agents a spoken one does. The
  HTTP answer ladder had no Task Bus, so its planning rung was absent; it now
  gets one — Operating Model §3, as wiring rather than intention.

> [!warning] Deviation, taken deliberately
> This phase lists five agents and none of them is a *topic* researcher — the
> five all assume the question is about the market. [[Operating Model]] §4 says
> otherwise ("Gann is a research subject"), and the gap showed the first time
> someone asked for research that had no ticker in it. See
> [[Agent — Topic Researcher]].
>
> Not built, and still the shortest path to this phase's exit criterion:
> [[Agent — Screener]] and [[Agent — News And Catalyst]]. Without the Screener
> the Idea Synthesizer only reasons about symbols a person named, so "≥3 ranked
> ideas none of which you asked for" is not yet reachable.

### Status — 2026-09-04: the Journal Family is built, out of order

Phase 8, built during Phase 4, and the reason is [[Journal Family]]'s own
premise: *a journal that is only ever written is a diary; a journal that is read
back into the decision process is an edge.* The reading-back needs history, and
history only accumulates if something is writing it down — so the store has to
exist **before** the data it will hold, not after.

All six agents plus `src/genesis/journal/` (store, schema, detectors, health,
drift) and `src/genesis/metrics/` (the one implementation of the arithmetic,
`tier: none` per [[Safety Invariants]] §3).

**What is genuinely running today, with no fills and no broker:**

- [[Agent — Watchdog]] — the only thing that notices a silent failure, and the
  reason it is worth having now is that the fleet just tripled.
- The **observation store**, and the loop into it from [[Charting Family]]:
  every scored [[Markup Spec]] writes one row per level, tagged with its
  *derivation*. Which makes *"your anchored-VWAP levels hold 71%, your
  trendlines 38%"* computable today rather than in Phase 8.
- **Hypotheses.** A finding below the 20-observation threshold is recorded
  against a stable key and accrues, instead of being rediscovered and discarded
  every night. This is the mechanism by which the system gets smarter over
  months, and it is worthless if switched on late — the months have to have
  happened.

**What is complete but idle:** [[Agent — Trade Journal]] has no fills;
[[Agent — Performance Analyst]] has no trades to slice; [[Agent — Backtest Vs
Live Drift]] has no backtests and reports which strategies it *cannot* measure
rather than inventing a baseline.

**Phase 8's remaining work** is therefore the [[Knowledge Graph]] and
[[Memory Consolidation]], plus turning these agents on against real fills — not
building them again.

### Status — 2026-09-04: the Market Data Plane is built, and it is not a phase

[[Market Data Plane]] has no phase of its own and should not have one. It is
**infrastructure Phase 4 already needed and Phase 7 cannot exist without**, so
it was built between them rather than added to the numbering.

What landed: `normalize`, `interface`, `budget`, `store` (DuckDB, Decimal,
write-once), `staleness`, `source`, `build`, `reconcile`, and four adapters —
`csv`, `databento`, `yfinance`, `ibkr`. Plus `genesis chart`, `genesis ibkr
check`, `genesis ibkr reconcile`, and the headless gateway in
`deploy/ib-gateway/`. 111 tests.

`StoreBarSource` implements the **existing** `BarSource` Protocol, so the
Charting Family swapped over with no change above the interface — proven by a
test that drives the real level and structure computation through store-backed
bars.

**Two decisions closed and one opened.** [[Open Questions]] §1 reversed to IBKR
and CME futures; §6 resolved — no separate real-time subscription, Databento is
historical-only because IBKR cannot serve backtests. §13 opened and is
**unanswered**: futures symbol identity and roll policy. Until it is answered
the store holds dated contracts only, and refuses a `CONT:` id outright.

**What is built but unproven:** the IBKR path. There are no credentials on the
machine, so every IBKR test runs against a fake client. Connection, contract
qualification against IBKR's real database, delayed-mode CME data, real pacing
behaviour, and the reconciliation number are all untested against a live
gateway. The code is real; the round trip is not yet evidence — and the
distinction matters here more than usual, because the reconciliation number is
what gates promoting IBKR to tier 1, which is the tier
[[Pre-Trade Risk Engine]] will read in Phase 7.

---

## Phase 5 — Backtest agents

- [[genesis-backtest-mcp]] — one call, full result
- [[Agent — Strategy Author]] · [[Agent — Backtest Runner]] · [[Agent — Risk Metrics]] · [[Agent — Optimizer]]
- [[Strategy Schema]] as the contract between them

Reference: vectorbt, `backtesting.py`, freqtrade hyperopt, `empyrical/stats.py` — see [[Trading Corpus Index]].

**Exit:** "Genesis, backtest that idea over five years" returns spoken headline
metrics plus a full tearsheet in the vault, with walk-forward and an out-of-sample holdout.

---

## Phase 6 — Dashboard

Specced in [[UI Stack]] (technology and the degradation ladder), [[Fleet View]] (the
live agent graph) and [[Genesis Core]] (the animated presence). Three internal stages,
in order:

> [!important] UI-0 comes first, and it is mostly deletion — [[UI-0 Build Order]]
> Stages 1–3 below assume a surface a person can already drive. The one that
> exists cannot be: it opens on an unrequested capability report, its 131 tools
> are reachable only through the voice router, a typed sentence that misses the
> deterministic table dies with *"I didn't catch a command in that"*, and the
> orchestrator has **no path to the UI at all**.
>
> That is not a missing feature list, it is the [[Operating Model|parity rule]]
> unmet. Close it before adding panels, or every panel added inherits the same
> shape:
>
> 1. **Land on an empty canvas.** A `home` category with no dock, and the
>    command line as the map ([[Workspaces]]).
> 2. **Unmatched sentence falls through to the orchestrator.** `POST /v1/command`
>    stops at the table today; the analyst is behind it and unreachable.
> 3. **Name → ticker resolution.** *"Nvidia"* → `NVDA`, deterministic, ambiguity
>    surfaced ([[Company Data Model]]).
> 4. **An efferent path from the orchestrator to the dock** — the same
>    `openPanel` the command line calls, with the causing request attached.
> 5. **Panels publish what they are showing**, so a question can read the open
>    workspace instead of re-fetching the world.
>
> Exit: the trader types *"why is Nvidia down today"* on a blank canvas, panels
> open naming the request that opened them, and every tool used is openable by
> hand from the same catalogue.
>
> Six steps, with files, exits and their order justified: **[[UI-0 Build Order]]**.

**UI-1 — instrument and shell.** The six [[Event Schema|fleet telemetry events]] as
OpenTelemetry spans, the collector, the WebSocket bridge, a local trace UI (Phoenix or
Langfuse), and the Tauri shell with the **plain-DOM safety floor** and the kill-switch
hotkey in the Rust host. Nothing visual beyond that floor.

**UI-2 — the surfaces.** [[Dashboard]] panels on Dockview, the [[Widget Catalog]]
widgets ported from [[Repo — Gensis Terminal Official]], and [[Fleet View]] including
trace mode.

**UI-3 — the core.** [[Genesis Core]] at `hero` tier, the Rive sigil at `ambient`, and
the full degradation ladder verified by killing the GPU context.

Order matters and is not aesthetic: the safety floor is built before anything can
obscure it, and the instrumentation is built before the thing that renders it. The
particle system is last because it is the only part the system can run without.

- WebSocket stream off the [[Task Bus]] and [[Event Schema]]

Reference: [[Repo — gensis-agents]] orchestrator, [[Repo — Gensis Terminal Official]] widgets.

**Exit:** the UI-0 exit above holds; you can watch the whole fleet work in real
time without reading a log;
trace mode reconstructs a three-week-old utterance from the [[Episodic Log]]; and
killing the WebGL context loses no safety-critical information.

---

## Phase 7 — Execution (paper only)

The dangerous phase. Build the gate before the gun.

Order of construction is deliberate:
1. [[Trade Ledger]] and [[Agent — Position And PnL Accountant]]
2. [[Risk Envelope]] and [[Pre-Trade Risk Engine]] — **before** any broker code
3. [[Kill Switch]] — standalone process, no LLM in the path
4. [[Agent — Broker Adapter]] (paper keys) and [[Agent — Order Manager]]
5. [[genesis-execution-mcp]] wrapping all of it
6. [[Approval Modes]] — ship in `advisory`, then `confirm`

**Exit:** paper orders fill; every one passed the gate; the ledger reconciles
against the broker; "Genesis, halt" cancels everything in under a second.

> **Progress (2026-09-14).** Steps 1–4 and 6 are built for IBKR paper, out of
> the listed order (the trader asked for manual paper trading first): ledger
> additions, risk engine, kill switch, broker adapter, order manager, approval
> tokens and one-click, plus the `TRD` panel and chart order lines. Exit checks
> met on the paper account: orders fill, every one carries an approval, the
> ledger reconciles, halt verified in 225–300 ms. Still open: the Position And
> PnL Accountant as its own component, genesis-execution-mcp, the voice halt
> trigger, and "Genesis, halt" by voice.

---

## Phase 8 — Journal and learning

- [[Agent — Trade Journal]] — every fill becomes a vault note with entry/exit charts
- [[Agent — Performance Analyst]] · [[Agent — Insight Miner]] · [[Agent — Backtest Vs Live Drift]]
- [[Knowledge Graph]] + [[Memory Consolidation]] nightly job

**Exit:** after two weeks of paper trading, the system tells you something true
about your trading that you did not already know.

---

## Phase 9 — Go live

- [[Paper To Live Promotion]] gate satisfied by exactly one strategy
- Tightest possible [[Risk Envelope]]
- [[Approval Modes|`confirm`]] mode, spoken confirmation required
- Daily reconciliation alerting

**Exit:** one live trade, fully logged, fully auditable from spoken word to fill.

---

## Phase 10 — Autonomy

- [[Approval Modes|`auto-within-limits`]] for setups with proven live edge
- Expand the fleet: [[Agent — Sentiment]], [[Agent — Fundamental]],
  [[Agent — Regime And Correlation]], [[Agent — ML Signal]], [[Agent — Multi Timeframe]]
- [[Agent — Prop Firm Guard]] if trading a funded account

**Exit:** the system trades a proven setup unattended inside its envelope, and
tells you about it afterwards.

---

## What not to do

- Do not build execution before the risk engine.
- Do not go live before [[Paper To Live Promotion]] passes.
- Do not add agents in Phase 4 beyond the five listed — prove the loop first.
- Do not let any agent talk to another agent directly. [[Task Bus]] or memory only.
- Do not ship a capability reachable only by voice. [[Operating Model]] §2 — if a
  person cannot invoke it by hand from the same catalogue, it is not shipped.
- Do not put anything on the landing screen that was not asked for.
