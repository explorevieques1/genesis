---
title: Trade Journal Schema
tags: [schema, journal]
status: built
implemented_by: [src/genesis/journal/schema.py, src/genesis/journal/store.py, tests/journal/test_schema.py, tests/journal/test_store.py]
---

# Trade Journal Schema

One note per trade, at `30-Journal/YYYY/MM/`. Written automatically by
[[Agent — Trade Journal]]; the human section is yours.

## The split

**Machine fields** are populated automatically and never require your input.
**Human fields** are prompted once, after the close, and are entirely skippable.

A journal entry with zero human input is still useful. That's deliberate — journaling
fails for everyone because it demands effort at the worst possible moment.

## Schema

```yaml
---
type: journal
id: jrn_01J8XW
trace_id: tr_01J8XP

# ── Machine: identity ────────────────────────────────
symbol: NVDA
direction: long
strategy: nq_orb_v3
setup: orb_breakout
idea: idea_01J8XS
account: primary

# ── Machine: execution ───────────────────────────────
entry: { price: 121.06, ts: 2026-08-29T14:31:02Z, qty: 120, fill: fill_01J8XW }
exit:  { price: 124.20, ts: 2026-08-29T15:12:40Z, qty: 120, fill: fill_01J8XX,
         reason: target }          # target | stop | trail | time | manual | invalidation
duration_min: 41
bars_held: 8

# ── Machine: risk and result ─────────────────────────
planned_stop: 118.40
planned_target: 124.50
planned_rr: 2.1
risk_dollars: 312.00
pnl_gross: 376.80
fees: 1.20
pnl_net: 375.60
r_multiple: 1.20
mae_r: -0.31                       # worst point against you
mfe_r: 1.34                        # best point in your favour
portfolio_heat_at_entry: 0.32

# ── Machine: context ─────────────────────────────────
regime: risk-on
session_segment: "14:30-15:30"
day_of_week: thursday
markup_entry: ms_01J8XR4K
markup_exit:  ms_01J8XY2C
chart_entry: 20-Charts/NVDA-2026-08-29-entry.png
chart_exit:  20-Charts/NVDA-2026-08-29-exit.png
slippage_bps: 3.3

# ── Machine: plan adherence (computed, not asked) ────
plan_adherence:
  entry_in_zone: true
  size_as_planned: false           # risk engine resized 192 → 120
  stop_as_planned: true
  stop_moved: false                # the most predictive field in the schema
  exit_as_planned: true
  deviations: []
plan_followed: true

# ── Human: yours ─────────────────────────────────────
emotion_entry: calm                # calm | eager | hesitant | fomo | frustrated
emotion_hold: calm
confidence_felt: 0.7               # vs. the system's 0.72
followed_plan: true
what_i_thought: ""
what_id_do_differently: ""
notes: ""

tags: [semis, orb, breakout, winner]
---
```

Then, in the note body: the **thesis copied verbatim** from the idea, both charts
embedded, and links to the strategy, the specs, and any lesson derived from this trade.

## Why the thesis is copied verbatim

Not summarised, not re-worded. Six months later you need to read what you *believed
at the time*, not a tidied version of it. Memory reliably rewrites the thesis of a
losing trade into something more reasonable than it was.

## `stop_moved` — the important field

Computed from the [[Trade Ledger]], never self-reported, because self-reporting on
this particular behaviour is unreliable in a way that is entirely human and entirely
predictable.

It is the single most predictive input to [[Agent — Insight Miner]]. "You moved your
stop against yourself on 3 of the last 5 losers" is the kind of finding that changes
behaviour, and it's only available because the field is computed.

## Human field prompting

- Asked **once**, after the close — never during the trade
- By voice, answered by voice, transcribed
- Fully skippable, with no nagging and no follow-up
- `confidence_felt` vs. the system's `confidence` is quietly valuable: divergence
  over time tells you whether to trust the system's scoring or your own read

## Dataview queries this enables

````
```dataview
TABLE symbol, r_multiple, setup, plan_followed, emotion_entry
FROM #journal WHERE date >= date(today) - dur(30 days) SORT r_multiple ASC
```

```dataview
TABLE setup, length(rows) AS n, sum(rows.r_multiple) AS total_r
FROM #journal GROUP BY setup SORT total_r DESC
```
````

## Related

[[Agent — Trade Journal]] · [[Agent — Insight Miner]] · [[Agent — Performance Analyst]] ·
[[Idea Schema]] · [[Obsidian Vault Schema]] · [[Data Model Overview]]
