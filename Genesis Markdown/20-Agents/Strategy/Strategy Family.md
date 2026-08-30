---
title: Strategy Family
tags: [moc, agent, strategy]
status: spec
implemented_by: []
---

# 🧪 Strategy Family

Seven agents that turn ideas into tested, sized, rule-bound strategies. This family
is the bridge between "that looks good" and "that has positive expectancy."

| Agent | One line |
|---|---|
| [[Agent — Strategy Author]] | Plain English → a testable strategy object (and PineScript) |
| [[Agent — Backtest Runner]] | Run it over history, return the truth |
| [[Agent — Optimizer]] | Search parameters without fooling yourself |
| [[Agent — Risk Metrics]] | Canonical, correct performance statistics |
| [[Agent — Portfolio And Allocation]] | How big, and how much of everything else |
| [[Agent — ML Signal]] | Learned signals — advisory only, never autonomous |
| [[Agent — Prop Firm Guard]] | Funded-account rule sets as hard constraints |

## The pipeline

```
 idea / voice ──► STRATEGY AUTHOR ──► strategy object ([[Strategy Schema]])
                                            │
                                            ▼
                                    BACKTEST RUNNER ──► equity curve + trades
                                            │
                          ┌─────────────────┼─────────────────┐
                          ▼                 ▼                 ▼
                     OPTIMIZER        RISK METRICS     PORTFOLIO/ALLOCATION
                  (walk-forward)    (empyrical math)     (size & weights)
                          │                 │                 │
                          └─────────────────┴─────────────────┘
                                            ▼
                                 [[Paper To Live Promotion]]
                                            ▼
                                    [[Execution Family]]
```

## Four of these agents run no LLM at all

[[Agent — Backtest Runner]], [[Agent — Optimizer]], [[Agent — Risk Metrics]],
[[Agent — Portfolio And Allocation]], and [[Agent — Prop Firm Guard]] are
`tier: none` — deterministic code with unit tests.

This is deliberate and non-negotiable. A language model must never compute a Sharpe
ratio, a position size, or a drawdown. It can *interpret* those numbers; it can
never produce them. See [[LLM Model Tiers]].

## Borrow, don't reinvent

Every piece of math here exists, correct and tested, in [[Trading Corpus Index|the corpus]]:

| Need | Source |
|---|---|
| Vectorized backtest / parameter sweep | `vectorbt/portfolio/` |
| Event-driven confirm | `backtesting.py`, `nautilus_trader` |
| Hyperopt + walk-forward | `freqtrade/optimize/` |
| Risk metrics | `empyrical/stats.py` — every formula, one file |
| Tearsheets | `pyfolio/tears.py` |
| Allocation | `PyPortfolioOpt`, `Riskfolio-Lib` |
| Drawdown guards | `freqtrade/plugins/protections/` |
| Prop-firm rules | `PropForge` |

Getting a Sharpe ratio subtly wrong is easy and expensive. Use the reference
implementation.

## The overfitting problem

The default outcome of any strategy search is a beautiful curve that does nothing
live. Countermeasures are built into the family, not bolted on:

- Walk-forward by default; a single in-sample optimization is not a result
- A permanent out-of-sample holdout that is **never** optimized against
- Deflated Sharpe — adjust for the number of trials actually run
- Parameter-sensitivity heatmaps — a lone peak is noise, a plateau is an edge
- Realistic costs: slippage, commission, and borrow, always on
- [[Agent — Backtest Vs Live Drift]] watches whether reality agrees, afterwards

## Related

[[Agent Index]] · [[Strategy Schema]] · [[Paper To Live Promotion]] ·
[[Execution Family]] · [[Trading Corpus Index]]
