---
title: Agent — Idea Synthesizer
tags: [agent, research, core]
family: research
cadence: market-open, cron, event
tier: large
status: built
implemented_by: [src/genesis/agents/research/idea_synthesizer.py, src/genesis/research/schema.py, tests/research/test_research_family.py]
---

# 💡 Agent — Idea Synthesizer

## Purpose

**The agent that decides.** Everything else in the [[Research Family]] produces
evidence; this one fuses it into ranked, structured, actionable trade ideas — each
with a thesis, an entry zone, an invalidation, a timeframe, and a calibrated
confidence.

This is the agent that makes the system feel autonomous. Left running overnight, it
is why you wake up to ideas you didn't ask for.

## Cadence

- `market-open` every 15 min
- `cron` 07:15 ET — the pre-market idea set (after [[Agent — Market Analyst]] runs)
- `event` on `news.spike`, `scan.hit`, `level.touched`, `regime.changed`
- `on-demand`

## Inputs

Everything the research family produced, plus context:

| Source | Contribution |
|---|---|
| [[Agent — Market Analyst]] | regime — the frame everything is judged in |
| [[Agent — Screener]] | candidates — the raw list |
| [[Agent — News And Catalyst]] | catalysts — the *why now* |
| [[Agent — Sentiment]] | positioning and divergence |
| [[Agent — Fundamental]] | quality bias and hard vetoes |
| [[Agent — Regime And Correlation]] | whether the setup's assumptions hold |
| [[Knowledge Graph]] | which levels historically hold; which setups have live edge |
| `lessons` namespace | [[Agent — Insight Miner]] output — your own past mistakes |
| [[Trade Ledger]] | current exposure — don't propose the sixth correlated long |

That last two rows are what makes this different from a stock screener with a
language model bolted on: **it knows your history and your current book.**

## Outputs

One or more idea records per [[Idea Schema]], written to the vault at
`10-Ideas/YYYY/MM/` and to the [[Knowledge Graph]]. Emits `idea.created`.

Every idea must have:

- **Thesis** — two sentences, plain English, citing its evidence
- **Entry zone** — a range, not a single price
- **Invalidation** — the condition that proves it wrong. *No invalidation, no idea.*
- **Targets** and the resulting R:R
- **Timeframe** — how long the thesis has to work before it's stale
- **Confidence** — 0–1, calibrated (see below)
- **Evidence links** — to the catalyst, the scan hit, the regime record, the [[Markup Spec]]
- **Conflicts** — anything arguing against it, stated explicitly

Then it dispatches `chart.markup` to [[Agent — Chart Markup]] for the top ideas.

## Confidence calibration

Confidence must mean something. It is scored, not vibed:

| Factor | Effect |
|---|---|
| Multiple independent evidence types agree | + |
| Regime supports the setup type | + |
| Setup has positive live edge in [[Agent — Performance Analyst]] stats | + |
| Level has held historically ([[Knowledge Graph]]) | + |
| A `lessons` entry warns against this pattern | −− |
| Fundamental verdict `cautionary` | − |
| Any input was `degraded` | hard cap |
| Fundamental verdict `disqualifying` | idea dropped entirely |
| High-impact scheduled event inside the timeframe | − and flag |

[[Observability]] tracks **outcome by confidence bucket**. If 0.7-confidence ideas
don't outperform 0.4-confidence ideas over time, the scoring is wrong and gets fixed.
That feedback loop is the whole point.

## Tools

`memory.read` (broad) · `memory.write` · `obsidian.write` · `taskbus.dispatch`

Note: it consumes almost no market data directly — it reads what other agents
already gathered. That keeps it cheap despite being large-tier.

## Memory namespace

Read: `shared`, all research namespaces, `lessons`, `ledger` (read-only), `knowledge-graph`
Write: `idea-synthesizer`, `shared`

## System prompt sketch

> You are the Idea Synthesizer. You turn evidence into a small number of high-quality,
> falsifiable trade ideas.
>
> **Rules:**
> 1. Every idea has an invalidation. If you cannot state what would prove it wrong,
>    you do not have an idea — discard it.
> 2. Cite evidence by id. Uncited claims are not permitted.
> 3. State the strongest argument **against** each idea in the `conflicts` field.
>    An idea with no counter-argument means you didn't look.
> 4. Respect vetoes: `disqualifying` fundamentals, and regime conflicts.
> 5. Check the existing book. Do not propose a position that duplicates existing
>    exposure or breaches concentration.
> 6. Check `lessons`. If the user has repeatedly lost money on this pattern, say so
>    in the idea and lower confidence.
> 7. **Fewer, better.** Three good ideas beat fifteen. If the evidence is thin,
>    return nothing — "no setup today" is a valid and valuable output.
> 8. You propose. You never place orders.

## Acceptance criteria

- Zero ideas produced without an invalidation condition.
- On a quiet, evidence-thin day the output is empty rather than padded.
- An idea that duplicates existing exposure is either not produced or explicitly
  flagged as an add.
- Confidence is calibrated: over a 100-idea sample, higher buckets show better
  outcomes. If not, it's a bug.
- Overnight unattended run produces ≥3 ideas with full evidence chains
  ([[Build Order]] Phase 4 exit criterion).

## Implementation notes — the built subset

**Every idea still requires an invalidation**, and that is enforced by the type
rather than by the prompt: `Idea` refuses to construct without one, so a model
that forgets produces a dropped idea and a stated caveat, never a hope with an
idea's frontmatter.

What is deliberately absent from the first build:

- **No `entry_zone`, `targets`, `rr` or `suggested_risk_pct`.** Those are prices,
  and prices that decide a trade are not a language model's output. Sizing belongs
  to the [[Pre-Trade Risk Engine]], which does not exist — [[Safety Invariants]]
  §1 and §3.
- **Two confidence factors are missing**, not approximated: historical setup edge
  and level hold rate. Both need data the system has not accumulated. A factor
  invented to fill a row is how a calibrated number stops being calibrated. The
  factors that *are* computed ship with every idea in `confidence_factors`,
  including the ones that scored zero.
- **It does not dispatch `chart.markup`.** That needs a [[Task Bus]] handle this
  agent is not given, and [[Agent Contract]] rule 1 forbids calling the charting
  agents directly. Until the handle exists, the human dispatches it.
- **Citations are verified against the evidence it was handed.** A cited note id
  that does not exist drops the idea — a hallucinated citation is worse than none,
  because it looks checkable and is not.

## Related

[[Idea Schema]] · [[Agent — Chart Markup]] · [[Agent — Insight Miner]] ·
[[Agent — Strategy Author]] · [[Research Family]] · [[Knowledge Graph]]
