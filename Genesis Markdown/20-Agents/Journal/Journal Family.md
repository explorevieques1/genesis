---
title: Journal Family
tags: [moc, agent, journal]
status: built
implemented_by: [src/genesis/server/journal_routes.py, ui/src/workspace/panels/journal.tsx, src/genesis/journal/store.py, src/genesis/journal/schema.py, src/genesis/journal/bridge.py, src/genesis/agents/journal/fleet.py, tests/journal/test_bridge.py, src/genesis/agents/journal/__init__.py, tests/journal/conftest.py, tests/journal/test_agents.py]
---

# 📓 Journal Family

Six agents that make the system learn — from your trades, from its own predictions,
and from its own health.

| Agent | One line |
|---|---|
| [[Agent — Trade Journal]] | Every fill becomes a note, automatically, with charts |
| [[Agent — Performance Analyst]] | Where the edge is, and where it isn't |
| [[Agent — Insight Miner]] | Patterns in *your* behaviour you can't see yourself |
| [[Agent — Backtest Vs Live Drift]] | Does reality agree with the backtest? |
| [[Agent — Watchdog]] | Is everything actually running? |
| [[Agent — Digest]] | The morning brief and the evening recap |

## The learning loop

```
   trade ──► TRADE JOURNAL ──► vault note (thesis, charts, R, tags)
                   │
                   ▼
        PERFORMANCE ANALYST ──► edge by setup / session / symbol / size
                   │
                   ▼
           INSIGHT MINER ──► lessons  ──┐
                   │                     │
        BACKTEST VS LIVE DRIFT           │  (high recall priority)
                   │                     │
                   └─────────────────────┼──► [[Agent — Idea Synthesizer]]
                                         └──► [[Pre-Trade Risk Engine]] (informs limits)
```

The loop closes when a lesson changes a future decision. A journal that is only ever
written is a diary; a journal that is read back into the decision process is an edge.

That's why `lessons` is a first-class [[Memory Fabric|memory namespace]] with
elevated recall priority — [[Agent — Idea Synthesizer]] is required to check it and
to lower confidence when a proposed idea matches a pattern you've lost money on.

## Automatic, not aspirational

Trade journaling fails for everyone because it's manual work at the worst possible
moment. Genesis writes the note at fill time with the chart, the thesis, the levels,
and the R multiple already filled in. **You add only what a machine can't know** —
what you were thinking, how you felt, whether you followed the plan.

The [[Trade Journal Schema]] separates these deliberately: machine fields are
populated automatically; human fields are prompted for, once, at a calm moment
(after the close, not during the trade).

## Honest, not flattering

These agents report what happened. A weekly review that always finds something
encouraging is worthless.

- If a setup has no edge, [[Agent — Performance Analyst]] says so with the numbers.
- If you're the problem — oversizing, revenge trading, moving stops —
  [[Agent — Insight Miner]] says that too, plainly.
- If a strategy has decayed, [[Agent — Backtest Vs Live Drift]] recommends retiring it.

The prompts for these agents explicitly forbid softening. Encouragement is not the
product; accuracy is.

## The store — what makes it compound

Built 2026-09-04, `src/genesis/journal/`. The family's claim is that a journal
read back into the decision process is an edge, and that claim needs a
*queryable* substrate with four properties. Each is enforced by the database
rather than trusted:

**Machine fields are immutable; human fields are not.** A `BEFORE UPDATE` trigger
rejects any change to a price, an R multiple or a plan-adherence flag, while
leaving the reflective columns writable. The frozen machine record and the
mutable reflection are stored separately and merged on read — so there is never
a moment where a reflection has been recorded and the machine record rewritten
to contain it, which is the state an audit could not distinguish from a number
having been edited.

**`lessons` has exactly one writer.** A `CHECK` constraint, not a convention.

**Findings accumulate.** See below — this is the important one.

**Observations are not trade-shaped.** They arrive from anywhere.

### Four record types

| Type | What it holds |
|---|---|
| `JournalEntry` | One closed trade, per [[Trade Journal Schema]] |
| `Lesson` | A finding with enough evidence to act on. ≥20 observations, enforced by the type |
| `Hypothesis` | A finding *without* enough evidence — **yet** |
| `Observation` | One durable fact worth remembering, whatever produced it |

