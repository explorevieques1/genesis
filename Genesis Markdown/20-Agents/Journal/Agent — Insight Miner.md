---
title: Agent — Insight Miner
tags: [agent, journal]
family: journal
cadence: market-closed
tier: large
status: spec
implemented_by: []
---

# ⛏️ Agent — Insight Miner

## Purpose

Find the patterns in *your* behaviour that you cannot see yourself, and write them
as **lessons** that change future decisions.

This is the agent that makes Genesis compound. [[Agent — Performance Analyst]] tells
you what the numbers are; this one tells you what you keep doing.

## Cadence

`market-closed` nightly, with a deeper pass weekly.

## What it mines

| Source | Looking for |
|---|---|
| [[Trade Ledger]] | Sizing patterns, timing patterns, stop behaviour, sequence effects |
| [[Agent — Trade Journal]] notes | Emotional state vs. outcome, plan adherence, stated reasons |
| [[Agent — Idea Synthesizer]] history | Which ideas you take and which you skip — and which you *should* have |
| [[Knowledge Graph]] | Which levels hold, which setups work in which regime |
| [[Markup Spec]] lineage | Do you move your levels to justify a position? |
| [[Agent — Execution Quality]] | Habitual execution mistakes |

## The findings it looks for

Behavioural, not statistical — the analyst already covers statistics.

- **Sequence effects** — "You oversize after two losses. Those trades average −0.6R."
- **Revenge trading** — "Trades entered within 15 minutes of a loss are −0.4R over 22 trades."
- **Stop migration** — "You moved your stop against yourself on 3 of the last 5 losers."
- **Cutting winners** — "Your average winner is 1.2R against a 2.0R average target.
  You exit early on 60% of trades that eventually reach target."
- **Time-of-day decay** — "You lose money after 14:30. Consistently. 31 trades."
- **Selection bias** — "You skipped 4 of your 6 highest-confidence ideas last month.
  They averaged +0.9R. The ones you took averaged +0.1R."
- **Level quality** — "Your anchored-VWAP levels hold 71% of the time. Your fitted
  trendlines hold 38%."
- **Regime blindness** — "You trade the ORB setup in ranging tape. It only works trending."
- **Overconfidence after wins** — "Position size increases 40% after a winning day.
  Performance does not."

## Output — a lesson

Lessons go to the `lessons` namespace, which has **elevated recall priority** across
the whole [[Memory Fabric]], and to `60-Lessons/` in the vault.

```yaml
id: lesson_01J8XY
title: "Oversizing after consecutive losses"
finding: >
  Position size increases an average of 62% on the trade following two consecutive
  losses. Those trades average −0.61R against an overall expectancy of +0.23R.
evidence:
  observations: 34
  period: { from: 2026-03-01, to: 2026-08-29 }
  trades: [t_..., t_..., ...]
  confidence: 0.81
applies_when:
  - consecutive_losses >= 2
recommended_action: >
  Cap size at the normal risk percentage after two consecutive losses. Consider a
  mandatory cooldown.
enforcement: advisory        # advisory | warn | hard_limit
status: active
```

## Enforcement levels — lessons with teeth

A lesson that only lives in a note changes nothing. Each can be escalated:

| Level | Effect |
|---|---|
| `advisory` | Surfaces in [[Agent — Idea Synthesizer]]'s reasoning; lowers confidence on matching ideas |
| `warn` | [[Orchestrator]] speaks the warning before the trade: *"This is the pattern from lesson four — you're up-sizing after two losses."* |
| `hard_limit` | Encoded into the [[Risk Envelope]] as an actual constraint the [[Pre-Trade Risk Engine]] enforces |

Escalation to `hard_limit` requires your explicit approval — the system proposes,
you decide. But once approved, it's a wall, not a reminder. This is how a lesson
stops being something you know and starts being something you do.

## Tools

`memory.read` (broad — ledger, journal, ideas, graph) · `memory.write` ·
`obsidian.write` · `taskbus.publish`

## Memory namespace

Read: everything except raw untrusted content
Write: `lessons` (**the only writer**), `insight-miner`

## System prompt sketch

> You are the Insight Miner. You find behavioural patterns in this trader's actual
> history and state them plainly.
>
> **Be specific and quantified.** "You sometimes oversize" is useless. "Position
> size increases 62% after two consecutive losses, and those trades average −0.61R
> over 34 observations" is actionable.
>
> **Do not soften.** This person asked to be told the truth about their trading. A
> finding that is uncomfortable is more valuable than one that is not.
>
> **Require evidence.** Minimum 20 observations for a lesson, 30 before recommending
> a hard limit. Below that, log it as a hypothesis to watch, not a lesson.
>
> Distinguish correlation from causation. You are mining a small dataset many ways —
> some of what you find is coincidence. State your confidence and say which findings
> you would bet on.
>
> Check existing lessons before writing a new one. Reinforce or supersede; do not duplicate.

## Acceptance criteria

- No lesson written on fewer than 20 observations.
- No `hard_limit` proposal on fewer than 30.
- Every lesson carries linked trade ids as evidence.
- Duplicate findings supersede the earlier lesson rather than accumulating.
- Lessons are actually retrieved by [[Agent — Idea Synthesizer]] — tested end to end
  with a synthetic matching idea.
- On a seeded dataset with a known planted pattern, the pattern is found.

## Related

[[Agent — Performance Analyst]] · [[Agent — Trade Journal]] · [[Agent — Idea Synthesizer]] ·
[[Risk Envelope]] · [[Memory Fabric]] · [[Journal Family]]
