---
title: Paper To Live Promotion
tags: [risk]
status: spec
implemented_by: []
---

# Paper To Live Promotion

The gate a strategy passes before it trades real money — and the gate it passes
again before it trades autonomously.

Nothing goes live because it looked good in a backtest. A backtest is a hypothesis;
paper trading is the experiment.

## The stages

```
 authored ──► backtested ──► paper ──► live (confirm) ──► live (auto)
                              │            │                  │
                          ≥30 trades    ≥30 trades      sustained edge
                          ≥4 weeks      ≥4 weeks        + all health gates
                          no drift      no drift
```

Each arrow is a gate with explicit criteria. No stage is skipped, including for a
strategy you're confident about — especially then.

## Backtest → paper

- Walk-forward out-of-sample results, not in-sample ([[Agent — Optimizer]])
- Deflated Sharpe above threshold, given the **cumulative** trial count
- Parameter surface is a plateau, not a peak
- Permanent holdout untouched
- Realistic costs applied
- `assumed_regime` declared, and the current regime matches
- Complete strategy: entry, exit, stop, sizing, session ([[Strategy Schema]])

## Paper → live (confirm mode)

The real gate. Minimums, all of which must hold:

| Criterion | Threshold |
|---|---|
| Live-path trades | ≥ 30 |
| Calendar duration | ≥ 4 weeks |
| Distinct regimes experienced | ≥ 1 full regime, ideally 2 |
| Drift vs. backtest | not `significant` ([[Agent — Backtest Vs Live Drift]]) |
| Execution quality | slippage within the assumed cost model ([[Agent — Execution Quality]]) |
| Implementation bugs found | zero open |
| Max drawdown in paper | within the strategy's envelope |
| Expectancy | positive, and consistent with the backtest distribution |

Note the 4-week minimum sits alongside the 30-trade minimum. Thirty trades in three
days tells you about one market condition, not about a strategy.

**Promotion requires your explicit approval** in the [[Dashboard]] ([[Approval Modes]]
loosening rule). The system proposes and shows the evidence; you decide.

Initial live sizing is a fraction of the strategy's eventual envelope — typically
25–50% — for the first N trades.

## Live (confirm) → live (auto)

The final gate, the hardest, and the one worth being slow about.

| Criterion | Threshold |
|---|---|
| Live trades in `confirm` | ≥ 30 |
| Live expectancy | positive and within the backtest distribution |
| Drift severity | `low` for the entire period |
| Execution path health | no `degraded` events during the period |
| Regime | current regime matches `assumed_regime` |
| Approval overrides | zero times you rejected a proposal the system made |

That last row is quietly the most important. If you kept saying no to the system's
proposals, the system's judgement doesn't match yours yet — and it should not be
acting unattended.

Even after promotion, `auto-within-limits` remains conditional on health, fresh
data, and no imminent high-impact event ([[Safety Invariants]] #8).

## Demotion

Automatic, and deliberately easier than promotion:

| Trigger | Demote to |
|---|---|
| Drift severity `critical` | `confirm`, size halved |
| Suspected implementation bug | `confirm` |
| `strategy.assumption_broken` from [[Agent — Regime And Correlation]] | `confirm` |
| Any execution-path component `degraded` | `confirm` (all strategies) |
| Max drawdown breach | paper |
| Reconciliation failure | `halt` (system-wide) |

Demotion never needs your approval. Promotion always does. That asymmetry is the
whole design.

## The promotion record

```yaml
strategy: nq_orb_v3
stage: live_confirm
promoted_at: 2026-08-15T18:00:00Z
promoted_by: human
evidence:
  paper_trades: 34
  paper_weeks: 5.2
  paper_expectancy_r: 0.28
  backtest_oos_expectancy_r: 0.31
  drift_z: -0.4
  regimes_seen: [trending, transitional]
  slippage_vs_assumed_bps: +1.2
  bugs_found: 0
size_fraction: 0.5
review_after_trades: 30
```

Stored in [[Memory Fabric]] and the vault at `40-Strategies/`. The evidence is
retained — when a strategy later fails, you can see exactly what it was promoted on.

## Acceptance criteria

- A strategy cannot reach live without a promotion record signed by a human.
- Thresholds are enforced in code, not documented and hoped for.
- Demotion is automatic and requires no approval.
- Promotion evidence is retained permanently.
- A strategy at `paper` cannot place a live order — tested.

## Related

[[Approval Modes]] · [[Agent — Backtest Vs Live Drift]] · [[Agent — Optimizer]] ·
[[Risk Envelope]] · [[Safety Invariants]] · [[Strategy Schema]]
