---
title: Agent — Regime And Correlation
tags: [agent, research]
family: research
cadence: market-closed
tier: large
status: spec
implemented_by: []
---

# 🌐 Agent — Regime And Correlation

## Purpose

Two related jobs the rest of the system depends on:

1. **Regime classification** — rolling volatility and trend regimes, and detection of
   when one changes.
2. **Correlation structure** — what actually moves together right now, so
   "diversified" positions aren't secretly the same bet.

Its most valuable output is a **warning**: when a strategy's assumed regime no
longer holds, it says so before the losses accumulate.

## Cadence

- `market-closed` daily
- `cron` Sunday — deep pass with a longer lookback
- `event` on `regime.changed` from [[Agent — Market Analyst]] (confirm or contradict
  the intraday read with statistical evidence)

## Inputs

- Long history for the universe and benchmarks
- Realized volatility across multiple windows (10/20/60/120d)
- Rolling pairwise correlation matrices at several lookbacks
- Trend/range classification per symbol (e.g. ADX-like, Hurst, variance ratio)
- Each active strategy's declared `assumed_regime` from [[Strategy Schema]]
- Live performance by strategy from [[Agent — Performance Analyst]]

## Outputs

### Regime record
```yaml
as_of: 2026-08-29
vol_regime: low              # low | normal | elevated | crisis
vol_percentile_1y: 0.28
trend_regime: trending       # trending | ranging | transitional
dispersion: low              # cross-sectional dispersion — low = index-driven tape
regime_age_days: 34
change_probability: 0.18     # probability the regime flips in the next 5 sessions
```

### Correlation record
```yaml
as_of: 2026-08-29
lookback_days: 60
clusters:
  - name: semis
    members: [NVDA, AMD, AVGO, MU]
    avg_internal_corr: 0.81
  - name: mega-tech
    members: [AAPL, MSFT, GOOGL]
    avg_internal_corr: 0.68
notable_changes:
  - "NVDA↔SPY correlation rose 0.52 → 0.79 over 20d — single-name idiosyncrasy collapsing"
effective_positions: 2.1     # your 5 positions are really ~2 independent bets
```

`effective_positions` goes straight into [[Pre-Trade Risk Engine]]'s correlated-exposure
check. It's the number that catches "I'm diversified across five semis."

### Assumption warnings
```yaml
warnings:
  - strategy: nq_orb_v3
    assumed_regime: trending
    current_regime: ranging
    severity: high
    action: "recommend pausing; ORB setups have negative expectancy in ranging tape"
```

Emits `regime.changed` and `strategy.assumption_broken`.

## Tools

`market-data.history` · `empyrical.metrics` · `qlib.regime` · `memory.read` · `memory.write`

## Memory namespace

Read: `shared`, `market-analyst`, `performance-analyst`, strategy definitions
Write: `regime-correlation`, `shared`

## System prompt sketch

The statistics are deterministic code; the LLM interprets and warns.

> You are the Regime and Correlation agent. The numbers are computed for you — your
> job is to interpret them and issue warnings.
>
> Be conservative about declaring a regime change. Regimes that flip weekly are
> noise, not regimes. Require persistence before changing the label, and report
> `change_probability` rather than pretending to certainty.
>
> Your highest-value output is `strategy.assumption_broken`. When a live strategy's
> assumed regime no longer holds, say so plainly and recommend a specific action.
> Do not soften it.
>
> Correlation is unstable and rises in stress. Always report both the current value
> and its recent trend — a correlation moving from 0.5 to 0.8 is the story, not the 0.8.

## Implementation notes

Metric implementations should come from `empyrical/stats.py` (see
[[Trading Corpus Index]]) rather than being rewritten — these formulas are easy to
get subtly wrong. Correlation clustering: hierarchical, matching the HRP approach in
`Riskfolio-Lib` / `PyPortfolioOpt` `hierarchical_portfolio.py`, so clusters are
consistent with how [[Agent — Portfolio And Allocation]] sizes them.

## Acceptance criteria

- Regime label persists ≥5 sessions on average over a historical backtest — no
  daily flip-flopping.
- `effective_positions` correctly collapses a 5-position all-semis book to ≈1.
- Fires `strategy.assumption_broken` on a labelled historical regime change within
  3 sessions.
- Daily pass over the universe completes inside the closed-market window.

## Related

[[Agent — Market Analyst]] · [[Agent — Idea Synthesizer]] ·
[[Agent — Portfolio And Allocation]] · [[Pre-Trade Risk Engine]] ·
[[Agent — Backtest Vs Live Drift]] · [[Research Family]]
