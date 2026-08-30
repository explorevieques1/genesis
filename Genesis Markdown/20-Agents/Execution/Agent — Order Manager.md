---
title: Agent — Order Manager
tags: [agent, execution, risk]
family: execution
cadence: event
tier: none
status: spec
implemented_by: []
---

# 📤 Agent — Order Manager

## Purpose

Own the lifecycle of every order: place, modify, cancel, and manage the brackets and
trails that follow. It is the only component permitted to call
[[Agent — Broker Adapter]], and it only ever acts on proposals carrying a valid
approval from [[Pre-Trade Risk Engine]].

## Cadence

`event` — on approved proposals, on order status updates, on fills, on stop/target
management triggers.

## Order lifecycle

```
 proposal ──(approval)──► NEW ──► SUBMITTED ──► ACCEPTED ──┬──► PARTIALLY_FILLED ──► FILLED
                                     │                     │
                                     │                     ├──► CANCELLED
                                     └──► REJECTED         └──► EXPIRED
```

Every transition writes to the [[Trade Ledger]] and the [[Episodic Log]]. State is
reconstructible from the log alone — a requirement, not a nicety.
Reference: `nautilus_trader/execution/` ([[Trading Corpus Index]]).

## Order types

| Type | Use |
|---|---|
| Market | Only when explicitly requested or on an urgent exit. Never the default. |
| Limit | Default for entries |
| Stop / stop-limit | Protective stops and breakout entries |
| **Bracket** | Entry + stop + target as one atomic unit — the default for any trade with a plan |
| OCO | One-cancels-other for the stop/target pair |
| Trailing stop | Server-side where the broker supports it, client-side otherwise |

**Brackets are the default.** A position without a resting stop is an unbounded
loss waiting for an outage. If the broker cannot do native brackets, the manager
places the stop immediately after the entry fill and treats failure to do so as
`fatal` — it will flatten the position rather than hold it unprotected.

## Position management

Once filled, the manager runs the exit plan from [[Strategy Schema]]:

- **Move stop to breakeven** after a configured R multiple
- **Trail** by ATR or by structure (below the last swing low)
- **Partial exits** — scale out at targets, adjust the remaining stop
- **Time stop** — exit at session close or after N bars
- **Invalidation exit** — [[Agent — Level Watcher]] fires `invalidation` → exit

Every modification is itself an order and goes through the same lifecycle. A stop
move that *widens* risk is treated as a new order and re-checked by
[[Pre-Trade Risk Engine]] — you cannot enlarge risk through a modification.

That rule closes the most obvious hole in the gate.

## Idempotency and retries

- Every order carries a client-generated `client_order_id` ([[Order And Fill Schema]])
- **Never blind-retry a placement.** On an ambiguous response, query broker state by
  `client_order_id` first, then act. A duplicate fill is far worse than a missed one.
- On reconnect after a disconnect: reconcile all working orders against the broker
  before doing anything else
- On restart: adopt existing broker orders into the ledger, never re-place

## Tools

`genesis-execution.place` · `genesis-execution.modify` · `genesis-execution.cancel` ·
`genesis-execution.query` · `memory.read` · `memory.write` · `taskbus.publish`

No LLM ([[LLM Model Tiers]]).

## Memory namespace

Read: `ledger`, `shared`, strategy library
Write: `ledger` (via the accountant), `order-manager`

## Failure behaviour

| Situation | Action |
|---|---|
| Broker rejects an order | Log, speak the reason, do not retry blindly |
| Broker unreachable, no open positions | Queue nothing, report degraded |
| Broker unreachable, **open positions** | `fatal` — speak immediately, consider [[Kill Switch]] |
| Entry filled but stop placement failed | Retry twice, then **flatten the position** |
| Partial fill at session end | Follow the strategy's time-stop rule; never leave an unplanned overnight |

## Acceptance criteria

- No order reaches the broker without a matching approval id — enforced and tested.
- A position is never held without a resting stop for more than a configured
  grace period (default 5 s).
- A stop modification that widens risk is re-checked by the risk engine.
- Simulated disconnect mid-placement produces exactly one order, never two.
- Restart adopts existing broker orders without duplicating them.
- Works with all LLM backends down.

## Related

[[Pre-Trade Risk Engine]] · [[Agent — Broker Adapter]] · [[Order And Fill Schema]] ·
[[Agent — Position And PnL Accountant]] · [[Kill Switch]] · [[Execution Family]]
