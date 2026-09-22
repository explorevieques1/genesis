---
title: Agent — Pattern Recognition
tags: [agent, charting]
family: charting
cadence: on-demand
tier: vision
status: built
implemented_by: [src/genesis/agents/charting/pattern_recognition.py, src/genesis/charting/structure.py, tests/charting/test_structure.py, tests/charting/test_agents.py]
---

# 👁️ Agent — Pattern Recognition

## Purpose

Name the structure. Trend or range, HH-HL or LH-LL, wedge, flag, head-and-shoulders,
double top, liquidity sweep, accumulation. Uses a vision model on the rendered chart,
**cross-checked against a deterministic rule engine** — neither alone is trustworthy.

## Cadence

- `on-demand`, usually chained after [[Agent — Chart Markup]]
- Never on a schedule — vision calls are expensive ([[LLM Model Tiers]])

## Inputs

- A rendered chart PNG from [[Charting Engine]] (fixed size and theme, for consistency)
- The [[Markup Spec]] that produced it — the model sees the same levels you do
- Deterministic structure computations: swing points, higher-high/lower-low sequence,
  ADX-style trend strength, range boundaries, volatility contraction

## Outputs

```yaml
symbol: NVDA
timeframe: 1D
spec: ms_01J8XR4K
structure:
  trend: up
  swing_sequence: HH-HL
  phase: continuation        # accumulation | markup | distribution | markdown | continuation
patterns:
  - name: bull_flag
    confidence: 0.68
    agreement: both          # vision | rules | both | conflict
    boundaries: { from: 2026-08-14, to: 2026-08-27 }
    why: "tight consolidation on declining volume after a 12% impulse leg"
  - name: liquidity_sweep
    confidence: 0.41
    agreement: vision
    why: "wick through the 8/09 low then immediate reclaim"
conflicts:
  - "Rules engine sees a range; vision sees a flag. Treat trend continuation as unconfirmed."
overall_confidence: 0.55
```

## The agreement field — the point of this agent

| `agreement` | Meaning | Confidence treatment |
|---|---|---|
| `both` | Vision and rules agree | Full confidence |
| `rules` | Deterministic only | Full confidence, it's measurable |
| `vision` | Vision only | **Cap at 0.5.** Vision models see patterns in noise. |
| `conflict` | They disagree | Report the conflict, do not resolve it silently |

A vision model asked "is there a pattern here?" will always find one. The rules
engine is the skeptic. When they conflict, the honest output is *"unconfirmed"* —
and [[Agent — Idea Synthesizer]] downweights accordingly.

## Tools

`genesis-charting.render` · `genesis-charting.structure` · vision model ·
`memory.read` · `memory.write`

## Memory namespace

Read: `shared`, `chart-markup`, `pattern-recognition`
Write: `pattern-recognition`

## System prompt sketch

> You are the Pattern Recognition agent. You look at a rendered chart and name its
> structure.
>
> **You are expected to find nothing much of the time.** Most charts are not
> textbook patterns. "No clear pattern, trending up, no actionable structure" is a
> correct and frequent answer. Pattern-matching noise is the failure mode of every
> vision model on charts — do not be one.
>
> You receive deterministic structure measurements alongside the image. When your
> visual read contradicts them, **report the conflict**; do not override the
> measurements. Numbers beat pixels.
>
> Confidence above 0.7 requires agreement between what you see and what was measured.
>
> Describe patterns by their boundaries and their volume behaviour, not just by name.
> "Bull flag" is a label; "tight consolidation on declining volume after a 12%
> impulse" is information.

## Cost control

Vision is expensive. Cache the interpretation against the [[Markup Spec]] id — the
same spec never gets read twice. Render once, ask once. Do not run this agent on a
cadence over a universe; it's a per-request tool.

## Acceptance criteria

- On a control set of random charts, returns "no clear pattern" ≥50% of the time.
- Never exceeds 0.5 confidence on a vision-only pattern.
- Conflicts are reported, never silently resolved in favour of the vision model.
- Repeat call on the same spec id costs zero vision tokens (cache hit).

## Related

[[Agent — Chart Markup]] · [[Agent — Multi Timeframe]] · [[Charting Engine]] ·
[[LLM Model Tiers]] · [[Charting Family]]
