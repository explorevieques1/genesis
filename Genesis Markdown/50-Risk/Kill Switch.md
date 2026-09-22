---
title: Kill Switch
tags: [agent, execution, risk, core]
family: execution
cadence: event
tier: none
status: building
implemented_by: [src/genesis/execution/killswitch.py, src/genesis/execution/halt.py, ui/src/components/KillSwitch.tsx]
---

# 🛑 Kill Switch

## Purpose

Stop everything, now. Cancel all working orders, optionally flatten all positions,
set mode to [[Approval Modes|`halt`]].

**It must work when everything else is broken.** That is its entire design brief.

## Design constraints — non-negotiable

1. **Separate process.** Not an agent in the fleet. Not supervised by the same
   supervisor. If the daemon is wedged, the kill switch still runs.
2. **No LLM in the path.** Not for the trigger, not for the decision, not for the
   execution. ([[LLM Model Tiers]])
3. **No dependency on the [[Task Bus]].** It calls the broker directly through
   [[Agent — Broker Adapter]].
4. **Multiple independent triggers.** Any one of them alone must work.
5. **Idempotent.** Firing it five times is the same as firing it once.
6. **Sub-second.** Working orders cancelled in under 1 second.

## Triggers

| Trigger | Path |
|---|---|
| Voice: "Genesis, halt" / "stop trading" / "flatten" | Recognized in [[10-Architecture/Voice Stack]] **before** intent classification — it does not wait for an LLM |
| [[Dashboard]] button | Direct HTTP to the kill-switch process, not through the bus |
| Global hotkey | [[Desktop Shell]] |
| Daily loss limit breached | [[Agent — Position And PnL Accountant]] |
| Prop-firm breach imminent | [[Agent — Prop Firm Guard]] |
| Reconciliation failure | [[Agent — Position And PnL Accountant]] |
| Ledger inconsistency | [[Trade Ledger]] |
| Broker unreachable with open positions | [[Agent — Broker Adapter]] |
| Runaway detection: N orders in M seconds | kill-switch process itself |
| Process-level: SIGTERM to the daemon | shutdown handler |

That last self-trigger matters — a bug that places orders in a loop is stopped by
the kill switch even if no other component notices.

## Levels

| Level | Action |
|---|---|
| `halt` (default) | Cancel all working orders. Keep positions. Mode → `halt`. Stops that protect positions **remain**. |
| `flatten` | Everything in `halt`, plus close all open positions at market. |

**Default is `halt`, not `flatten`.** Flattening is itself a risky act — it converts
unrealized losses to realized ones at whatever price the market offers, possibly the
worst price of the day. It requires explicit intent: "Genesis, flatten everything."

Protective stops are never cancelled by `halt`. Cancelling the stops on open
positions in an emergency is precisely backwards.

## Sequence

```
1. Set mode = halt                          (immediate, in-memory + persisted)
2. Reject any in-flight proposals            (they fail closed)
3. Cancel working orders — parallel, excluding protective stops
4. Verify cancellation by querying broker state
5. If flatten: close positions at market, verify
6. Speak confirmation with the actual numbers
7. Write a halt record to the [[Episodic Log]]
8. Notify every surface: voice, dashboard, desktop, push
```

Step 4 matters. A cancel request that was sent is not a cancel that happened —
verify against broker state, and if verification fails, say so loudly rather than
reporting success.

## Spoken confirmation

Always speaks, always with real numbers, never a bare "done":

> "Halted. Four working orders cancelled. Two positions still open — 120 NVDA and
> 200 AMD, both with stops in place. Net down 340 today."

If flattening:

> "Flattened. Both positions closed. NVDA out at 122.10, AMD at 141.80. Day closed
> down 512."

## Recovery

Leaving `halt` is deliberate and manual:

- Requires a human action in the [[Dashboard]] — **not** a voice command, and never
  an agent decision ([[Approval Modes]] loosening rule)
- Reconciliation must pass first
- The triggering condition must be resolved, and the resolution recorded
- Resuming into [[Approval Modes|`auto-within-limits`]] directly is not permitted —
  you resume into `confirm` and step up from there

## Testing — the most important tests in the system

- Fires correctly with the LLM endpoints unreachable
- Fires correctly with the daemon process hung (`SIGSTOP` the daemon, then trigger)
- Fires correctly with the [[Task Bus]] database locked
- Cancels in under 1 s with 50 working orders
- Protective stops survive `halt`
- Idempotent under 10 concurrent triggers
- The voice trigger works while TTS is speaking (barge-in path, [[10-Architecture/Voice Stack]])
- Verification catches a cancel that silently failed

Run these tests on every release. If the kill switch is broken, nothing else in
Genesis is safe to run.

## Implementation (2026-09-14)

`python -m genesis.execution.killswitch` (or `genesis killswitch serve`;
`genesis serve` starts one detached if none answers). Loopback HTTP on
`execution.killswitch_port` (8766): `GET /health`, `POST /halt`,
`POST /flatten`. Its own IBKR client id. The flag is
`<execution.state_dir>/halt.json`, which the order manager reads every tick.

Three facts measured against the paper gateway shaped it, and they change the
design above:

1. **Only the placing client may cancel an order** (IBKR 10147). So `halt`
   raises the flag, lets the order manager cancel its own entries, and after
   ~0.15–0.9 s checks the broker with a *fresh* request. Only if an entry is
   still working (the daemon is wedged) does it escalate: note the stops,
   global-cancel, re-place the stops under its own client id. Measured: healthy
   daemon 225–300 ms; wedged daemon 1.4 s including re-verification.
2. **IBKR cancels a whole OCA group when one member is cancelled.** Cancelling
   a target took its stop down with it. So `halt` cancels **entries** and keeps
   every exit order on an open position — targets as well as stops. This
   deviates from "cancel all working orders except protective stops", on the
   safe side: an exit can only reduce risk.
3. **Another client's cancellations are not pushed** to this client, so its
   cached open-order list goes stale. Every decision reads a fresh
   `reqAllOpenOrders()` (≈5 ms).

`flatten` global-cancels, closes every position at market (contracts qualified
by id — a position's contract has no exchange), and verifies flat: 734–751 ms
measured. Only the kill switch closes positions on a flatten; the order
manager only cancels, so both can never sell.

Not built: runaway detection, the voice trigger before intent classification,
the desktop hotkey, spoken confirmation.

## Related

[[Approval Modes]] · [[Pre-Trade Risk Engine]] · [[Safety Invariants]] ·
[[Agent — Broker Adapter]] · [[Risk Envelope]] · [[Execution Family]]