### Hypotheses: the mechanism that makes this compound

[[Agent — Insight Miner]] may not write a lesson below 20 observations. Without
somewhere to put an eight-observation finding, every nightly pass would
rediscover it, decline to write it, and forget — forever. The system would start
from zero every night.

A `Hypothesis` is keyed on the detector that found it, so the same pattern seen
again **updates one row rather than creating a second**. Its evidence grows night
after night, and on the night it crosses 20 it is promoted to a lesson with the
accumulated evidence and the trail intact.

That is the difference between a system that learns over months and one that
merely reports.

### Observations: why the loop is already running

Trades need Phase 7. Observations do not. [[Agent — Chart Markup]] produces a
scoreable outcome every time a spec is scored, and `journal/bridge.py` writes one
row per level with its **derivation** as the source — `anchored-vwap`,
`sr-cluster`, `trendline`.

Which means [[Charting Family]]'s stated distinctive edge —

> Your anchored-VWAP levels hold 71% of the time. Your fitted trendlines hold 38%.

— is computable **today**, from `outcome_rate()`, and `level_quality` in
`journal/patterns.py` already reports it. Level outcomes, live level fires, idea
outcomes (including the *skipped* ones, which leave no trade and are therefore
invisible to the journal alone) and health incidents all land in the same table
and are all evidence a lesson can later rest on.

**The operator is one of the sources.** A marked range of candles
(`mark.entry`, `mark.exit`, `mark.idea` — [[Agent — Trade Journal]] §Marks) is
an observation like any other, with `source: operator`. It is the only row in
this table a person authors by hand, and the only way an idea that was never
taken becomes evidence.

> [!important] Record it at the time or not at all
> A level's outcome depends on the spec that was active when price reached it.
> Once the symbol is re-marked, the original question is unanswerable. So the
> recording happens at the moment of scoring — which is why the bridge is wired
> before there is anything much to learn.

## Status — 2026-09-04

All six agents built, plus the store, the metrics engine and the detectors.

**What works with no execution and no fills:** the Watchdog (the only thing that
notices a silent failure), the Digest, the observation store, the level-outcome
loop from [[Charting Family]], and the Insight Miner's `level_quality` detector.

**What is waiting on Phase 7:** everything that needs trades — most detectors,
most of [[Agent — Performance Analyst]]'s slices, and [[Agent — Trade Journal]]
itself, which is complete and simply has no fills to record yet.

**What is waiting on Phase 5:** [[Agent — Backtest Vs Live Drift]] has no
backtest expectations to compare against. It reports which live strategies it
*cannot* measure rather than inventing a baseline — and a strategy trading live
with nothing to compare it against is itself a finding.

**Ten behavioural detectors** in `journal/patterns.py`, every one deterministic.
A language model reading a trade history will find patterns whether or not they
are there; the model's job here is to *word* a finding, never to discover one.
Verified against a seeded dataset with a planted pattern, per the note's
acceptance criterion.

**Metrics live in `src/genesis/metrics/`**, outside the family, because
[[Agent — Performance Analyst]] and [[Agent — Backtest Vs Live Drift]] must
agree about what a win rate is. [[Agent — Risk Metrics]] will wrap it in Phase 5
rather than reimplement it. `tier: none`, per [[Safety Invariants]] §3.

## Wiring — 2026-09-14

- **Daemon** (`cli._build_journal_fleet`): the Watchdog gets the daemon's
  supervisor and Task Bus, the Digest gets the episodic log plus the research
  and news stores. Until now the Watchdog was built with neither and probed
  nothing, and its two probes called methods that do not exist.
- **By hand** (Operating Model §1): `JD` Journal desk runs Digest, Performance
  Analyst, Insight Miner, Watchdog and Drift through `POST /v1/journal/run`,
  which submits to the same Task Bus as the planner and workflows. It also shows
  lessons and hypotheses. Trade Journal has no button: it records a fill.
- **Still waiting:** fills (Phase 7, no `TradeLedger` is built) and drift
  expectations (backtest runs store headline stats, not a per-trade R
  distribution).

## Related

[[Agent Index]] · [[Trade Journal Schema]] · [[Obsidian Vault Schema]] ·
[[Memory Fabric]] · [[Knowledge Graph]]
