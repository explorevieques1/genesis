---
title: Agent — Performance Analyst
tags: [agent, journal]
family: journal
cadence: cron, market-closed
tier: large
status: spec
implemented_by: []
---

# 📊 Agent — Performance Analyst

## Purpose

Where is the edge, and where is it not? Slices performance by every dimension that
could matter and reports honestly — including when the answer is "you have no edge here."

## Cadence

- `cron` 18:00 ET — daily tearsheet
- `cron` Sunday 10:00 — **the weekly review**, spoken
- `market-closed` — deeper slices on demand

## Dimensions analysed

Every slice via [[Agent — Risk Metrics]] — one implementation, consistent numbers.

| Dimension | Question |
|---|---|
| By strategy | Which strategies actually make money live? |
| By setup type | ORB vs. mean reversion vs. breakout |
| By symbol / sector | Are you good at semis and bad at energy? |
| By session time | First 30 min vs. midday vs. last hour |
| By day of week | The classic, and often real |
| By hold duration | Is your edge in the first hour or the third day? |
| By position size | **Do bigger positions do worse?** (they usually do) |
| By regime | Which regime does each strategy actually work in? |
| By confidence bucket | **Is the [[Agent — Idea Synthesizer]]'s confidence calibrated?** |
| By plan adherence | Do you make more when you follow the plan? |
| By R multiple distribution | Are you cutting winners and letting losers run? |

The two bold rows are the highest-value analyses in the system. Position-size-vs-
performance catches overconfidence in real time. Confidence calibration is the
feedback loop that makes the whole idea-generation pipeline honest — if 0.7-confidence
ideas don't beat 0.4-confidence ideas, the scoring is broken and needs fixing.

## Output

Daily: a tearsheet at `90-Meta/` — equity curve, drawdown, rolling metrics, monthly
heatmap, R distribution.

Weekly: a spoken review plus a vault note.

```yaml
week: 2026-W35
trades: 14
net_r: 3.2
win_rate: 0.50
expectancy_r: 0.23
best_slice:  { dim: setup, value: orb_breakout, expectancy_r: 0.61, n: 6 }
worst_slice: { dim: session, value: "15:30-16:00", expectancy_r: -0.44, n: 4 }
calibration:
  - { bucket: "0.7-0.8", ideas: 5, taken: 3, avg_r: 0.8 }
  - { bucket: "0.5-0.6", ideas: 9, taken: 4, avg_r: 0.1 }
  verdict: "directionally calibrated, sample too small to confirm"
size_effect: "trades above 1.5x average size averaged −0.3R vs +0.4R below"
adherence_effect: "plan-followed trades +0.51R; deviated trades −0.22R"
sample_warnings:
  - "14 trades is not enough to draw conclusions about any single slice"
```

## The sample-size discipline

The most common way performance analysis misleads is by slicing a small sample into
smaller ones until something looks significant.

Rules, enforced:
- Every slice reports `n`.
- Below a threshold (default 20 trades), the slice is reported as **indicative, not
  conclusive**, and the note says so.
- No recommendation to change behaviour is made on fewer than 30 observations.
- The weekly review is allowed — encouraged — to say "not enough data yet."

## Spoken weekly review

Three minutes, structured, honest:

1. The number: net R, expectancy, and how it compares to the trailing 8 weeks
2. What worked, with the sample size stated out loud
3. What didn't, stated plainly
4. One thing to change — **at most one**, and only if the sample supports it
5. Open questions the data can't yet answer

## Tools

`empyrical.metrics` (via [[Agent — Risk Metrics]]) · `pyfolio.tearsheet` ·
`memory.read` (ledger, journal, ideas) · `obsidian.write` · `memory.write`

## Memory namespace

Read: `ledger`, `trade-journal`, `idea-synthesizer`, `execution-quality`, `regime-correlation`
Write: `performance-analyst`, `shared`

## System prompt sketch

> You are the Performance Analyst. You report what the numbers say. You do not
> encourage, soften, or find silver linings.
>
> **Always state the sample size in the same breath as the finding.** "ORB has an
> expectancy of 0.61R over six trades" — the six is part of the sentence, not a
> footnote.
>
> Never recommend a change on fewer than 30 observations. "Not enough data yet" is a
> complete and valuable answer, and you should give it often.
>
> Correlation is not causation, and you are slicing a small sample many ways. Some
> of what you find is noise. Say which findings you'd bet on and which you wouldn't.
>
> If the honest summary of the week is "you lost money and nothing in the data
> explains why", say exactly that.

## Acceptance criteria

- Every slice reports `n`; every under-threshold slice is labelled indicative.
- No behavioural recommendation on <30 observations, enforced by test.
- Confidence calibration is computed weekly and tracked over time.
- Spoken review stays under 3 minutes.
- On a losing week, the review says so directly in the first sentence.

## Related

[[Agent — Risk Metrics]] · [[Agent — Insight Miner]] · [[Agent — Trade Journal]] ·
[[Agent — Backtest Vs Live Drift]] · [[Agent — Idea Synthesizer]] · [[Journal Family]]
