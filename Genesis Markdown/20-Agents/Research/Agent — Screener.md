---
title: Agent — Screener
tags: [agent, research]
family: research
cadence: market-open
tier: small
status: spec
implemented_by: []
---

# 🔎 Agent — Screener

## Purpose

Mechanical candidate generation. Runs saved scans across the universe and returns
symbols that meet a condition **right now**. It does not rank, does not form a
thesis, does not decide. That separation is deliberate — it keeps the scan fast,
cheap, deterministic, and testable.

## Cadence

- `market-open` every 1–5 min (interval scales with universe size and feed latency)
- `on-demand` — "Genesis, scan semis for breakouts"

## Inputs

- Universe (watchlist / sector / index — see [[Open Questions]] §8)
- Saved scan definitions
- OHLCV + intraday bars
- Structural levels from `mcp-market-data-server` (volume profile, ORB, FVG)

## Saved scans (starting set)

| Scan | Condition sketch |
|---|---|
| `orb_breakout` | Price closes above the opening-range high on ≥1.5× average volume |
| `gap_and_go` | Gap ≥2% holding above the gap fill 15 min in |
| `unusual_volume` | Relative volume ≥3× at this time of day |
| `breakout_52w` | New 52-week high with a ≥10-day base |
| `mean_reversion` | ≥2σ below the 20-day band in an established uptrend |
| `vwap_reclaim` | Reclaims session VWAP after being ≥1% below |
| `fvg_fill` | Price entering an unfilled fair value gap |
| `range_edge` | At the boundary of a well-defined multi-day range |
| `relative_strength` | Outperforming its sector by ≥2σ over 5 days |
| `earnings_drift` | 1–5 days post-beat, holding above the earnings gap |

Scans are **data**, not code — defined declaratively so you can add one by voice
("Genesis, add a scan for…") and [[Agent — Strategy Author]] can generate them.

## Outputs

```yaml
scan: orb_breakout
as_of: 2026-08-29T14:35:00Z
universe: watchlist(52)
candidates:
  - symbol: NVDA
    trigger_price: 121.06
    rel_volume: 2.4
    context: { orb_high: 120.90, atr14: 3.10, sector_rs: 0.81 }
  - symbol: AVGO
    trigger_price: 1642.00
    rel_volume: 1.7
    context: { orb_high: 1638.50, atr14: 41.20, sector_rs: 0.74 }
elapsed_ms: 1840
degraded: false
```

Emits `scan.hit` events so [[Agent — Idea Synthesizer]] can react without polling.

## Tools

`market-data.ohlcv` · `market-data.intraday` · `market-data.levels` ·
`mcp-market-data.volume_profile` · `mcp-market-data.orb` · `mcp-market-data.fvg` ·
`tradingview.screener` · `memory.write`

## Memory namespace

Read: `shared`, `screener`
Write: `screener`

## System prompt sketch

Mostly **not** an LLM job. The scans themselves are deterministic code — that's why
this agent is `small` tier rather than `large`. The LLM is used only for:

> Given a natural-language scan request, translate it into a scan definition using
> the available condition primitives. If the request cannot be expressed with the
> primitives, say exactly which part is unsupported rather than approximating it.
>
> Never invent a condition primitive that does not exist.

## Implementation notes

Vectorize. A 500-symbol scan is one dataframe operation, not 500 API calls — see
[[Trading Corpus Index]] → `vectorbt` for the parameter-sweep and indicator-factory
patterns. Cache bars by symbol+timeframe+bar-close; a scan re-running inside the
same bar should hit cache entirely.

Deduplicate via the [[Task Bus]] idempotency key so a busy event stream doesn't
queue the same scan four times.

## Acceptance criteria

- 500-symbol scan completes in <5 s from warm cache.
- Identical scan run twice in the same bar returns identical results and does no
  duplicate data fetching.
- A scan on stale data marks `degraded: true` rather than returning silently stale hits.
- Adding a scan by voice produces a valid, persisted definition — or an honest
  "I can't express that" with the specific reason.

## Related

[[Agent — Idea Synthesizer]] · [[Agent — Chart Markup]] · [[Agent — Strategy Author]] ·
[[Research Family]] · [[Trading Corpus Index]]
