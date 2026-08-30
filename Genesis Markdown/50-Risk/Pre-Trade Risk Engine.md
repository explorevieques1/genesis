---
title: Pre-Trade Risk Engine
tags: [agent, execution, risk, core]
family: execution
cadence: event
tier: none
status: spec
implemented_by: []
---

# 🛡️ Pre-Trade Risk Engine

## Purpose

**The gate.** Every order — from an agent, from you, from a strategy, from the
dashboard — passes through here before it can reach a broker. It returns
`approve`, `resize`, or `reject`, always with the numbers that produced the decision.

This is the most important component in Genesis. If it has a bug, nothing else
matters.

## Design principles

1. **Separate process from the LLM path.** It runs and decides with every model
   endpoint down.
2. **No LLM anywhere in it.** Rules, arithmetic, tests. ([[LLM Model Tiers]])
3. **Fails closed.** A rule that cannot be evaluated is a rejection, never a pass.
4. **Independently re-derives everything.** It does not trust the size it was given
   by [[Agent — Portfolio And Allocation]]; it recomputes from the ledger and the
   [[Risk Envelope]].
5. **No bypass exists.** Not for humans, not for "just this once," not for a
   manual dashboard ticket. There is no code path around it.
6. **Every decision is logged** with all inputs, so any rejection is explicable months later.

## Cadence

`event` — on every order proposal. Must complete in **under 50 ms**; it sits in the
hot path and the [[Task Bus]] gives it a dedicated worker pool.

## Checks

Evaluated in order; **first hard failure rejects**. Soft failures resize.

| # | Check | Failure | Source |
|---|---|---|---|
| 1 | Approval mode permits orders at all | reject | [[Approval Modes]] |
| 2 | Kill switch not engaged | reject | [[Kill Switch]] |
| 3 | Symbol on the allow-list | reject | [[Risk Envelope]] |
| 4 | Inside the permitted session window | reject | [[Risk Envelope]] |
| 5 | Order is well-formed: valid stop, non-zero size, sane price vs. market | reject | fat-finger guard |
| 6 | Not a duplicate (idempotency key, and near-identical recent order) | reject | [[Order And Fill Schema]] |
| 7 | Position size ≤ max position % of equity | **resize** | [[Risk Envelope]] |
| 8 | Portfolio heat after this order ≤ max | **resize** | [[Risk Envelope]] |
| 9 | Correlated exposure ≤ max | **resize** | [[Agent — Regime And Correlation]] |
| 10 | Daily loss so far + worst case ≤ daily loss limit | reject | [[Trade Ledger]] |
| 11 | Prop-firm rules (if configured) | reject | [[Agent — Prop Firm Guard]] |
| 12 | Liquidity: size ≤ % of average daily volume | **resize** | market data |
| 13 | Broker buying power / margin sufficient | reject | [[Agent — Broker Adapter]] |
| 14 | Not within N minutes of a high-impact scheduled event (auto mode only) | reject | [[Agent — News And Catalyst]] |
| 15 | All execution-path components healthy (auto mode only) | reject → downgrade to confirm | [[Agent — Watchdog]] |

**Worst case, always.** Checks are computed against the full stop-out, not the
expected outcome.

## Output

```yaml
proposal_id: ord_prop_01J8XV
decision: resize                # approve | resize | reject
original_size: 192
approved_size: 120
binding_check: correlated_exposure
worst_case_loss: 312
worst_case_pct_equity: 0.31
checks:
  - { id: symbol_allowlist,   result: pass }
  - { id: session_window,     result: pass }
  - { id: max_position_pct,   result: pass,   headroom_pct: 3.8 }
  - { id: portfolio_heat,     result: pass,   after: 4.2, limit: 6.0 }
  - { id: correlated_exposure,result: resize, would_be: 12.4, limit: 10.0 }
  - { id: daily_loss,         result: pass,   used: 340, limit: 2000 }
  - { id: prop_firm,          result: pass,   tightest_headroom: 660 }
evaluated_at: 2026-08-29T14:31:02.104Z
elapsed_ms: 6
spoken_summary: "Approved at 120 shares instead of 192 — semis exposure is the constraint."
```

The `spoken_summary` matters. A silently-resized order teaches you nothing; a spoken
one teaches you where your book is concentrated.

## Rejection is a first-class outcome

A rejection is **information**, not an error. It is spoken, logged, and counted.
[[Observability]] tracks rejections by rule — the rule that binds most often tells
you where your process actually is, which is usually not where you think.

## Tools

`memory.read` (ledger, positions, envelope) · `market-data.quote` · `taskbus.publish`

Reference implementations ([[Trading Corpus Index]]): `nautilus_trader/risk/` for a
correct pre-trade risk engine; `freqtrade/plugins/protections/` for cooldown,
stoploss-guard, low-profit-pairs, and max-drawdown protection patterns.

## Testing — mandatory

Every check gets a test that **tries to violate it**, and a test that confirms a
legitimate order passes. Additionally:

- A test asserting no code path reaches [[Agent — Broker Adapter]] without a
  recorded approval for that exact proposal id
- A test that an unevaluable rule (missing data) rejects rather than passes
- A test that a human dashboard order is checked identically to an agent order
- A fuzz test over malformed proposals — nothing crashes, everything rejects

## Acceptance criteria

- p99 latency under 50 ms.
- 100% of orders reaching the broker have a recorded approval.
- Works with every LLM endpoint unreachable.
- Every rejection reason is human-readable and spoken.
- Missing data → reject, proven by test.

## Related

[[Risk Envelope]] · [[Safety Invariants]] · [[Approval Modes]] · [[Kill Switch]] ·
[[Agent — Order Manager]] · [[Agent — Prop Firm Guard]] · [[Execution Family]]
