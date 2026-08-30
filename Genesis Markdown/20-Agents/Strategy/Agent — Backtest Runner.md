---
title: Agent — Backtest Runner
tags: [agent, strategy]
family: strategy
cadence: market-closed, on-demand
tier: none
status: spec
implemented_by: []
---

# ⏮️ Agent — Backtest Runner

## Purpose

Run a strategy over history and return the truth: metrics, equity curve, trade list,
tearsheet. **No LLM.** Deterministic, reproducible, and unit-tested — the same
strategy over the same data returns the identical result, forever.

## Cadence

- `market-closed` — the queue drains overnight where the compute budget lives
- `on-demand` — "Genesis, backtest that over five years" (short runs only)

## Two-stage design

| Stage | Engine | Purpose |
|---|---|---|
| **1. Vectorized sweep** | `vectorbt` | Fast, approximate. Parameter grids, large universes, first-pass viability. Seconds. |
| **2. Event-driven confirm** | `backtesting.py` / `nautilus_trader` | Slow, accurate. Realistic fills, order lifecycle, intrabar behaviour. Minutes. |

A strategy that looks good in stage 1 must survive stage 2 before it means anything.
Stage 1 alone systematically overstates results — it assumes fills that an
event-driven engine won't give you.

Corpus references ([[Trading Corpus Index]]): `vectorbt/portfolio/nb.py` for the
numba order-fill logic, `freqtrade/optimize/backtesting.py` for a production
backtest engine, `nautilus_trader/execution/` for correct order lifecycle.

## Inputs

- A strategy object per [[Strategy Schema]]
- Date range, and the **out-of-sample holdout** boundary (never crossed here)
- Cost model: commission, slippage, spread, borrow
- Data: bars at the strategy's timeframe, adjusted for splits and dividends

## Outputs

```yaml
strategy: nq_orb_v3
run_id: bt_01J8XT
engine: vectorbt+backtesting.py
period: { from: 2021-01-01, to: 2026-06-30 }
holdout: { from: 2026-07-01, to: 2026-08-29, used: false }
costs: { commission_bps: 1.0, slippage_bps: 2.0, spread_model: quoted }
metrics:                      # computed by [[Agent — Risk Metrics]], not here
  total_return: 0.61
  cagr: 0.11
  sharpe: 1.24
  sortino: 1.71
  calmar: 0.92
  max_drawdown: -0.12
  win_rate: 0.47
  profit_factor: 1.44
  expectancy_r: 0.21
  trades: 418
  avg_bars_held: 22
  exposure_pct: 0.34
equity_curve: <ref>
trades: <ref>                 # full list, per-trade MAE/MFE included
tearsheet: 40-Strategies/nq_orb_v3/bt_01J8XT.png
warnings:
  - "18% of trades occurred in the first 6 months — results are period-concentrated"
  - "Data gap 2022-03-14 to 2022-03-18; those days excluded"
```

## Correctness rules

These are the ways backtests lie. Each must be actively prevented, and prevention
must be tested.

| Trap | Prevention |
|---|---|
| **Lookahead bias** | Signals computed on bar *t* may only be acted on at bar *t+1*'s open. Tested with a deliberately-leaking strategy that must fail. |
| **Survivorship bias** | Universe must include delisted symbols for the period tested |
| **Data gaps** | Detect and report; never silently interpolate |
| **Splits/dividends** | Use adjusted series consistently |
| **Unrealistic fills** | Cost model always on; no fills at prices that never traded; volume-capped fills |
| **Period concentration** | Warn when returns come from a small slice of the sample |
| **Holdout leakage** | The holdout range is refused by this agent, not merely discouraged |

## Tools

`genesis-backtest.run` · `market-data.history` · `memory.write` · `obsidian.write`

## Memory namespace

Read: strategy library, `shared`
Write: `backtest-runner`, `40-Strategies/` in the vault

## Reproducibility

Every run records: engine versions, data snapshot hash, cost model, full parameter
set, and a random seed. Re-running `bt_01J8XT` a year later must produce identical
numbers. Without this, [[Agent — Backtest Vs Live Drift]] has nothing to compare
against and strategy comparisons are meaningless.

## Acceptance criteria

- A deliberately lookahead-biased strategy is **detected and rejected**, not silently run.
- Identical inputs produce byte-identical outputs across runs.
- Requesting a range overlapping the holdout is refused with a clear reason.
- Data gaps are reported, never interpolated.
- Vectorized 10-year single-symbol run completes in <10 s; event-driven in <2 min.
- Every result carries its cost model — a result without costs is never emitted.

## Related

[[Agent — Optimizer]] · [[Agent — Risk Metrics]] · [[Agent — Strategy Author]] ·
[[Agent — Backtest Vs Live Drift]] · [[genesis-backtest-mcp]] · [[Strategy Family]]
