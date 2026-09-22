---
title: Agent — Order Manager
tags: [agent, execution, risk]
family: execution
cadence: event
tier: none
status: building
implemented_by: [src/genesis/execution/order_manager.py, src/genesis/server/execution_routes.py, tests/execution/test_order_manager.py, tests/execution/fake_broker.py, ui/src/api/useExecState.ts, ui/src/workspace/panels/trade.tsx]
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

## Implementation (2026-09-14)

One thread owns the order connection, the ledger handle and the approval book;
routes hand it work through `call()`. Every order is written to the ledger
before it is sent; a failed placement is recorded as rejected and never retried.

**Brackets.** A limit entry goes as a native IBKR bracket. A market entry's
fixed stop and target are placed **at the real fill price** the moment the fill
arrives, as a standalone OCA pair — an absolute price guessed from a delayed
quote can land on the wrong side of the fill. A trailing stop needs no price
and always travels with the parent. Failure to place protection is retried
twice by the grace monitor, then the position is flattened.

**What the paper gateway taught (all reproduced in `fake_broker.py`):**
- A bracket child given an explicit OCA group is rejected on its first
  modification *and cancelled* (10326). Native children carry no group.
- A market order can fill inside `place()`; protection is registered first.
- Blocking IBKR calls inside an event callback raise "event loop already
  running" after the order has gone out. Callback-triggered work is deferred
  until the callback returns, and protection placement first checks coverage.
- IBKR will not change an order's type in place (329). Converting a stop to a
  trailing stop places a whole new stop+target set one tick beyond the old one
  in a fresh OCA group, waits until it is working, then retires the old set.
- Cancelling an order that is already gone is a no-op, or a flatten would stop
  before sending its close.

**Management.** Move a limit entry (its stop and target move with it) · move a
stop (widening is re-checked by the gate) · stop to breakeven · convert to or
adjust a trailing stop · move a target · cancel (a protective stop on an open
position is refused) · flatten or close part, which shrinks stops and targets to
the remaining position first so an exit can never reverse it.

**Restart.** Orders are GTC under the fixed `execution.client_id`; on reconnect
reconciliation matches every working order and today's executions to the
ledger by `orderRef`, and positions by quantity. Anything Genesis did not place
halts trading until the trader adopts it from the panel (`/v1/exec/adopt`).

Deviation: until [[Agent — Position And PnL Accountant]] exists, the order
manager writes fills to the ledger itself. Average entry is not compared in
reconciliation — IBKR's futures `avgCost` includes commission.

## Related

[[Pre-Trade Risk Engine]] · [[Agent — Broker Adapter]] · [[Order And Fill Schema]] ·
[[Agent — Position And PnL Accountant]] · [[Kill Switch]] · [[Execution Family]]
