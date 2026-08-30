---
title: Agent — ML Signal
tags: [agent, strategy]
family: strategy
cadence: market-closed
tier: large
status: optional
---

# 🧬 Agent — ML Signal

## Purpose

Learned predictive signals — feature pipeline, model training, periodic retrain,
prediction serving. **Advisory only.** An ML signal is one piece of evidence for
[[Agent — Idea Synthesizer]], never an autonomous trading authority.

Optional. Disabled by default (`agents.ml-signal.enabled: false`). Build it in
[[Build Order|Phase 10]], after the deterministic system demonstrably works.

## Why advisory only

An ML model on financial data is an overfitting machine with excellent PR. It is
useful as a weak signal among others; it is dangerous as a decision-maker because:

- Non-stationary data — the relationship it learned may have already stopped existing
- Its confidence is not calibrated to reality, and looks convincing anyway
- It cannot explain itself, so a losing streak is uninvestigable
- Feature leakage is easy to introduce and nearly invisible

So: it produces a score with a confidence. [[Agent — Idea Synthesizer]] weighs it
alongside everything else. It never sizes or triggers a trade by itself, and
[[Approval Modes|`auto-within-limits`]] never applies to an ML-originated idea.

## Cadence

- `market-closed` weekly — retrain
- `market-closed` daily — inference over the universe
- Never intraday inference in v1

## Inputs

- Feature set: price/volume derived, cross-sectional factors, regime features,
  fundamental factors from [[Agent — Fundamental]]
- Labels: forward returns over a defined horizon, or triple-barrier labels
- A point-in-time universe (delisted symbols included — survivorship bias is fatal here)

## Outputs

```yaml
model: gbdt_5d_v7
trained: 2026-08-25
train_period: { from: 2018-01-01, to: 2026-02-28 }
validation:  { from: 2026-03-01, to: 2026-06-30 }
holdout:     { from: 2026-07-01, to: 2026-08-24 }
metrics:
  ic: 0.031                    # information coefficient — the honest number
  ic_ir: 0.42
  rank_ic: 0.038
  holdout_ic: 0.019            # decayed vs. validation, as expected
  hit_rate: 0.53
predictions:
  - { symbol: NVDA, score: 0.71, percentile: 0.94, horizon_days: 5 }
top_features: [rel_volume_20d, sector_momentum, iv_rank, margin_trend]
decay_warning: "IC has fallen for 3 consecutive weeks — retrain or retire"
advisory_only: true
```

An IC of 0.03 is a *normal, useful* result in this domain. A model reporting IC of
0.3 has leakage — treat that as a bug alert, not a triumph.

## Guards

| Guard | Why |
|---|---|
| Point-in-time features only | No future data in any feature, ever |
| Purged, embargoed CV | Overlapping labels leak across fold boundaries |
| Permanent holdout | Never trained or tuned on |
| Feature-importance stability | Wildly shifting importances = the model is fitting noise |
| IC decay monitoring | Auto-retire the model when IC decays past a threshold |
| Retrain registry | Cumulative trial counting, as with [[Agent — Optimizer]] |

## Tools

`qlib.model` · `qlib.data` · `genesis-backtest.run` · `memory.write`

Corpus references ([[Trading Corpus Index]]): `qlib/contrib/model/` (GBDT, LSTM,
Transformer zoo) and `qlib/contrib/data/` (Alpha158/360 feature sets);
`machine-learning-for-trading/04_alpha_factor_research/` and `08_ml4t_workflow/`
for the end-to-end pipeline; `freqtrade/freqai/` for the retrain-on-schedule pattern;
`FinRL` if you go the reinforcement-learning route (`finrl/meta/env_stock_trading/`
for state/action/reward design).

## Memory namespace

Read: `fundamental`, `regime-correlation`, `shared`
Write: `ml-signal`

## Acceptance criteria

- A deliberately leaked feature is caught by the leakage test (IC implausibly high).
- Model output is never accepted as a sole basis for an idea — enforced in
  [[Agent — Idea Synthesizer]], tested.
- `advisory_only: true` on every prediction, always.
- Auto-retires on sustained IC decay without human intervention.
- Retraining completes inside the weekly closed-market window.

## Related

[[Agent — Idea Synthesizer]] · [[Agent — Fundamental]] · [[Agent — Optimizer]] ·
[[Trading Corpus Index]] · [[Strategy Family]]
