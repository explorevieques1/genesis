---
title: Agent — Trade Journal
tags: [agent, journal]
family: journal
cadence: event
tier: small
status: built
implemented_by: [src/genesis/agents/journal/trade_journal.py, src/genesis/journal/bridge.py, src/genesis/server/journal_routes.py, ui/src/workspace/panels/charting.tsx, ui/src/workspace/panels/journal.tsx, tests/journal/test_agents.py]
---

# 📝 Agent — Trade Journal

## Purpose

Every fill becomes a vault note, automatically, with the chart, the thesis, and the
numbers already filled in. You add only what a machine cannot know.

Manual journaling fails because it asks for effort at the worst moment. This agent
removes the effort and leaves only the reflection.

## Cadence

`event` — on entry fill (create the note), on each partial (update), on exit
(complete it), and at 16:15 ET (prompt for the human fields).

## What it captures automatically

| At entry | At exit |
|---|---|
| Symbol, side, size, price, time | Exit price, time, reason (target / stop / trail / time / manual) |
| The [[Idea Schema\|idea]] that produced it, with its full thesis and evidence | R multiple achieved |
| The [[Markup Spec]] and rendered chart **at entry** | A fresh chart **at exit**, same spec re-rendered |
| Stop, target, planned R:R | MAE and MFE in R |
| Strategy and setup tags | Slippage from [[Agent — Execution Quality]] |
| Regime and session context | Duration, bars held |
| Portfolio heat at the time of entry | Fees |
| The `trace_id` back to the utterance or event that started it | Whether the plan was followed |

That last row on the left is what makes the journal auditable: from a trade you can
walk back to the idea, to the research, to the words you said.

## What it asks you for

Once, at a calm moment after the close — never during the trade:

- What were you thinking when you entered?
- How did you feel while holding it? (rated, for [[Agent — Insight Miner]])
- Did you follow the plan? If not, what did you change and why?
- What would you do differently?

Asked by voice, answered by voice, transcribed into the note. Skippable — a partial
journal entry is better than none, and nagging produces resentment, not insight.

## Marks — the half a fill cannot see

Built 2026-09-15. Everything above is **fill-driven**: no trade, no entry. But a
trader reads bars long before they take one, and an idea they *skipped* leaves
no fill and is invisible to this agent forever.

A **mark** is a range of candles selected on a chart — press-drag a zone on `CH`
(a saved [[Candle Ranges|candle range]] opens as the series `CR:<id>`, so it
works there too), select it, press **journal**, and say what it was: an
**entry**, an **exit**, or an **idea**.

It lands in two places, by context, and the split is the design:

| Situation | Record |
|---|---|
| Always | An `Observation` — `mark.entry` / `mark.exit` / `mark.idea`, `subject` the ticker, `source: operator`, `detail` carrying symbol, timeframe, the window in epoch seconds, the series, the drawing id and the note. Not trade-shaped, so an idea never taken still leaves evidence [[Agent — Insight Miner]] can aggregate |
| The mark names a trade | Also appended to that entry's **human half** (`notes`, and a `mark:<id>` tag) |

**A mark can never reach the machine record.** `human_patch` refuses machine
fields and a SQLite trigger refuses the write, so a hand-drawn range cannot
move a price, an R multiple or a plan-adherence flag — the boundary that makes
[[Agent — Performance Analyst]]'s arithmetic trustworthy holds unchanged.

**Doors:** `POST /v1/journal/mark` is the door; the chart's *journal* button
posts the same body a person can post by hand, and `GET /v1/journal/marks`
reads them back in `JM`. Written by `journal/bridge.py:record_mark`, not by
this agent — it is the operator's hand, not an agent's judgement.

## Plan adherence — computed, not asked

The agent compares plan to execution and states the deviation as fact:

```yaml
plan_adherence:
  entry_in_zone: true
  size_as_planned: false      # took 120, plan said 192 — risk engine resized
  stop_as_planned: true
  stop_moved: false
  exit_as_planned: false      # exited at 1.2R, target was 2.0R
  deviations:
    - "Exited early at 1.2R against a 2.0R target — no stated reason"
```

`stop_moved` in the wrong direction is the single most predictive field for
[[Agent — Insight Miner]]. It's computed from the [[Trade Ledger]], not
self-reported, because self-reporting on this particular behaviour is unreliable.

## Output

A note per [[Trade Journal Schema]] at `30-Journal/YYYY/MM/`, with:

- Frontmatter for every machine field (queryable by Dataview)
- Entry and exit charts embedded
- The thesis, copied verbatim from the idea — so you can read what you *believed*,
  not what you remember believing
- Human reflection section
- Links: to the idea, the strategy, the markup specs, the lessons it later informs

## Tools

`memory.read` (ledger, ideas, specs) · `genesis-charting.render` · `obsidian.write` ·
`memory.write`

Small tier ([[LLM Model Tiers]]) — this is formatting and transcription, not reasoning.

## Memory namespace

Read: `ledger`, `idea-synthesizer`, `chart-markup`, `execution-quality`
Write: `trade-journal`, vault `30-Journal/`

## Acceptance criteria

- 100% of fills produce a note. No exceptions, no silent misses.
- Entry chart is rendered from the spec **as it was at entry**, not re-computed later.
- The thesis is copied verbatim, never re-summarized — the point is the original wording.
- Plan adherence is computed from the ledger, never self-reported.
- Prompting happens once, after the close, and is skippable without consequence.
- A note is complete enough to be useful even if you never answer a single prompt.

## Related

[[Trade Journal Schema]] · [[Agent — Insight Miner]] · [[Agent — Performance Analyst]] ·
[[Idea Schema]] · [[Obsidian Vault Schema]] · [[Journal Family]]
