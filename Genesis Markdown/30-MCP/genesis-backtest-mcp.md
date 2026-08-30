---
title: genesis-backtest-mcp
tags: [mcp, strategy]
status: spec
implemented_by: []
---

# genesis-backtest-mcp

One call runs a backtest and returns a complete, honest result. Wraps vectorbt,
backtesting.py, freqtrade, and empyrical behind a single interface.

## Tools exposed

| Tool | Behaviour |
|---|---|
| `run` | Backtest a [[Strategy Schema]] object over a date range. Two-stage: vectorized sweep, then event-driven confirm. Returns metrics, equity curve, trade list, tearsheet path. |
| `optimize` | Walk-forward parameter search with overfit guards. See [[Agent — Optimizer]]. |
| `metrics` | Canonical metrics for any returns series, via `empyrical`. See [[Agent — Risk Metrics]]. |
| `tearsheet` | Full pyfolio-style report from returns, positions, transactions |
| `compare` | Two runs side by side — for [[Agent — Backtest Vs Live Drift]] |
| `replay_live` | Re-run a strategy over the period it traded live. The sharpest drift diagnostic there is. |

## Why ours

The corpus offers four backtest engines with four different APIs, four different
result shapes, and four different sets of assumptions about fills. Agents should not
know or care which one ran.

More importantly, the **correctness rules** belong in one place:

- Lookahead detection
- Cost model always applied
- Holdout range refused, not merely discouraged
- Reproducibility metadata recorded on every run
- Data-gap reporting rather than silent interpolation

Put those in the server and every caller inherits them. Put them in each agent and
one of them will eventually skip a check.

## Engine routing

| Request | Engine |
|---|---|
| Parameter sweep, large universe, fast first pass | `vectorbt` |
| Single-strategy accurate confirm | `backtesting.py` |
| Production-like with protections and hyperopt | `freqtrade` |
| Tick-level / microstructure | `hftbacktest` |
| Metrics only | `empyrical` |
| Tearsheet | `pyfolio` |

See [[Trading Corpus Index]] for what each is good at and where the relevant code lives.

## Result contract

Every result carries, without exception:

- The cost model used (a backtest without costs is never returned)
- The data snapshot hash and engine versions
- Whether the holdout was touched (always `false` — it's refused)
- Data gaps found
- Warnings: period concentration, small sample, unrealistic fill assumptions
- A `reproducible_with` block sufficient to re-run it identically

## Refusals

The server refuses, rather than warns, on:

- A date range overlapping the permanent holdout
- A strategy with no stop or no sizing rule
- A cost model of zero (you must explicitly pass `frictionless: true`, and the result
  is labelled as such everywhere it appears)
- A strategy whose signals reference future bars — lookahead detection is a refusal

## Long jobs

Optimization runs for hours. The server:

- Accepts a job, returns a job id immediately
- Reports progress on the [[Task Bus]]
- Respects a wall-clock cap and returns **partial results honestly** if killed
- Never blocks an agent's task slot ([[Agent Contract]] timeout rule)

## Access

Allow-listed to the [[Strategy Family]] and [[Agent — Backtest Vs Live Drift]].

## Acceptance criteria

- A lookahead-biased strategy is refused, not run.
- A holdout-overlapping range is refused.
- Identical inputs produce identical outputs across runs and across machines.
- Every result includes its cost model and reproducibility block.
- A killed long job returns partial results with a clear caveat.
- `replay_live` correctly reproduces the simulated result for a period that was traded live.

## Related

[[Agent — Backtest Runner]] · [[Agent — Optimizer]] · [[Agent — Risk Metrics]] ·
[[Agent — Backtest Vs Live Drift]] · [[Strategy Schema]] · [[Trading Corpus Index]]
