---
title: Agent — Multi Timeframe
tags: [agent, charting]
family: charting
cadence: on-demand
tier: vision
status: spec
implemented_by: []
---

# 🔭 Agent — Multi Timeframe

## Purpose

Same symbol, several timeframes, one composite image, one **alignment score**. The
question it answers: *does the higher timeframe agree with the setup I'm about to take?*

Most bad trades are timeframe conflicts — a long entry on the 5-minute against a
daily downtrend. This agent makes that conflict impossible to miss.

## Cadence

- `on-demand`
- `event` — chained automatically for any idea above a confidence threshold, before
  it reaches the [[Dashboard]] idea board

## Inputs

- Symbol and a timeframe ladder (default: 1M, 1W, 1D, 1H, 15m — configurable per instrument)
- A [[Markup Spec]] per timeframe from [[Agent — Chart Markup]]
- Structure reads per timeframe from [[Agent — Pattern Recognition]]
- The proposed trade direction, if there is one

## Outputs

1. **Composite render** — one image: higher timeframes small on the left, the trading
   timeframe large on the right, shared symbol header, consistent theme
2. **Alignment record**:

```yaml
symbol: NVDA
proposed_direction: long
ladder:
  - { tf: 1M,  trend: up,    structure: HH-HL,  agrees: true }
  - { tf: 1W,  trend: up,    structure: HH-HL,  agrees: true }
  - { tf: 1D,  trend: up,    structure: HH-HL,  agrees: true }
  - { tf: 1H,  trend: range, structure: range,  agrees: neutral }
  - { tf: 15m, trend: up,    structure: HH-HL,  agrees: true }
alignment_score: 0.85       # weighted toward higher timeframes
verdict: aligned            # aligned | mixed | conflicted
key_conflict: null
nearest_htf_level:
  price: 128.40
  tf: 1W
  type: resistance
  distance_atr: 2.3
why: "weekly and daily both trending up; hourly consolidating inside the trend — a pause, not a reversal"
```

`nearest_htf_level` is quietly one of the most useful fields in the system: a long
entered 0.3 ATR below weekly resistance is a bad trade no matter how good the
5-minute chart looks. [[Agent — Idea Synthesizer]] penalizes it.

## Alignment scoring

Weighted by timeframe, higher = heavier. A conflict on the weekly matters far more
than a conflict on the 15-minute.

| Verdict | Condition | Downstream effect |
|---|---|---|
| `aligned` | score ≥ 0.7 | confidence bonus |
| `mixed` | 0.4 – 0.7 | neutral, note it |
| `conflicted` | < 0.4 | **confidence penalty and an explicit warning in the idea** |

A `conflicted` verdict on a high-confidence idea should be spoken aloud, not buried:
"Setup's clean on the daily, but you'd be long into weekly resistance two ATR away."

## Tools

`genesis-charting.render_composite` · `market-data.ohlcv` · vision model ·
`memory.read` · `memory.write`

## Memory namespace

Read: `shared`, `chart-markup`, `pattern-recognition`
Write: `multi-timeframe`

## System prompt sketch

> You are the Multi Timeframe agent. You judge whether timeframes agree.
>
> Higher timeframes dominate. A conflict on the weekly outweighs three agreeing
> intraday charts — say so plainly.
>
> Always report `nearest_htf_level` in ATR distance, not percent. "2.3 ATR below
> weekly resistance" is actionable; "5% below resistance" is not.
>
> Your job is often to be the one that says no. A `conflicted` verdict on an
> otherwise attractive setup is your most valuable output. Do not soften it.

## Acceptance criteria

- Composite render is legible for all five timeframes at the fixed output size.
- A deliberately conflicted test case (daily up, weekly down) scores <0.4 and
  produces an explicit warning.
- `nearest_htf_level` is always populated when higher-timeframe data exists.
- Runs in under 15 s including renders.

## Related

[[Agent — Chart Markup]] · [[Agent — Pattern Recognition]] ·
[[Agent — Idea Synthesizer]] · [[Charting Engine]] · [[Charting Family]]
