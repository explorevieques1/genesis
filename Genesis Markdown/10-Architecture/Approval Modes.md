---
title: Approval Modes
tags: [architecture, risk]
status: spec
implemented_by: []
---

# Approval Modes

How much autonomy execution has. Set globally; can be tightened per strategy, never
loosened per strategy.

This is the **policy** gate. [[Pre-Trade Risk Engine]] is the **numbers** gate.
An order must pass both. Neither can be skipped.

---

## The four modes

### `advisory`
Agents may research, chart, backtest, and **draft** orders. No order reaches a
broker. Drafts appear in the [[Dashboard]] approval queue and in the vault.

Use for: development, a new strategy's first days, any time you're unsure.

### `confirm` — **default**
A live order requires a spoken confirmation that **names the ticker and the size**.

```
🤖 "NVDA long, 40 shares, stop 118.40, risk 92 dollars, 0.9% of equity. Confirm?"
👤 "Confirm NVDA 40."
🔔 [earcon: trade placed]
🤖 "Filled 40 NVDA at 121.06."
```

Rules:
- Confirmation **expires in 60 seconds**. After that the price has moved; re-propose.
- A bare "yes" is **not** enough — the ticker must be spoken back. This prevents
  a stray "yeah" in ambient conversation from placing a trade.
- Confirmation can also be given by clicking in the [[Dashboard]] approval queue.
- The proposal read aloud always includes: side, symbol, size, stop, dollar risk,
  and risk as % of equity.

### `auto-within-limits`
Orders execute automatically **iff** every condition holds:

- Strategy has passed [[Paper To Live Promotion]]
- Symbol is on the allow-list in [[Risk Envelope]]
- Inside the permitted session window
- Position size, portfolio heat, daily loss, and correlation all within envelope
- [[Agent — Watchdog]] reports all execution-path components healthy
- Not within N minutes of a high-impact scheduled event (from [[Agent — News And Catalyst]])

Everything is logged and **spoken after the fact** ("Took NVDA long, 40 shares,
per the ORB setup"). Any single failed condition demotes that order to `confirm` —
it does not silently drop.

### `halt`
Kill switch engaged. No new orders from anyone. Optional flatten-all. Agents drop
to research-only and keep gathering, so you lose execution, not awareness.

Triggered by: voice ("Genesis, halt"), [[Dashboard]] button, a breached hard limit,
a failed daily reconciliation, or a [[Agent — Watchdog]] fatal. See [[Kill Switch]].

---

## Mode transitions

```
   advisory ──► confirm ──► auto-within-limits
       ▲           ▲                │
       └───────────┴────────────────┘
                   │
              any ──► halt   (always allowed, always instant)
```

- **Loosening** (toward more autonomy) requires an explicit, logged human action and
  cannot be done by voice alone — it needs the [[Dashboard]]. An LLM can never
  loosen a mode.
- **Tightening** can be done by anything, at any time, including agents.
- `halt` is reachable from any state, instantly, without the LLM path.

## Per-strategy override

A strategy may declare a *stricter* mode than global:

```yaml
strategy: nq_orb_v3
approval_mode: confirm   # even when global is auto-within-limits
```

The effective mode is always `min(global, strategy)` on the autonomy scale.

## What each mode allows

| Capability | advisory | confirm | auto | halt |
|---|:--:|:--:|:--:|:--:|
| Research, scan, chart | ✅ | ✅ | ✅ | ✅ |
| Backtest, optimize | ✅ | ✅ | ✅ | ✅ |
| Write to vault / memory | ✅ | ✅ | ✅ | ✅ |
| Draft an order | ✅ | ✅ | ✅ | ❌ |
| Place an order | ❌ | with spoken confirm | ✅ within envelope | ❌ |
| Modify / cancel own order | ❌ | ✅ | ✅ | cancel only |
| Manage an open position (stops, partials) | ❌ | ✅ | ✅ | flatten only |

Note the last row: in `halt` you can still **reduce** risk, never add it.

## Acceptance criteria

- In `advisory`, no code path can reach the broker. Prove it with a test that
  asserts the broker adapter is never called.
- A bare "yes" in `confirm` mode never places a trade.
- A confirmation older than 60 s is rejected with a re-quote.
- Loosening the mode from a voice command alone fails.
- `halt` from any mode cancels all working orders in under 1 s.

## Related

[[Pre-Trade Risk Engine]] · [[Risk Envelope]] · [[Kill Switch]] ·
[[Paper To Live Promotion]] · [[Safety Invariants]] · [[Orchestrator]]
