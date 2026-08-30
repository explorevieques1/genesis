---
title: Agent — Portfolio And Allocation
tags: [agent, strategy]
family: strategy
cadence: on-demand, event
tier: none
status: spec
implemented_by: []
---

# ⚖️ Agent — Portfolio And Allocation

## Purpose

Answer two questions with arithmetic, never with judgement:

1. **How big is this position?** — given the stop distance, account equity, and the
   strategy's risk-per-trade.
2. **How much of everything?** — portfolio weights across strategies and positions,
   accounting for correlation.

## Cadence

- `event` — on every order proposal, before it reaches [[Pre-Trade Risk Engine]]
- `market-closed` — portfolio-level rebalance suggestions
- `on-demand`

## Position sizing

The primary, hot path. Called on every single trade.

```
risk_dollars = equity × risk_pct
stop_distance = |entry − stop|
raw_size = risk_dollars ÷ stop_distance
size = min(raw_size,
           max_position_pct constraint,
           liquidity constraint (% of ADV),
           correlated-exposure constraint,
           prop-firm constraint)
size = round_to_tradeable(size)   # whole shares / contracts
```

Every constraint that bound is reported, so the [[Orchestrator]] can say *"half size
— you're already long two correlated semis"* instead of silently shrinking the trade.

```yaml
symbol: NVDA
entry: 121.00
stop: 118.40
equity: 100000
risk_pct: 0.5
risk_dollars: 500
stop_distance: 2.60
raw_size: 192
final_size: 120
binding_constraint: correlated_exposure
constraints_evaluated:
  max_position_pct:      { limit: 5.0,  would_allow: 413 }
  liquidity_pct_adv:     { limit: 1.0,  would_allow: 8200 }
  correlated_exposure:   { limit: 10.0, would_allow: 120 }   # ← binding
  prop_firm:             { limit: null, would_allow: null }
actual_risk_dollars: 312
actual_risk_pct: 0.31
why: "reduced from 192 to 120 — semis cluster already at 7.4% of equity"
```

## Kelly, and why it's capped

Kelly sizing is available but **hard-capped at a fraction** (default ¼ Kelly).
Full Kelly assumes your edge estimate is correct; it never is. Half Kelly on an
overestimated edge is ruin. The cap is not a suggestion — it's enforced in code.

## Portfolio allocation

The slower path, for weights across strategies and positions.

| Method | When |
|---|---|
| Equal risk contribution | Default. Simple, robust, hard to break. |
| Hierarchical Risk Parity (HRP) | When correlation clusters are meaningful — uses the clusters from [[Agent — Regime And Correlation]] |
| Mean-CVaR | When tail risk is the binding concern |
| Black-Litterman | When you want to express a view on top of a market prior |

Corpus references ([[Trading Corpus Index]]): `Riskfolio-Lib` `riskfolio/src/Portfolio.py`
(20+ risk measures), `PyPortfolioOpt` `hierarchical_portfolio.py` and
`black_litterman.py`, and critically `pypfopt/discrete_allocation.py` for turning
weights into **whole-share orders** — the step most implementations skip and then
wonder why the weights don't match.

Also `backtrader/sizers/` for the position-sizing plugin pattern.

## Tools

`riskfolio.optimize` · `pypfopt.allocate` · `memory.read` (ledger, correlation) ·
`memory.write`

No LLM ([[LLM Model Tiers]]). This is arithmetic on which real money depends.

## Memory namespace

Read: `ledger`, `regime-correlation`, strategy library, `shared`
Write: `portfolio-allocation`

## Relationship to the risk gate

This agent computes what size *should* be. [[Pre-Trade Risk Engine]] independently
verifies that the size is *allowed*. They are separate on purpose — sizing logic is
complex and could have a bug; the gate is simple, dumb, and re-checks everything
from scratch. Defence in depth.

## Acceptance criteria

- Position size math is exact to the share/contract; verified against hand-computed
  fixtures.
- The binding constraint is always identified and reported.
- Kelly output never exceeds the configured fraction, even if the formula says otherwise.
- Weights convert to whole shares without drift from the target allocation.
- Zero or negative stop distance is rejected, never divided by.
- A correlated book correctly reduces size (test: five semis positions).

## Related

[[Pre-Trade Risk Engine]] · [[Risk Envelope]] · [[Agent — Regime And Correlation]] ·
[[Agent — Prop Firm Guard]] · [[Trading Corpus Index]] · [[Strategy Family]]
