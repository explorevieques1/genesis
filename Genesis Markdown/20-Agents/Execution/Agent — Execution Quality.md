---
title: Agent — Execution Quality
tags: [agent, execution]
family: execution
cadence: market-open, event
tier: none
status: building
implemented_by: [src/genesis/agents/execution/execution_quality.py, tests/execution/test_execution_quality.py]
---

# 📏 Agent — Execution Quality

## Purpose

Did we get a fair fill? Measures slippage, fill rate, and fees per trade and in
aggregate — then feeds it back into [[Agent — Backtest Runner]]'s cost model so
backtests stop lying about what execution actually costs.

The quiet agent that closes the loop between simulated and real trading.

## Cadence

- `event` on every fill
- `market-closed` daily aggregate → [[Agent — Performance Analyst]]

## Measurements

| Metric | Definition | Why it matters |
|---|---|---|
| **Arrival slippage** | Fill price vs. the mid at proposal time | The honest cost of your latency and decision-to-order delay |
| **Signal slippage** | Fill price vs. the strategy's theoretical signal price | What the backtest assumed vs. what you got |
| **Spread cost** | Half-spread paid at fill | Unavoidable, but should be measured |
| **Market impact** | Price movement attributable to your own size | Relevant once size approaches % of ADV |
| **Fill rate** | Limit orders filled / placed | A low rate means missed trades that the backtest counted |
| **Time to fill** | Submission → fill | |
| **Fee drag** | Fees as % of gross P&L | Often the difference between an edge and no edge |
| **Adverse selection** | Did price continue against you right after the fill? | Signals you're being picked off |

## Output

```yaml
fill_id: fill_01J8XW
order: ord_01J8XV
symbol: NVDA
side: buy
qty: 120
fill_price: 121.06
arrival_mid: 121.02
signal_price: 121.00
slippage:
  arrival_bps: 3.3
  signal_bps: 5.0
  dollars: 7.20
spread_at_arrival_bps: 2.1
fill_rate: 1.0
time_to_fill_ms: 840
fees: 0.60
adverse_selection_30s_bps: -1.2      # negative = price went our way after
verdict: normal                       # good | normal | poor | pathological
why: "3.3 bps arrival slippage on a 2.1 bps spread — reasonable for size"
```

Aggregate, daily:

```yaml
date: 2026-08-29
fills: 6
avg_arrival_slippage_bps: 4.1
median_arrival_slippage_bps: 3.3
worst: { symbol: AMD, bps: 14.2, why: "market order into a thin book at 09:31" }
limit_fill_rate: 0.82
total_fees: 3.60
fee_drag_pct_of_gross: 0.9
recommended_cost_model:
  slippage_bps: 4.0                   # measured, feeds backtests
  commission_bps: 1.0
drift_vs_backtest_assumption: "+2.0 bps — backtests are optimistic by ~2 bps per trade"
```

That last line is the payoff. Feed it back into [[Agent — Backtest Runner]] and
future backtests get honest.

## Findings it surfaces

- "Your market orders in the first minute cost 12 bps. Your limit orders after
  09:45 cost 3."
- "Limit fill rate on breakout entries is 61% — the backtest assumed 100%, so its
  results are meaningfully overstated."
- "Fees are 0.9% of gross P&L. On the mean-reversion strategy they're 4.1% — it may
  not have an edge after costs."
- "Adverse selection is consistently negative on `nq_orb_v3` — good, you're not
  being picked off."

## Tools

`memory.read` (ledger, orders) · `market-data.quote_history` · `memory.write`

No LLM ([[LLM Model Tiers]]) — this is measurement. [[Agent — Performance Analyst]]
does the narrating.

## Memory namespace

Read: `ledger`, `order-manager`
Write: `execution-quality`

## Acceptance criteria

- Arrival mid is captured **at proposal time**, not looked up later — this requires
  the [[Pre-Trade Risk Engine]] to stamp it, and it must be tested.
- Slippage math verified against hand-computed fixtures for buys and sells (sign
  errors here are easy and silent).
- Daily aggregate feeds a cost model that [[Agent — Backtest Runner]] actually consumes.
- `pathological` verdict fires on an obviously bad fill and never on a normal one.

## Implementation (2026-09-14)

Measured on every fill from the order manager: arrival slippage (bps and
dollars, positive = adverse), spread at arrival, time to fill, fees, and
adverse selection 30 s after. Stop fills are measured against their own trigger
price. **A fill benchmarked against a delayed quote gets verdict `unmeasured`**
— on IBKR's free feed the arrival mid is 10–15 minutes old, and slippage against
it measures the delay. The daily aggregate counts those separately rather than
averaging them in. Served at `/v1/exec/quality`, shown in the trade panel.
Not built: signal slippage (no strategy signals yet), feeding the backtest cost
model.

## Related

[[Agent — Order Manager]] · [[Agent — Backtest Runner]] · [[Agent — Performance Analyst]] ·
[[Agent — Backtest Vs Live Drift]] · [[Trade Ledger]] · [[Execution Family]]
