---
title: Execution Family
tags: [moc, agent, execution, risk]
status: spec
implemented_by: []
---

# ⚡ Execution Family

Six components that touch real money. **Every [[Safety Invariants|safety invariant]]
applies here in full.** Build them in the order given in [[Build Order|Phase 7]] —
the gate before the gun.

| Component | One line |
|---|---|
| [[Pre-Trade Risk Engine]] | **The gate.** Every order. No bypass. No exceptions. |
| [[Agent — Order Manager]] | Place, modify, cancel; brackets, trails, partials, OCO |
| [[Agent — Position And PnL Accountant]] | The source of truth for what you own |
| [[Agent — Broker Adapter]] | One interface, many brokers; paper and live share a code path |
| [[Agent — Execution Quality]] | Did we get a fair fill? |
| [[Kill Switch]] | Stop everything, now, without the LLM |

## The order path

There is exactly one, and it is a straight line:

```
  proposal (agent or human)
        │
        ▼
  [[Agent — Portfolio And Allocation]]   ← computes what size should be
        │
        ▼
  ╔═══════════════════════════════════╗
  ║   [[Pre-Trade Risk Engine]]       ║  ← independently verifies it's allowed
  ║   approve | resize | reject       ║     fails CLOSED
  ╚═══════════════════════════════════╝
        │
        ▼
  [[Approval Modes]]                     ← policy gate: advisory / confirm / auto
        │
        ▼
  [[Agent — Order Manager]] ──► [[Agent — Broker Adapter]] ──► broker
        │
        ▼ fill
  [[Agent — Position And PnL Accountant]] ──► [[Trade Ledger]]
        │
        ├──► [[Agent — Execution Quality]]  (slippage analysis)
        └──► [[Agent — Trade Journal]]      (the vault note)
```

**A human clicking "buy" on the [[Dashboard]] enters at the same place as an agent
proposal.** There is no fast path, no manual override, no "just this once."

## Zero LLMs

Every component in this family is `tier: none` ([[LLM Model Tiers]]).

Language models propose trades. They do not size them, check them, place them,
account for them, or cancel them. The entire path from "approved" to "filled" is
deterministic code with unit tests, and it keeps working when every model endpoint
is down.

## Defence in depth

The same limit is checked more than once, by different code:

1. [[Agent — Portfolio And Allocation]] sizes *within* the limits
2. [[Pre-Trade Risk Engine]] independently re-derives and verifies from scratch
3. [[Agent — Prop Firm Guard]] applies funded-account rules as a separate veto
4. [[Agent — Broker Adapter]] applies broker-side limits where available
5. [[Kill Switch]] watches the aggregate and can stop everything

Redundant on purpose. Sizing logic is complex enough to have a bug; the gate is
simple enough not to.

## Fail closed

Every ambiguity resolves toward *not trading*:

- Risk rule can't be evaluated (missing data) → **reject**
- Broker state unknown → **do not place**, query first
- Ledger inconsistent → **halt**
- Execution-path component degraded → force [[Approval Modes|`confirm`]]
- Confirmation expired → re-propose, never assume

## Related

[[Safety Invariants]] · [[Risk Envelope]] · [[Approval Modes]] ·
[[Order And Fill Schema]] · [[Trade Ledger]] · [[Agent Index]]
