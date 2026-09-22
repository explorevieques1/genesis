---
title: Agent — Broker Adapter
tags: [agent, execution, risk]
family: execution
cadence: event
tier: none
status: building
implemented_by: [src/genesis/execution/ibkr_broker.py, tests/execution/fake_broker.py]
---

# 🔌 Agent — Broker Adapter

## Purpose

One interface, many brokers. Normalizes order types, symbols, error shapes, and
account data so nothing above it knows or cares which broker is connected.

**Paper and live are the same code path**, differing only by credentials and a mode
flag. This is what makes paper trading meaningful — you are testing the actual
execution code, not a simulation of it.

## Cadence

`event` — called only by [[Agent — Order Manager]] and
[[Agent — Position And PnL Accountant]].

## The interface

```
place(order)        → broker_order_id | typed error
modify(id, changes) → ack | typed error
cancel(id)          → ack | typed error
query(client_id)    → order state           # the disambiguator after a timeout
positions()         → normalized positions
account()           → equity, cash, buying power, margin
stream()            → order updates, fills   (where supported)
```

Every method is either idempotent or safely queryable. `query(client_id)` is what
makes retry safe — after an ambiguous response, ask before acting.

## Normalization

The adapter absorbs the differences so the rest of the system stays simple:

| Difference | Normalized to |
|---|---|
| Symbol format (`BRK.B` / `BRK/B` / `BRK-B`) | canonical internal symbol |
| Order type names and semantics | the Genesis order type set |
| Bracket support (native / emulated / none) | always presented as native; emulated below if needed |
| Time-in-force semantics | explicit, per-order |
| Fractional shares | supported or not, surfaced as a capability |
| Error shapes | typed errors: `rejected`, `insufficient_funds`, `market_closed`, `rate_limited`, `session_lost`, `unknown` |
| Fee structures | normalized into the ledger's cost fields |

Capabilities are **declared, not assumed**:

```yaml
broker: alpaca
mode: paper
capabilities:
  native_brackets: true
  trailing_stop: true
  fractional: true
  extended_hours: true
  asset_classes: [equity, option, crypto]
  streaming_fills: true
```

If a broker lacks native brackets, the adapter declares it and
[[Agent — Order Manager]] emulates them — but it must *know*, because an emulated
bracket has a real gap between entry fill and stop placement.

## Reference implementation

`alpaca-mcp-server` (official) — see [[Trading Corpus Index]]. Study `src/` for tool
schema, auth handling, and error shape. It's the cleanest model for the tool
interface. Also `nautilus_trader/execution/` for multi-venue adapter design.

If the venue is futures at a prop firm, that reference set doesn't cover the
actual target — see [[Futures Broker Options]] for the survey (Tradovate's direct
API excludes prop accounts entirely) and its own reference pointers per firm
(TopstepX, Sierra Chart DTC, Rithmic R|API+, NinjaTrader ATI).

## Paper vs. live

```yaml
brokers:
  primary:
    kind: alpaca
    mode: paper        # paper | live
```

Going live requires **two independent actions**: changing this flag *and* the live
credentials being present in the environment ([[Config And Secrets]]). Never one
flag. The adapter refuses to start in `live` mode with paper credentials, and
announces its mode loudly at boot:

> "Genesis online. Broker: Alpaca, **paper**."

The mode is also shown persistently on the [[Dashboard]] — live mode in a colour you
cannot miss. Most catastrophic mistakes in this category begin with someone
believing they were on paper.

## Connection management

- Persistent session with heartbeat; automatic reconnect with backoff
- **On reconnect: reconcile before acting.** Query all working orders and positions
  and compare to the ledger *before* placing anything new
- Rate limiting respected proactively, not discovered through errors
- Session loss is a typed error, retried once silently, then surfaced
  (pattern: [[Repo — jarvis]] `mcp_runtime.spec.md`)

## Tools

Direct broker SDK/API, wrapped by [[genesis-execution-mcp]]. No LLM
([[LLM Model Tiers]]).

## Acceptance criteria

- Identical test suite passes against paper and live-sandbox credentials.
- Refuses to start in live mode without live credentials present.
- Mode is announced at boot and displayed persistently in the UI.
- Simulated timeout mid-placement, followed by `query()`, correctly determines
  whether the order exists — no duplicates in a 1000-iteration fuzz test.
- Unsupported capabilities are declared, never silently emulated without the caller knowing.
- Reconnect triggers reconciliation before any new order is accepted.

## Implementation (2026-09-14)

`IbkrBroker`: IB Gateway, its own connection with Read-Only off, fixed client
id `execution.client_id`. Refuses any account whose id is not paper (`D…`),
independently of `brokers.primary.mode` — two locks. Declares nothing it
emulates: native brackets, trailing stops, what-if margin, PnL subscriptions.
Order status maps to Order And Fill Schema states; fills are delivered with
their commission. A blank TIF makes the gateway's order preset swallow a what-if
(10349), so every order and what-if names its TIF. A bid or ask of zero or −1
means "none" and is never averaged into a mid.

## Related

[[Agent — Order Manager]] · [[Agent — Position And PnL Accountant]] ·
[[genesis-execution-mcp]] · [[Order And Fill Schema]] · [[Config And Secrets]] ·
[[Execution Family]] · [[Futures Broker Options]]
