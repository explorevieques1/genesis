---
title: Safety Invariants
tags: [risk, core]
status: spec
implemented_by: []
---

# 🔒 Safety Invariants

Ten rules. **The design is wrong if any of them breaks.** Each has a test whose job
is to try to violate it.

---

### 1. One gate, no bypass
Every order — agent, human, strategy, dashboard, API — passes
[[Pre-Trade Risk Engine]]. There is no fast path, no manual override, no "just this
once." Enforced structurally by [[genesis-execution-mcp]]: no tool exists that
places an order without an approval id.

**Test:** every order reaching [[Agent — Broker Adapter]] has a matching approval id.
Assert on 100% of fills.

### 2. The risk engine has no LLM in it
Rules, arithmetic, tests. It decides correctly with every model endpoint down.
([[LLM Model Tiers]])

**Test:** full risk-engine suite passes with all LLM backends unreachable.

### 3. Fail closed
Any ambiguity resolves toward not trading. A rule that cannot be evaluated is a
**rejection**. Unknown broker state means query before acting. An inconsistent
ledger means halt.

**Test:** force an unevaluable rule; assert rejection, not pass.

### 4. The kill switch works when everything else is broken
Separate process, no LLM, no task bus, multiple independent triggers, idempotent,
sub-second. ([[Kill Switch]])

**Test:** `SIGSTOP` the daemon, lock the queue database, kill the LLM endpoints —
the kill switch still cancels every working order in under a second.

### 5. Untrusted text is never instruction
Web, news, social, and third-party MCP content is fenced as data. An injection
attempt is logged and flagged, never followed. ([[MCP Gateway]])

**Test:** a prompt-injection eval set — zero injected instructions executed.

### 6. Paper and live share one code path
Differing only by credentials and a mode flag. Going live requires **two independent
actions**: the config change and the live credentials present. The mode is announced
at boot and displayed persistently. ([[Agent — Broker Adapter]])

**Test:** the full execution suite passes identically against paper and live-sandbox.

### 7. The ledger is append-only and reconciled
No `UPDATE`, no `DELETE`, enforced at the database level. Reconciled against the
broker daily. **Any mismatch is fatal** and halts the system. ([[Trade Ledger]])

**Test:** seeded mismatch halts within 5 s; an `UPDATE` against a fill fails.

### 8. Autonomy requires health
[[Approval Modes|`auto-within-limits`]] is permitted only when every execution-path
component is healthy, data is fresh, and no high-impact event is imminent. Any
degradation demotes to `confirm` — it never silently continues.
([[Agent — Watchdog]], [[Error Handling And Degradation]])

**Test:** degrade each execution-path component in turn; assert demotion each time.

### 9. Loosening autonomy is a human act
Moving toward more autonomy requires an explicit action in the [[Dashboard]], logged.
**Never by voice alone. Never by an agent.** Tightening can be done by anything, at
any time. ([[Approval Modes]])

**Test:** attempt to loosen the mode via voice and via an agent; both must fail.

### 10. Never confabulate
No invented price, level, position, or P&L. Degraded input produces labelled output.
"I can't reach the broker, so I can't confirm your position" is the correct answer.
([[Error Handling And Degradation]])

**Test:** cut the data feed; assert no numeric claim is made without a source or a
staleness label.

---

## Supporting rules

These aren't quite invariants, but violating them is how invariants eventually break:

- Agents never call each other directly — [[Task Bus]] or [[Memory Fabric]] only
- No safety-critical or arithmetic decision runs on an LLM
- `Decimal` for money, everywhere
- Every order carries an idempotency key; placements are never blind-retried
- A position is never held without a resting stop beyond a short grace period
- A stop modification that widens risk is re-checked by the risk engine
- Restart never resurrects a stale trade confirmation
- Single-writer memory namespaces, enforced server-side

## Review discipline

Any change touching the [[Execution Family]], [[Pre-Trade Risk Engine]],
[[Kill Switch]], [[Risk Envelope]], or [[Trade Ledger]]:

- Re-run the full invariant test suite — all ten, every time
- Re-read this note before merging
- If a change makes an invariant harder to hold, that's a design smell, not an
  acceptable trade-off

## Related

[[Pre-Trade Risk Engine]] · [[Kill Switch]] · [[Risk Envelope]] · [[Approval Modes]] ·
[[Trade Ledger]] · [[Error Handling And Degradation]] · [[Execution Family]]
