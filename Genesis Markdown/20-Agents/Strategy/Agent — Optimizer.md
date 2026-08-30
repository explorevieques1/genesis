---
title: Agent — Optimizer
tags: [agent, strategy]
family: strategy
cadence: market-closed
tier: none
status: spec
implemented_by: []
---

# 🎛️ Agent — Optimizer

## Purpose

Search parameter space **without fooling yourself**. The default outcome of naive
optimization is a beautiful equity curve that does nothing live. This agent's real
job is not finding the best parameters — it is deciding whether an edge exists at all.

## Cadence

`market-closed`, queue-driven. Long jobs, scheduled to finish before the 07:00 brief
([[Daemon And Cadence]]).

## Method

### Walk-forward by default

```
|--- IS 12mo ---|- OOS 3mo -|
        |--- IS 12mo ---|- OOS 3mo -|
                |--- IS 12mo ---|- OOS 3mo -|
```

Optimize on each in-sample window; record performance on the untouched out-of-sample
window that follows. **The reported result is the concatenation of the OOS windows**,
never the in-sample fit. A single in-sample optimization is not a result and this
agent will not report one as such.

### Overfit guards

| Guard | What it catches |
|---|---|
| **Deflated Sharpe** | Adjusts for the number of trials actually run. 200 trials will produce a 2.0 Sharpe by chance. |
| **Parameter plateau** | A lone peak surrounded by bad values is noise. Report the heatmap; prefer a broad plateau over the highest point. |
| **Parameter count penalty** | Every additional free parameter needs to earn its keep |
| **Permanent holdout** | A final slice never touched by any optimization, ever |
| **Trial registry** | Every trial is logged. Trial count feeds the deflated Sharpe. Re-optimizing the same strategy accumulates, it does not reset. |
| **Randomization test** | Compare against the same strategy on shuffled returns — if it still looks good, it's the search that's finding patterns, not the strategy |

That trial registry matters more than it sounds. Running the optimizer twenty times
and reporting the twentieth is the most common way a good process produces a bad
strategy. The count is cumulative and permanent.

## Inputs

- Strategy object with parameter ranges declared in [[Strategy Schema]]
- Walk-forward window configuration
- Objective function (default: OOS Calmar, not raw return)
- Cumulative prior trial count for this strategy

## Outputs

```yaml
strategy: nq_orb_v3
optimization_id: opt_01J8XU
method: walk_forward
windows: { is_months: 12, oos_months: 3, step_months: 3, count: 14 }
trials_this_run: 240
trials_cumulative: 640
best_params: { orb_minutes: 15, rel_volume: 1.5, atr_mult: 1.5 }
in_sample:  { sharpe: 1.81, calmar: 1.42 }
out_of_sample: { sharpe: 0.94, calmar: 0.71 }      # the honest number
deflated_sharpe: 0.61
plateau_quality: broad                              # broad | narrow | peak
holdout_untouched: true
verdict: marginal                                   # robust | marginal | overfit
heatmap: 40-Strategies/nq_orb_v3/opt_01J8XU-heatmap.png
why: >
  OOS Sharpe roughly half of IS. Parameter surface is a broad plateau, which is
  reassuring, but the deflated Sharpe after 640 cumulative trials is 0.61. Tradeable
  only at reduced size, and only in a trending regime.
```

**The verdict must be honest.** `overfit` is a common and correct output. An
optimizer that never says "this doesn't work" is a random number generator with a
progress bar.

## Tools

`genesis-backtest.run` · `genesis-backtest.optimize` · `empyrical.metrics` ·
`memory.write` · `obsidian.write`

Corpus references ([[Trading Corpus Index]]): `freqtrade/optimize/hyperopt_tools.py`
for the hyperopt pattern; `backtesting.py` `doc/examples/Parameter Heatmap &
Optimization.py` for the heatmap approach.

## Memory namespace

Read: strategy library, `backtest-runner`
Write: `optimizer`

## Compute budget

- Hard wall-clock cap per job (`agents.optimizer.max_wall_min`)
- Coarse grid first, refine only around promising regions
- Must finish before pre-market; a job that would overrun is killed and reports
  partial results honestly rather than being silently extended

## Acceptance criteria

- Never reports in-sample results as the headline figure.
- Trial count is cumulative across runs and persists.
- On a known-random strategy, verdict is `overfit`.
- A narrow single-peak parameter surface produces `plateau_quality: peak` and at
  best a `marginal` verdict.
- The permanent holdout is never read by this agent (enforced, not documented).
- Overrunning jobs are killed and report partial results with a clear caveat.

## Related

[[Agent — Backtest Runner]] · [[Agent — Risk Metrics]] · [[Paper To Live Promotion]] ·
[[Agent — Backtest Vs Live Drift]] · [[Strategy Family]]
