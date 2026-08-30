---
title: Trade Ledger
tags: [memory, risk]
status: spec
implemented_by: []
---

# Trade Ledger

The financial source of truth. Append-only, double-entry, reconciled daily against
the broker. **Zero tolerance for inconsistency.**

Single writer: [[Agent — Position And PnL Accountant]]. Everyone else reads.

## Why double-entry

Because single-entry position tracking drifts, and you don't find out until the
numbers are already wrong.

Every economic event is recorded as balanced entries. Cash decreases, position value
increases, fees are their own line. The books must balance after every event — and
when they don't, that's caught immediately rather than at reconciliation.

## Tables

| Table | Contents | Mutability |
|---|---|---|
| `orders` | Every order and every state transition | append-only |
| `fills` | Every execution: price, qty, fee, timestamp, venue | append-only |
| `positions` | Derived snapshots: qty, avg entry, per symbol per strategy | derived, rebuildable |
| `cash_flows` | Deposits, withdrawals, fees, interest, dividends | append-only |
| `equity_snapshots` | Mark-to-market at intervals and at session boundaries | append-only |
| `reconciliations` | Daily comparison results against broker state | append-only |

**`positions` is derived, not authoritative.** It can be dropped and rebuilt from
`fills` at any time — and doing so is part of the test suite. If the rebuild
disagrees with the stored snapshot, something is wrong and you want to know.

## Fill record

```yaml
id: fill_01J8XW
order_id: ord_01J8XV
client_order_id: gen_20260829_143100_NVDA_b_01
broker_fill_id: "abc-123"
symbol: NVDA
side: buy
qty: 120
price: 121.06
fee: 0.60
venue: IEX
ts: 2026-08-29T14:31:02.840Z
strategy: nq_orb_v3
idea: idea_01J8XS
trace_id: tr_01J8XP
approval_id: appr_01J8XV
```

Every fill carries `approval_id`. A fill without one means an order reached the
broker without passing [[Pre-Trade Risk Engine]] — that is a **critical bug**, and
it's detectable precisely because this field is required.

## Reconciliation

Daily at 16:15 ET, and on every broker reconnect ([[Agent — Broker Adapter]]).

Compared: positions by symbol and quantity, average entry price, cash balance,
total equity, working orders, and today's fills.

**Any mismatch is `fatal`:**
1. Emit `reconciliation.failed`
2. Trigger [[Kill Switch]] → mode `halt`
3. Speak it immediately
4. Block the order path until a human resolves it

There is no "small" mismatch. One share of divergence means the ledger and reality
have parted company, and every risk calculation downstream is now built on fiction.

## Money handling

- `Decimal`, never `float`. Everywhere. No exceptions. ([[Conventions]])
- Quantities are integers for shares and contracts; `Decimal` for fractional
- Currency is explicit on every amount
- Fees are recorded separately and included in realized P&L — a strategy profitable
  before fees and losing after must show as **losing**
- Lot method is consistent and configured (FIFO default), never mixed

## Rebuild and audit

The ledger must be fully rebuildable from `fills` and `cash_flows`. Two consequences:

- A corrupted `positions` snapshot is recoverable — drop and rebuild
- The rebuild is a continuous test: nightly, rebuild in memory and compare to stored.
  Divergence is a bug alert.

Every ledger row links to its `trace_id`, so the full causal chain from utterance to
fill is queryable ([[Episodic Log]], [[Observability]]).

## Acceptance criteria

- `UPDATE` or `DELETE` on `orders`, `fills`, or `cash_flows` fails at the database level.
- Positions rebuilt from fills match stored snapshots exactly, tested nightly.
- Books balance after every event — partial fills, reversals, scale-ins, scale-outs.
- A fill without a valid `approval_id` triggers a critical alert.
- Seeded reconciliation mismatch halts the system within 5 s.
- No `float` appears in any monetary field, enforced by a type test.

## Related

[[Agent — Position And PnL Accountant]] · [[Pre-Trade Risk Engine]] · [[Kill Switch]] ·
[[Order And Fill Schema]] · [[Memory Fabric]] · [[Safety Invariants]]
