---
title: genesis-execution-mcp
tags: [mcp, execution, risk]
status: spec
implemented_by: []
---

# genesis-execution-mcp

Our normalized multi-broker order interface **with the risk gate baked in**.

## Why it must be ours

If agents could call a broker MCP directly, the risk gate would be a convention
rather than a wall. By making the only available execution tools ones that route
through [[Pre-Trade Risk Engine]], bypassing it becomes impossible rather than
merely discouraged.

This is the same principle as [[MCP Gateway]] allow-lists, applied one level deeper:
**make the unsafe thing unrepresentable**.

## Tools exposed

| Tool | Behaviour |
|---|---|
| `propose_order` | Submit a proposal. Runs [[Agent — Portfolio And Allocation]] sizing, then [[Pre-Trade Risk Engine]]. Returns `approve` / `resize` / `reject` with full reasoning. **Does not place anything.** |
| `place_approved` | Places an order that already carries a valid, unexpired approval id. Rejects anything else. |
| `modify_order` | Modify a working order. Any modification that widens risk is re-checked by the risk engine. |
| `cancel_order` | Cancel. Always permitted, in any mode. |
| `query_order` | Order state by `client_order_id`. The disambiguator after an ambiguous response. |
| `positions` | Normalized open positions. |
| `account` | Equity, cash, buying power, margin. |
| `halt` | Trigger [[Kill Switch]]. Always available. |

Note what is **not** exposed: there is no `place_order`. The only path to the broker
is `propose_order` → approval → `place_approved`, and the approval id is generated
by the risk engine, not by the caller.

## Approval tokens

```yaml
approval_id: appr_01J8XV
proposal_id: ord_prop_01J8XV
approved_size: 120
expires_at: 2026-08-29T14:32:02Z    # 60 s
binds_to:
  symbol: NVDA
  side: buy
  qty: 120
  limit: 121.20
signature: <hmac>
```

- **Single use.** Consumed on placement.
- **Short-lived.** 60 s, matching the [[Approval Modes]] confirmation TTL.
- **Bound to the exact order.** Changing symbol, side, size, or price invalidates it.
- **Signed**, so a forged token is detectable.

## Access

Allow-listed to exactly two components ([[MCP Gateway]]):

- [[Agent — Order Manager]] — full access
- [[Agent — Position And PnL Accountant]] — read-only (`positions`, `account`)

Every other agent in the system is rejected at the gateway.

## Mode enforcement

The server itself enforces [[Approval Modes]] — a second, independent check from the
orchestrator's:

| Mode | `place_approved` |
|---|---|
| `advisory` | **always rejects** — the broker adapter is never reached |
| `confirm` | requires a recorded human confirmation linked to the approval |
| `auto-within-limits` | permitted when all auto-mode conditions held at approval time |
| `halt` | rejects; `cancel_order` still permitted |

Two independent enforcements of the same policy, in different processes. Defence in
depth ([[Execution Family]]).

## Reference implementation

`alpaca-mcp-server` `src/` (see [[Trading Corpus Index]]) — study it for tool schema
design, auth handling, and error shapes before writing this. Also
`nautilus_trader/execution/` for order lifecycle correctness.

## Acceptance criteria

- No tool exists that places an order without an approval id.
- An expired, reused, or mutated approval token is rejected — tested for each case.
- `advisory` mode: a test asserts the broker adapter is never called, for every tool.
- Every agent except the two allow-listed ones is rejected at the gateway.
- `halt` works with the LLM path and the task bus both down.

## Related

[[Pre-Trade Risk Engine]] · [[Agent — Order Manager]] · [[Agent — Broker Adapter]] ·
[[Approval Modes]] · [[Kill Switch]] · [[MCP Gateway]] · [[Execution Family]]
