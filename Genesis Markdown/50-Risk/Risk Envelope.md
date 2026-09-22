---
title: Risk Envelope
tags: [risk, schema]
status: building
implemented_by: [src/genesis/config.py, src/genesis/marketdata/universe.py, tests/marketdata/test_universe.py]
---

# Risk Envelope

The signed set of hard limits every order is checked against. Changing it is a
deliberate, logged, human act — never a voice command, never an agent decision.

**A change takes effect on the next proposal, not the next restart**
(`config.LiveConfig`, 2026-09-17). Editing `~/.genesis/config.yaml` is still the
only door, and it is still a human act with a file behind it — but tightening a
limit mid-session now works, because a limit that needs a restart is one nobody
tightens during the drawdown that called for it. An invalid edit leaves the
limits already in force standing. See [[Config And Secrets]].

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

## Futures limits (2026-09-13)

Open Questions §1 moved v1 to CME futures, where a percentage of equity against
one contract's notional is not a limit anyone can reason about (one NQ is
~$590k). Added to the `risk:` block, validated in `genesis.config.Risk`:

```yaml
symbol_allowlist: [ES, NQ, MES, MNQ, RTY, M2K, YM, MYM]   # contract roots
max_contracts_per_symbol: 2
max_daily_loss_usd: 2000
max_price_deviation_pct: 2.0      # fat-finger band against the arrival quote
```

`session_window` stays for equities; futures use the contract's own trading
hours as IBKR reports them. Not yet built: envelope signing and versioning,
weekly loss, max drawdown, per-strategy envelopes.

## The equity universe (2026-09-20)

A news brief names `SPY`, `NVDA`, `CVX` — never `MNQ`. With a futures-only
allow-list, *every* idea the news pipeline produced was refused before it could
be sized, which made the whole path decorative.

```yaml
equity_universe: true    # adds the S&P 500 and the core ETFs to the roots above
```

Membership is **resolved in advance, into a file**, by `genesis universe
refresh` — SSGA's daily SPY holdings, the same deterministic source
[[Index Movers]] uses. The gate keeps doing exactly what it did: one set
membership test.

> [!important] The allow-list check is a reflex, so it may not make a network call
> Resolving "the S&P 500" at check time would put an HTTP request with a
> timeout inside the fastest path in the system, on every order. A gate that
> cannot answer must fail closed, so a slow vendor would become a desk that
> cannot trade. The snapshot is written deliberately and read from disk.

**Both failure directions are closed.** A missing or unreadable snapshot yields
the futures roots plus the core ETFs — never "everything", and never an empty
list, which would refuse the futures the desk already trades. A snapshot older
than seven days is reported stale with its age: a company removed from the index
last month is one nobody meant to permit.

**"All ETFs" is not enumerable and the code does not pretend otherwise.** There
is no free, authoritative list of every US ETF, and a guess would be an
allow-list with holes — the worst shape for a safety control. `CORE_ETFS` is the
liquid set a brief actually names; anything else is added by hand.

> [!warning] `max_contracts_per_symbol` is a futures limit applied to shares
> An equity idea is currently sized to **2 shares**, because the cap that stops
> two NQ contracts is the same number. It is not dangerous — it errs small —
> but it is not a position either. Equity sizing wants the percent-of-equity
> rule the checks above already state; until then, sizes on equity ideas are
> honest and useless.

## Related

[[Pre-Trade Risk Engine]] · [[Safety Invariants]] · [[Approval Modes]] ·
[[Prop Firm Rules]] · [[Agent — Portfolio And Allocation]] · [[Config And Secrets]]
