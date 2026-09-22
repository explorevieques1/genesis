---
title: Agent — Chart Markup
tags: [agent, charting]
family: charting
cadence: on-demand, event
tier: large
status: built
implemented_by: [src/genesis/agents/charting/chart_markup.py, src/genesis/charting/compose.py, tests/charting/test_agents.py]
---

# ✏️ Agent — Chart Markup

## Purpose

Given a symbol and a timeframe, work out what matters on the chart and say why.
Produces a [[Markup Spec]] — levels, zones, trendlines, structure — and a rendered
image.

This is the agent behind "Genesis, chart NVDA."

## Cadence

- `on-demand` — voice or dashboard request
- `event` — dispatched by [[Agent — Idea Synthesizer]] for top-ranked ideas; also on
  `level.touched` to re-mark after a structural break

## Inputs

- Symbol, timeframe(s), lookback
- OHLCV bars
- Structural computations: volume profile, ORB, FVGs, prior-period H/L
- Prior [[Markup Spec]] for the same symbol/timeframe (becomes the `parent`)
- Regime context from [[Agent — Market Analyst]] — a level means something different
  in a trending vs. ranging tape

## Outputs

1. A [[Markup Spec]] per [[Markup Spec Schema]], stored immutably in [[Memory Fabric]]
2. A rendered PNG at `20-Charts/SYMBOL-YYYY-MM-DD-TF.png`
3. A vault note linking the image, the spec, and any idea it supports
4. Level entities written to the [[Knowledge Graph]] as `level:SYMBOL:PRICE`
5. A spoken summary — one or two sentences naming **the** level that matters

## Level selection — the hard part

The failure mode is drawing forty lines. A chart with forty levels has none.

Selection rules:

- **Cap the output.** Maximum ~8 levels per chart. If more qualify, keep the strongest.
- **Strength is scored**, not asserted: number of touches × recency weight ×
  reaction magnitude × volume at the level.
- **Prefer confluence.** A price where the 200-day, the prior-day high, and the
  value-area high coincide is one strong level, not three weak ones — merge them
  and say so in the `why`.
- **Prefer proximity.** A level 30% away is noise for a day-trade timeframe. Weight
  by distance in ATR units, not percent.
- **Always include** prior-day/period high and low, session VWAP (intraday), and the
  nearest untested level above and below. These are cheap and always relevant.

Level types computed: support/resistance clusters, VWAP and anchored VWAP, ORB,
FVGs, volume profile POC and value area, prior-period H/L/C, Fibonacci from the
dominant swing, order blocks, fitted trendlines, key moving averages.
See [[Charting Engine]] for the sources.

## Tools

`market-data.ohlcv` · `market-data.intraday` · `mcp-market-data.volume_profile` ·
`mcp-market-data.orb` · `mcp-market-data.fvg` · `genesis-charting.compute_levels` ·
`genesis-charting.render` · `obsidian.write` · `memory.write`

## Memory namespace

Read: `shared`, `chart-markup`, `idea-synthesizer`, `market-analyst`, `knowledge-graph`
Write: `chart-markup`

## System prompt sketch

> You are the Chart Markup agent. You produce a [[Markup Spec]] describing what
> matters on this chart.
>
> **Restraint is the skill.** Eight levels maximum. A chart with forty lines
> communicates nothing. If two levels are within 0.25 ATR of each other, merge them
> into one and note the confluence.
>
> Every annotation needs a `why` a human would accept — "prior-day high, rejected
> twice intraday" not "resistance". Six months from now this note has to still make
> sense.
>
> Name **the** level in your spoken summary — the single price that decides the next
> move. If you can't pick one, the chart is unclear, and saying that is more useful
> than listing eight prices out loud.
>
> Levels are computed by tools, not estimated by you. Never state a price you did
> not receive from a tool call.

That last line matters: the LLM selects and explains levels; it does not compute them.

## Acceptance criteria

- Never produces more than the configured maximum annotations.
- Two levels within 0.25 ATR are merged with a confluence note.
- Every price in the output traces to a tool result — zero hallucinated prices,
  verified by an eval that diffs spec prices against tool outputs.
- Re-marking creates a child spec with `parent` set; the original is unchanged.
- A markup of a 1-year daily chart completes in under 10 s end to end.
- The spoken summary is under 30 words and names one decisive level.

## Related

[[Markup Spec]] · [[Charting Engine]] · [[Agent — Pattern Recognition]] ·
[[Agent — Level Watcher]] · [[Agent — Idea Synthesizer]] · [[Charting Family]]
