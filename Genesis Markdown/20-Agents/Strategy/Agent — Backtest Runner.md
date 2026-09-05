---
title: Agent — Backtest Runner
tags: [agent, strategy]
family: strategy
cadence: market-closed, on-demand
tier: none
status: building
implemented_by:
  - src/genesis/backtest/strategy.py
  - src/genesis/backtest/spec_strategy.py
  - src/genesis/backtest/runner.py
  - src/genesis/backtest/store.py
  - src/genesis/server/backtest_routes.py
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

| Stage | Engine | Purpose | Built |
|---|---|---|---|
| **1. Vectorized sweep** | `vectorbt` | Fast, approximate. Parameter grids, large universes, first-pass viability. Seconds. | ❌ not built |
| **2. Event-driven confirm** | `nautilus_trader` | Slow, accurate. Realistic fills, order lifecycle, intrabar behaviour. Minutes. | ✅ `backtest/runner.py` |

> **2026-09-05 — stage 2 first, and stage 1 may never be needed.**
> Nautilus is wired as *the* engine rather than as the confirmation half of a
> pair. A 122-bar daily run completes in ~60 ms in-process, which is well
> inside an interactive budget, so the argument for a fast approximate stage
> does not apply at the current data scale. Stage 1 becomes worth building when
> a parameter sweep over a large universe is actually being asked for — and the
> ordering matters, because stage 1 alone systematically overstates results.
> Building the accurate engine first means there is never a period where the
> only available answer is the flattering one.
>
> `backtesting.py` is dropped from the note: two event-driven engines is two
> implementations of expectancy, which is exactly the drift [[Agent — Backtest
> Vs Live Drift]] exists to detect and would then misreport.

A strategy that looks good in stage 1 must survive stage 2 before it means anything.
Stage 1 alone systematically overstates results — it assumes fills that an
event-driven engine won't give you.

Corpus references ([[Trading Corpus Index]]): `vectorbt/portfolio/nb.py` for the
numba order-fill logic, `freqtrade/optimize/backtesting.py` for a production
backtest engine, `nautilus_trader/execution/` for correct order lifecycle.

## Strategies are data, not code

The engine will not run a strategy a model wrote, because
[[Safety Invariants]] #3 puts backtest arithmetic in the spinal cord. The
boundary is drawn at authorship instead:

- `backtest/strategy.py` defines a **closed vocabulary** — indicators, comparison
  and crossover operators, stop/sizing/cost blocks. A `StrategySpec` is JSON.
  There is no `expression: str` field and no `eval`.
- `backtest/spec_strategy.py` is the **single** Nautilus `Strategy` class that
  interprets one. It is fixed, reviewed code; the spec only parameterises it.

So a model can answer *"create a MACD crossover strategy"* by selecting rules,
and cannot compute a stop, size a position, or emit an executable line. A spec
outside the vocabulary is rejected at parse time rather than run approximately.

> Nautilus documents `ImportableStrategyConfig(strategy_path, config)` for this
> and it was the intended mechanism. It does not work in v2 — `StrategyConfig`
> is a native Rust class, so a Python subclass declaring extra fields silently
> gains none of them. The spec is passed to a factory and the strategy is
> constructed in-process. The safety property is unchanged; the dotted-path
> allow-list is not what enforces it.

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

### Which of these hold today

| Trap | Status |
|---|---|
| Lookahead bias | ✅ Enforced by Nautilus' event loop — a bar is delivered, then acted on. Bracket stops rest at the venue rather than being resolved against a bar whose range is already known. |
| Unrealistic fills | ✅ Nautilus' simulated matching engine, with commission and slippage. |
| Data gaps | ⚠️ Reported as coverage on the market-data side; the runner does not yet refuse a gapped window. |
| Period concentration | ⚠️ Not detected. A thin sample is warned about (`< 30` positions), which is a weaker check. |
| Survivorship bias | ❌ The universe is whatever bars are held; there is no delisted-symbol set. |
| Splits/dividends | ✅ Adjusted series, flagged per bar (`adjusted`). |
| Holdout leakage | ❌ No holdout boundary is modelled yet. |

The unmet ones are listed rather than quietly omitted: a report that does not
say which traps it has *not* closed is one that reads as though it closed all
of them.

## Honesty machinery

Nautilus catches exceptions raised inside `on_bar` and logs them, so a broken
strategy produces a clean, zero-trade report. That failure is indistinguishable
from a strategy that simply never triggered — and the two conclusions a person
would draw are opposite.

So `SpecStrategy` records its own exceptions and the runner surfaces them as the
first warning on the run. Every `warnings` entry is *generated from the run*
rather than written by hand, so none of them can fall out of date:

- the strategy raised on at least one bar
- no positions were opened — statistics are empty rather than zero
- fewer than 30 closed positions — every ratio is indicative
- bars are tier 3 — fills are indicative ([[Market Data Sources]])
- more than half of bars were undecidable (indicators still warming up)

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
