---
title: Agent — Screener
tags: [agent, research]
family: research
cadence: market-open
tier: small
status: building
implemented_by: [src/genesis/screener/snapshot.py, src/genesis/screener/scan.py, src/genesis/screener/chat.py, src/genesis/agents/research/screener.py, src/genesis/screener/__init__.py, tests/test_screener.py]
---

# 🔎 Agent — Screener

## Purpose

Mechanical candidate generation. Runs saved scans across the universe and returns
symbols that meet a condition **right now**. It does not rank, does not form a
thesis, does not decide. That separation is deliberate — it keeps the scan fast,
cheap, deterministic, and testable.

## Built first: the fundamentals screener (2026-09-14)

The technical scans below are still spec. What exists is a **fundamentals screen
over the S&P 500**, driven by conversation — decided with the operator, and it
settles [[Open Questions]] §8 for this agent.

- **Universe** — SPY's daily holdings file (same source as [[Index Movers]]),
  sectors from which sector SPDR holds the name. Never model memory.
- **Snapshot** — `screener.db` beside the other stores: one row per member from
  yfinance `.info`, rebuilt by the `screener` agent (tier none, `market-closed`,
  daily) or `scr refresh`. ~20 s for 503 names. Replaced only when ≥90% of members
  come back, otherwise yesterday's stays.
- **Units** are normalised at the snapshot: ratios in percent, sizes in $B.
  yfinance mixes fractions and percents; the model and a typed scan must mean the
  same thing by "10".
- **Fields** — a closed catalogue (`snapshot.FIELDS`): valuation (P/E trailing and
  forward, PEG, P/B, P/S, EV/EBITDA), EPS, revenue, growth, margins, ROE/ROA,
  debt/equity, current ratio, FCF and FCF yield, dividend yield and payout, beta,
  52-week change and distance from high, short interest, institutional ownership,
  analyst rating and target upside; text fields sector, industry, name.
- **Scan** — `{criteria: [{field, op, value}], sort, limit}`, validated against the
  catalogue. Unknown field, operator or sector is refused with the reason. **An
  absent value never passes** and is counted in the result. A snapshot older than
  80 h is `degraded`.

### Conversation

The small tier's only job is interpretation. Given the message, the previous
scans in the Ask Genesis conversation, and the catalogue, it returns one JSON
object: `understood` (the idea behind the words), `scan`, `readings` (how each
vague word was read — "cheap → pe_forward < 15"), `unsupported` (what no field can
express, with the reason), and at most one `question` with tap-to-send `choices`.
Code runs the scan; the model never sees rows or names results.

- Refinements edit the previous scan ("only tech", "loosen P/E to 25").
- A proposed scan that fails validation gets **one** repair call with the error,
  then fails as degraded — never repaired by guessing.
- Zero matches or more than 40 adds a deterministic honing question.
- `not_screen` hands the sentence to the analyst ladder.
- Routing: the command table's `screen` entry catches "find/which … stocks|companies",
  "screen", "scan" and `scr`. Inside an Ask Genesis conversation, an unmatched
  sentence following a `screen.*` reply stays with the screener; any other table
  command ends the thread.

**Current screen:** every result is saved as the one current screen and the
interpreter is always shown it, so "refine the current screen: …" edits it with
or without chat history, and a hand edit in [[Screener|SCR]] is what the next
message refines. A different idea replaces it.

**Parity:** `scr pe_forward<15 revenue_growth>10 sector=technology sort:-roe top:20`
builds the same scan with no model (`~` contains, `!=` excludes, `=a,b` is *in*,
`=lo..hi` is *between*). `scan.terms()` writes any scan back out in this grammar. With no small tier this is
the whole screener, and the reply says so.

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
[[Research Family]] · [[Screener]] · [[Trading Corpus Index]]
