---
title: Agent — Risk Metrics
tags: [agent, strategy]
family: strategy
cadence: on-demand
tier: none
status: spec
implemented_by: []
---

# 📐 Agent — Risk Metrics

## Purpose

One place where performance statistics are computed, correctly, for any equity
curve — a backtest, a live strategy, the whole account, or a single setup type.

There is exactly one implementation of Sharpe in Genesis. Every other agent calls
this one.

## Why it's its own agent

Risk metrics are easy to get subtly wrong and expensive to get wrong: annualization
factors, geometric vs. arithmetic returns, whether the risk-free rate is included,
how drawdown is measured on an equity curve with intraday marks. Five agents each
implementing "Sharpe" produces five different numbers and no way to compare anything.

Corpus reference: `empyrical/stats.py` (see [[Trading Corpus Index]]) — every metric,
one file, correct formulas. **Use it. Do not rewrite it.**

## Cadence

`on-demand`. Called by [[Agent — Backtest Runner]], [[Agent — Optimizer]],
[[Agent — Performance Analyst]], and [[Agent — Backtest Vs Live Drift]].

## Inputs

- A returns or equity series with its frequency
- Optional: positions and transactions (enables exposure, turnover, per-trade stats)
- Optional: a benchmark series (enables alpha, beta, information ratio)
- Risk-free rate and annualization convention

## Outputs

```yaml
period: { from: 2021-01-01, to: 2026-06-30, freq: daily }
returns:
  total: 0.61
  cagr: 0.11
  best_day: 0.041
  worst_day: -0.038
risk_adjusted:
  sharpe: 1.24
  sortino: 1.71
  calmar: 0.92
  omega: 1.31
  tail_ratio: 1.08
drawdown:
  max: -0.12
  max_duration_days: 84
  current: -0.03
  top_5: [...]
distribution:
  volatility_annual: 0.18
  downside_deviation: 0.11
  skew: -0.31
  kurtosis: 4.2
  var_95: -0.021
  cvar_95: -0.033
trade_stats:              # when transactions are supplied
  count: 418
  win_rate: 0.47
  profit_factor: 1.44
  expectancy_r: 0.21
  avg_win_r: 1.83
  avg_loss_r: -0.98
  largest_loss_r: -2.4    # >1R means a stop was violated — investigate
  avg_mae_r: -0.42
  avg_mfe_r: 1.12
benchmark:                # when a benchmark is supplied
  alpha_annual: 0.04
  beta: 0.82
  information_ratio: 0.38
  up_capture: 0.91
  down_capture: 0.74
caveats:
  - "418 trades over 5.5y — sufficient sample for trade stats"
  - "Skew is negative; Sharpe understates left-tail risk here"
```

## Rules

- **Always report the sample size.** A Sharpe of 3.0 over 14 trades is not a number,
  it's a coincidence. Emit a caveat below a configurable threshold.
- **Always report drawdown duration**, not just depth. An 8% drawdown lasting nine
  months is psychologically harder than a 20% one lasting three weeks, and it's the
  one that makes people abandon good systems.
- **Flag `largest_loss_r > 1.0`** — a loss bigger than 1R means a stop was violated,
  slipped, or gapped. That's an execution finding, and it's surfaced here.
- **Never annualize a short sample** without a loud caveat.
- **Never smooth or clean the curve.** Report what happened.

## Tools

`empyrical.metrics` · `pyfolio.tearsheet` · `memory.write`

No LLM. This agent is arithmetic ([[LLM Model Tiers]]).

## Tearsheets

Full tearsheet generation (rolling risk, drawdown tables, monthly return heatmap,
distribution plots) via the `pyfolio` pattern — `pyfolio/tears.py`, `timeseries.py`,
`risk.py`. Output lands in `40-Strategies/` for strategies and `90-Meta/` for the
account.

## Acceptance criteria

- Every metric matches `empyrical`'s reference output on a fixed test series, to
  floating-point tolerance.
- Sample-size caveat fires below the threshold, every time.
- `largest_loss_r > 1.0` always produces a flag.
- Identical inputs produce identical outputs — no randomness anywhere.
- Handles an empty or single-point series without crashing (returns nulls plus a caveat).

## Related

[[Agent — Backtest Runner]] · [[Agent — Optimizer]] · [[Agent — Performance Analyst]] ·
[[Agent — Backtest Vs Live Drift]] · [[Trading Corpus Index]] · [[Strategy Family]]
