---
title: Prop Firm Rules
tags: [risk]
status: spec
implemented_by: []
---

# Prop Firm Rules

Funded-account rule sets, encoded as hard constraints. Enforced by
[[Agent — Prop Firm Guard]] inside [[Pre-Trade Risk Engine]].

Active only when `risk.prop_firm` is configured. See [[Open Questions]] §2.

## Why these are different from normal risk limits

A normal risk breach costs you money. A prop-firm breach costs you **the account**,
including the evaluation fee and every dollar of profit not yet withdrawn. The
asymmetry justifies treating every rule as a wall with margin, not a limit to
approach.

Practical consequence: the guard should keep you meaningfully *away* from the line,
not right up against it. A configurable safety buffer (default 20% of headroom) is
subtracted before the check.

## The rule shapes

### Daily loss limit
Maximum loss from the day's starting equity, or from the day's high-water mark
depending on the firm — **get this right per firm, it's a real difference.**

Resets at the firm's reset time, in the **firm's** timezone, including DST. A daily
limit that resets at the wrong hour is worse than no limit.

### Trailing max drawdown
The one that kills accounts.

A floor that trails your account's high-water mark. The critical detail: some firms
trail on **unrealized** equity (your intraday peak counts, even if you gave it back)
and others on **realized** balance only. Encoding this wrong means the guard reports
headroom you don't have.

```
floor = high_water_mark − trailing_amount
headroom = current_equity − floor
```

At some firms the floor stops trailing once it reaches the starting balance plus the
profit target. Encode that too.

### Profit target
Required to pass an evaluation phase. Reaching it changes the account's phase and
therefore its rules — the guard must handle phase transitions, not just a static
rule set.

### Consistency rule
No single day may exceed X% of total profit. Silently violated by one great day,
which is a genuinely counterintuitive failure — you can pass every risk rule, make
money, and fail the evaluation.

The guard should warn *proactively* when a day is approaching the consistency
threshold: "You're up 900 today. Another 200 and you'd breach consistency."

### Position and contract limits
Hard caps, often scaled to account size. Simple to encode, easy to forget.

### Session restrictions
No holding through news, no overnight positions, flat by a specific time. Some firms
auto-liquidate; some just fail you.

### Minimum trading days
An availability requirement, not a risk one — but it belongs in the same record so
the dashboard can show it.

## Encoding source

`PropForge` in the corpus ([[Trading Corpus Index]]) is a browser-based prop-firm
challenge simulator implementing FTMO / TopStep / Apex phases, daily loss, max
drawdown, and profit targets.

**Borrow its rule encodings.** Deriving these from a firm's marketing page is how
you end up with a subtly wrong trailing-drawdown formula and a blown account.
Verify each encoding against hand-worked examples from the firm's actual rule
document before trusting it.

## Integration points

| Component | Role |
|---|---|
| [[Agent — Prop Firm Guard]] | Computes headroom continuously; vetoes orders |
| [[Pre-Trade Risk Engine]] | Check #11 — the veto is applied here |
| [[Risk Envelope]] | The `prop_firm` block; effective limits are `min(envelope, prop)` |
| [[Agent — Portfolio And Allocation]] | Sizing constrained by the tightest prop headroom |
| [[Kill Switch]] | `breach_imminent` is a trigger |
| [[Voice UX]] | Headroom spoken at the open and on every warning |

## Multi-account

If you run a personal account alongside a funded one, every rule is per-account.
[[Trade Ledger]] and [[Risk Envelope]] must key on `account_id` from day one — cheap
now, painful to retrofit. See [[Open Questions]] §10.

## Acceptance criteria

- Trailing drawdown verified against hand-worked examples for each firm's actual
  rules, including the realized-vs-unrealized variants.
- Daily reset fires at the firm's time in the firm's timezone, DST included.
- Phase transition (evaluation → funded) correctly changes the active rule set.
- Consistency warning fires before the breach, not after.
- An order whose **full stop-out** would breach any rule is rejected, tested per rule.
- The safety buffer is applied — the guard blocks before the actual line.

## Related

[[Agent — Prop Firm Guard]] · [[Risk Envelope]] · [[Pre-Trade Risk Engine]] ·
[[Kill Switch]] · [[Trading Corpus Index]] · [[Open Questions]]
