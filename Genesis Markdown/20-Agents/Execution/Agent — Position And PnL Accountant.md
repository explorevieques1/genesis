---
title: Agent — Position And PnL Accountant
tags: [agent, execution, risk]
family: execution
cadence: market-open, event
tier: none
status: spec
implemented_by: []
---

# 🧾 Agent — Position And PnL Accountant

## Purpose

The **source of truth** for what you own, what it cost, and what it's worth. Every
other component asks this one — nothing computes its own idea of a position.

If this is wrong, [[Pre-Trade Risk Engine]] is making decisions on fiction.

## Cadence

- `event` on every fill — immediate
- `market-open` every 30 s — mark to market
- `cron` 16:15 ET — **daily reconciliation against the broker**

## Responsibilities

| Job | Detail |
|---|---|
| Position tracking | Quantity, average entry, side, per account and per strategy |
| Realized P&L | Closed trades, net of fees, using a consistent lot method (FIFO default) |
| Unrealized P&L | Mark-to-market on the current quote, with quote staleness tracked |
| Exposure | Gross, net, by sector, by strategy, by correlation cluster |
| **Portfolio heat** | Σ (entry − stop) × size across open positions, as % of equity |
| Daily P&L | Since the session's start, for the daily-loss check |
| Cost basis | Fees, commissions, borrow, and their effect on true P&L |
| Reconciliation | Ledger vs. broker, every day, with zero tolerance |

**Portfolio heat is the number that matters most.** Unrealized P&L tells you what
happened; heat tells you what can still happen. It's what
[[Pre-Trade Risk Engine]] check #8 uses.

## Output

```yaml
as_of: 2026-08-29T14:31:00Z
account: primary
equity: 101_240.55
cash: 42_100.00
buying_power: 84_200.00
positions:
  - symbol: NVDA
    qty: 120
    side: long
    avg_entry: 121.06
    current: 122.40
    unrealized: 160.80
    unrealized_r: 0.51
    stop: 118.40
    risk_open: 319.20        # (avg_entry − stop) × qty
    strategy: nq_orb_v3
    opened: 2026-08-29T14:12:00Z
    quote_age_ms: 400
exposure:
  gross_pct: 14.2
  net_pct: 14.2
  by_sector: { semis: 14.2 }
  by_cluster: { semis: 14.2 }
portfolio_heat_pct: 0.32
pnl:
  realized_today: -340.00
  unrealized: 160.80
  net_today: -179.20
  fees_today: 4.20
reconciled: true
reconciled_at: 2026-08-28T16:15:00-04:00
degraded: false
```

## Reconciliation — zero tolerance

Every day at 16:15 ET, and on every reconnect, the ledger is compared against the
broker's own position and cash report.

Any mismatch is **`fatal`**:
1. Emit `reconciliation.failed`
2. Trigger [[Kill Switch]] → mode `halt`
3. Speak it immediately, loudly, no matter what else is happening
4. Block the order path until a human resolves it

There is no "small" mismatch. A one-share discrepancy means the ledger and reality
have diverged, and every risk calculation downstream is now unreliable.

## Quote staleness

Unrealized P&L is only as good as the quote. Every position carries `quote_age_ms`.
Beyond a threshold, the accountant marks itself `degraded`, and:

- Spoken P&L is prefixed with "on delayed data"
- [[Approval Modes|`auto-within-limits`]] is suspended
- The [[Dashboard]] shows the P&L in a degraded style, not as a confident number

## Tools

`genesis-execution.positions` · `genesis-execution.account` · `market-data.quote` ·
`memory.write` (ledger) · `taskbus.publish`

No LLM ([[LLM Model Tiers]]). Reference: `nautilus_trader/portfolio/` for correct
position and P&L accounting ([[Trading Corpus Index]]).

## Memory namespace

Read: `ledger`, `shared`
Write: `ledger` (**the only writer**), `position-accountant`

Single-writer is deliberate. One component writes the ledger; everyone else reads it.

## Acceptance criteria

- Position math verified against hand-computed fixtures including partial fills,
  scale-ins, scale-outs, and reversals.
- Fees are included in realized P&L — a strategy profitable before fees and losing
  after must show as losing.
- A seeded reconciliation mismatch triggers halt within 5 s.
- Portfolio heat is correct with mixed long/short and multiple stops.
- Stale quotes produce `degraded: true` and suspend auto mode.
- Ledger is append-only — an `UPDATE` against a fill row fails at the database level.

## Related

[[Trade Ledger]] · [[Pre-Trade Risk Engine]] · [[Kill Switch]] ·
[[Agent — Order Manager]] · [[Agent — Execution Quality]] · [[Execution Family]]
