---
title: Agent — Backtest Vs Live Drift
tags: [agent, journal]
family: journal
cadence: market-closed
tier: large
status: built
implemented_by: [src/genesis/agents/journal/drift.py, src/genesis/journal/drift.py, tests/journal/test_agents.py]
---

# 📉 Agent — Backtest Vs Live Drift

## Purpose

Does reality agree with the backtest? When live results diverge from the strategy's
tested expectation, there are exactly two explanations — **the regime changed**, or
**the implementation has a bug**. Both are urgent. This agent detects the divergence
and works out which.

## Cadence

`market-closed` nightly per active strategy; deeper weekly pass.

## Method

For each live strategy, compare live results against the backtest's out-of-sample
distribution — not against a single number.

```yaml
strategy: nq_orb_v3
live_period: { from: 2026-06-01, to: 2026-08-29, trades: 47 }
backtest_oos:
  expectancy_r: 0.31
  win_rate: 0.48
  avg_win_r: 1.79
  avg_loss_r: -0.98
  trades_per_week: 4.1
live:
  expectancy_r: 0.04
  win_rate: 0.43
  avg_win_r: 1.31
  avg_loss_r: -1.02
  trades_per_week: 3.8
divergence:
  expectancy_z: -2.1        # standard deviations from the backtest distribution
  significant: true
  primary_gap: avg_win_r    # winners are smaller, losers are the same size
diagnosis:
  likely_cause: implementation
  reasoning: >
    Trade frequency and loss size match the backtest closely, so the signal is
    firing as designed and stops are working. Winners are 27% smaller. That points
    at the exit path, not the market — check the trailing stop and whether early
    exits are being taken.
  regime_check:
    backtest_regime: trending
    live_regime: trending
    regime_stable: true
  execution_check:
    slippage_live_bps: 6.1
    slippage_assumed_bps: 2.0
    contribution_to_gap_r: 0.05
recommendation: "Investigate the exit path before continuing. Reduce size to half until resolved."
severity: high
```

## The diagnostic tree

The value is in distinguishing the causes, and each has a signature:

| Symptom | Likely cause |
|---|---|
| Trade frequency much lower than backtest | Signal not firing — data or condition bug |
| Trade frequency higher | Signal firing on bars it shouldn't — lookahead removed in live, present in backtest |
| Losses larger than backtest | Stops slipping, gapping, or not being placed |
| Winners smaller | Exit path — trailing stop, early exits, or partials misconfigured |
| Everything proportionally worse | Costs — check [[Agent — Execution Quality]] |
| Win rate down, sizes matching | Regime — check [[Agent — Regime And Correlation]] |
| Matches for weeks, then diverges sharply | Regime change at a specific date |
| Never matched from day one | The backtest was overfit — check [[Agent — Optimizer]] trial count |

That last row is the most common one, and the hardest to admit.

## Statistical honesty

47 live trades against a 400-trade backtest is a small sample. This agent must not
cry wolf on normal variance.

- Compare against the **distribution**, not the point estimate — a z-score, not a difference
- Minimum 30 live trades before declaring divergence significant
- Report the probability that the gap is chance
- Distinguish "underperforming" (common, expected, noise) from "distributionally
  different" (rare, meaningful)

A strategy that runs 20% below its backtest expectancy over 40 trades is probably
fine. One where losses are systematically larger over the same 40 trades is not.

## Escalation

| Severity | Action |
|---|---|
| `low` | Note it, keep watching |
| `medium` | Vault note, mention in the weekly review |
| `high` | Speak it, recommend size reduction |
| `critical` | Recommend pausing the strategy; if the cause looks like an implementation bug, auto-demote it to [[Approval Modes\|`confirm`]] |

Auto-demotion on a suspected implementation bug is deliberate: if the code might be
wrong, autonomy is withdrawn until it's proven right.

## Tools

`memory.read` (ledger, backtests, journal, regime) · `empyrical.metrics` ·
`genesis-backtest.run` (to re-run the backtest over the live period) · `memory.write`

Re-running the backtest over the *live period* is the sharpest test available: same
strategy, same dates, simulated vs. actual. If they disagree there, it's the
implementation, not the market.

## Memory namespace

Read: `ledger`, `backtest-runner`, `optimizer`, `regime-correlation`, `execution-quality`
Write: `drift`, `shared`

## System prompt sketch

> You are the Drift agent. You compare live results to backtest expectations and
> diagnose the difference.
>
> **Distinguish variance from divergence.** Most underperformance is noise. Use the
> distribution, not the point estimate, and state the probability that the gap is chance.
>
> When you do find real divergence, diagnose it. "It's not working" is not an output.
> Use the diagnostic signatures: what matches and what doesn't is the evidence.
>
> Consider that the backtest may have been wrong. An overfit backtest that never
> matched is a common and important finding — check the cumulative trial count.
>
> Never recommend continuing a strategy with a suspected implementation bug at full
> size. Reduce or pause.

## Acceptance criteria

- Does not flag divergence below 30 live trades.
- On a seeded implementation bug (deliberately broken exit logic), correctly
  diagnoses `implementation`.
- On a seeded regime change, correctly diagnoses `regime`.
- Re-runs the backtest over the live period as part of the diagnosis.
- `critical` severity auto-demotes the strategy's approval mode.

## Related

[[Agent — Backtest Runner]] · [[Agent — Optimizer]] · [[Agent — Regime And Correlation]] ·
[[Agent — Execution Quality]] · [[Paper To Live Promotion]] · [[Journal Family]]
