---
title: Agent — Prop Firm Guard
tags: [agent, strategy, risk]
family: strategy
cadence: market-open, event
tier: none
status: spec
implemented_by: []
---

# 🏦 Agent — Prop Firm Guard

## Purpose

Encode a funded-account rule set as **hard constraints** and block anything that
would breach them. On a prop account, a rule breach doesn't cost you a trade — it
costs you the account. This agent treats every rule as a wall, not a guideline.

Active only when `risk.prop_firm` is configured ([[Config And Secrets]]).

## Cadence

- `market-open` continuously — the trailing drawdown moves with equity, so the
  distance to the wall changes on every tick
- `event` on every order proposal and every fill
- `cron` at session boundaries — reset daily counters correctly for the firm's timezone

## Rule sets

Configured per firm. The parameters differ; the shapes do not.

| Rule | Typical shape | Notes |
|---|---|---|
| **Daily loss limit** | Max loss from the day's starting equity (or high-water) | Resets at the firm's reset time, in the firm's timezone — not yours |
| **Trailing max drawdown** | Floor that trails the account high-water mark | The one that kills accounts. Trails on **unrealized** equity at some firms and **realized** at others — get this exactly right per firm. |
| **Profit target** | Required to pass an evaluation phase | Passing ends the phase; behaviour changes after |
| **Consistency rule** | No single day may be more than X% of total profit | Silently violated by one great day |
| **Max position / contracts** | Hard cap, often scaled by account size | |
| **Session restrictions** | No holding through news, no overnight, flat by close | Some firms auto-liquidate |
| **Minimum trading days** | Must trade N distinct days | An availability rule, not a risk rule |

Corpus reference: `PropForge` (see [[Trading Corpus Index]]) implements FTMO /
TopStep / Apex phases, daily loss, max drawdown, and profit targets — borrow the
rule encodings rather than re-deriving them from marketing pages.

## Outputs

A continuously updated **headroom record**:

```yaml
firm: topstep
account_size: 50000
phase: funded
as_of: 2026-08-29T14:31:00Z
daily_loss:
  limit: 1000
  used: 340
  headroom: 660
  resets_at: "2026-08-29T18:00:00-05:00"
trailing_drawdown:
  high_water: 52400
  floor: 50400            # high_water − 2000
  current_equity: 51820
  headroom: 1420
  trails_on: unrealized
consistency:
  limit_pct: 50
  best_day_pct_of_profit: 38
  status: ok
position_limit: { max_contracts: 5, current: 2 }
status: ok                # ok | warning | blocked
blocked_reason: null
```

Emits `propfirm.warning` at a configurable headroom threshold and
`propfirm.breach_imminent` when the next stop-out would breach.

## The veto

This agent has **hard veto power** inside [[Pre-Trade Risk Engine]]. An order is
rejected if:

- Its worst case (full stop loss) would breach the daily loss limit
- Its worst case would breach the trailing drawdown floor
- It exceeds the position/contract cap
- It falls outside a permitted session
- It would be held into a prohibited event or overnight

Note **"worst case"**: the check is against the full stop-out, not the expected
outcome. Sizing to your expected loss is how accounts die.

## Tools

`memory.read` (ledger, positions) · `market-data.quote` · `taskbus.publish`

No LLM ([[LLM Model Tiers]]). No exceptions — this is a rules engine.

## Memory namespace

Read: `ledger`, `shared`
Write: `prop-firm-guard`

## Voice behaviour

Headroom should be **spoken proactively**, not looked up:

- At the open: "TopStep account. Daily loss headroom, one thousand. Trailing floor
  at fifty thousand four hundred."
- On a warning: "Careful — six hundred left on the daily loss limit. One more
  full stop and you're at three hundred."
- On `breach_imminent`: interrupt whatever is playing and say it.

## Acceptance criteria

- Trailing drawdown computed correctly for realized-vs-unrealized firm variants,
  verified against hand-worked examples from each firm's actual rules.
- Daily reset fires at the firm's reset time in the firm's timezone, including DST.
- An order whose full stop-out would breach any limit is rejected — tested for
  every rule independently.
- Headroom updates within 1 s of a fill.
- Runs with all LLM backends down.

## Related

[[Pre-Trade Risk Engine]] · [[Risk Envelope]] · [[Prop Firm Rules]] ·
[[Agent — Portfolio And Allocation]] · [[Kill Switch]] · [[Strategy Family]]
