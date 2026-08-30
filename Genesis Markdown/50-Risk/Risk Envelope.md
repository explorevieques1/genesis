---
title: Risk Envelope
tags: [risk, schema]
status: spec
implemented_by: []
---

# Risk Envelope

The signed set of hard limits every order is checked against. Changing it is a
deliberate, logged, human act — never a voice command, never an agent decision.

## The envelope

```yaml
envelope:
  version: 7
  signed_at: 2026-08-20T09:00:00Z
  signed_by: human
  account: primary

  # Position level
  max_position_pct: 5.0            # single position as % of equity
  max_risk_per_trade_pct: 1.0      # (entry − stop) × size, as % of equity
  max_liquidity_pct_adv: 1.0       # size as % of average daily volume

  # Portfolio level
  max_portfolio_heat_pct: 6.0      # Σ open risk as % of equity
  max_gross_exposure_pct: 100.0
  max_correlated_exposure_pct: 10.0  # per correlation cluster
  max_open_positions: 8
  min_effective_positions: 2.0     # from [[Agent — Regime And Correlation]]

  # Loss limits
  max_daily_loss_pct: 2.0
  max_weekly_loss_pct: 5.0
  max_drawdown_pct: 10.0           # from high-water; breach → halt

  # Scope
  symbol_allowlist: [NVDA, AMD, AVGO, SPY, QQQ]
  symbol_blocklist: []
  asset_classes: [equity]
  session_window: { start: "09:45", end: "15:45", tz: America/New_York }
  allow_overnight: false
  allow_earnings_hold: false

  # Event guards
  block_minutes_before_high_impact: 30
  block_minutes_after_high_impact: 15

  # Lesson-derived hard limits (see [[Agent — Insight Miner]])
  hard_limits:
    - id: lesson_01J8XY
      rule: "after 2 consecutive losses, max_risk_per_trade_pct = 0.5"
      approved_at: 2026-08-22T18:00:00Z

  prop_firm: null                  # or a [[Prop Firm Rules]] block
```

## Reading the limits

| Limit | Catches |
|---|---|
| `max_position_pct` | One position becoming the whole account |
| `max_risk_per_trade_pct` | Wide stops turning a normal-looking size into a huge risk |
| **`max_portfolio_heat_pct`** | The aggregate. The one that matters most — five 1% risks is a 5% day. |
| `max_correlated_exposure_pct` | "Diversified" across five semis |
| `min_effective_positions` | The same thing, measured properly — see [[Agent — Regime And Correlation]] |
| `max_daily_loss_pct` | The bad day |
| `max_drawdown_pct` | The bad month |
| `session_window` | Trading at times you have no edge |
| Event guards | Being long into a print you didn't check |

**Worst case, always.** Every check is computed against the full stop-out, not the
expected outcome. This is the single most common sizing error and the envelope is
where it gets caught.

## Signing and versioning

- Every change increments `version` and records who, when, and what changed
- The envelope is signed; [[Pre-Trade Risk Engine]] verifies the signature and
  refuses to operate on an unsigned or mutated one
- Old versions are retained — [[Observability]] can answer "what were the limits when
  that trade was taken?"
- An unsigned envelope is a `fatal` condition, not a warning

## Who can change it

| Actor | Tighten | Loosen |
|---|---|---|
| You, in the [[Dashboard]] | ✅ | ✅ (logged, confirmed) |
| You, by voice | ✅ | ❌ |
| An agent | ✅ (with reason) | ❌ **never** |
| [[Agent — Insight Miner]] | proposes a `hard_limit`, you approve | ❌ |

Tightening is always allowed because it's always safe. Loosening is the dangerous
direction and requires the surface with the most friction.

## Per-strategy envelopes

A strategy may declare a **stricter** envelope than global. The effective limit is
always `min(global, strategy)`. A strategy can never widen a global limit — a new
strategy under [[Paper To Live Promotion]] typically runs at a fraction of the
global envelope until it earns more.

## Breach behaviour

| Breach | Response |
|---|---|
| Position / heat / correlation | **Resize** the order down |
| Symbol, session, event guard | **Reject** |
| Daily loss | Reject; at the limit → [[Kill Switch]] `halt` |
| Weekly loss | Reject new entries; positions kept |
| Max drawdown | `halt` + alert; requires human review to resume |
| Prop-firm rule | Reject; see [[Prop Firm Rules]] |

## Acceptance criteria

- Every limit has a test that tries to exceed it and asserts the correct response.
- An unsigned or mutated envelope prevents any order from being approved.
- Loosening via voice or via an agent fails, tested for both.
- Per-strategy envelopes correctly compute as `min(global, strategy)`.
- Portfolio heat is computed correctly with mixed long/short and multiple stops.

## Related

[[Pre-Trade Risk Engine]] · [[Safety Invariants]] · [[Approval Modes]] ·
[[Prop Firm Rules]] · [[Agent — Portfolio And Allocation]] · [[Config And Secrets]]
