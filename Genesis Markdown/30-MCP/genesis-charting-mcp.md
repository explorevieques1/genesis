---
title: genesis-charting-mcp
tags: [mcp, charting]
status: spec
implemented_by: []
---

# genesis-charting-mcp

Level computation and [[Markup Spec]] rendering, exposed as tools.

## Tools exposed

| Tool | Returns |
|---|---|
| `compute_levels` | All structural levels for a symbol/timeframe: S/R clusters with touch counts and strength, VWAP/AVWAP, ORB, FVGs, volume profile POC and value area, prior-period H/L/C, Fibonacci from the dominant swing, order blocks, fitted trendlines, moving averages |
| `render` | A [[Markup Spec]] → PNG/SVG at a fixed size and theme. Returns the file path. |
| `render_composite` | Several specs across timeframes → one composite image ([[Agent — Multi Timeframe]]) |
| `structure` | Deterministic structure measurements: swing sequence, trend strength, range boundaries, volatility contraction — the skeptic that cross-checks [[Agent — Pattern Recognition]] |
| `diff_spec` | Re-render an old spec against current data. *"Show me how that level held up."* |
| `compile_pine` | A strategy or markup spec → PineScript alert or indicator |

## Why ours

Three reasons:

1. **The [[Markup Spec]] is a Genesis concept.** No third-party server knows about it.
2. **Rendering must be deterministic and identical** across the vault, the dashboard,
   and vision-model input. One renderer, one output.
3. **`diff_spec` is only possible** because specs are immutable objects we control.

## Determinism requirements

Same spec plus same bars must produce a byte-identical image. This matters more than
it sounds:

- Vision-model interpretations are cached against the spec id — a nondeterministic
  render invalidates that cache silently
- Journal charts must be reproducible years later
- Visual regression tests need a stable baseline

So: no timestamps in the image beyond the intended one, no random jitter in layout,
fonts embedded, fixed dimensions.

## Level computation quality

The hard part isn't computing levels — it's computing *good* ones.

- **Strength scoring**: touches × recency weight × reaction magnitude × volume at level
- **Confluence merging**: levels within a tick tolerance merge into one, strength combined
- **ATR-relative distance**: relevance is measured in ATR, not percent
- **Timeframe-appropriate lookback**: a daily chart's S/R uses a different window than a 5-minute chart's

Borrow the indicator math ([[Trading Corpus Index]]): `nautilus_trader/indicators/`,
`vectorbt/indicators/factory.py`, and `mcp-market-data-server` for volume profile,
ORB, and FVG.

## PineScript output

`compile_pine` serves the workflow where you want the alert on TradingView rather
than inside Genesis. Lineage: [[Repo — gensis-agents]] `agents/alert-agent` — the
condition builder, filters, lookback confirmation, and cooldown gate, plus the
`.pine` files in `New Downloads/` as test fixtures.

## Access

Allow-listed to the [[Charting Family]] and [[Agent — Strategy Author]]
(for `compile_pine`).

## Acceptance criteria

- Identical inputs produce byte-identical images.
- `compute_levels` returns levels with strength scores and merged confluences.
- `diff_spec` correctly re-renders a 3-month-old spec against current data.
- Rendered charts are legible enough that a vision model names the marked levels
  correctly ≥90% of the time.
- Generated PineScript compiles against a test corpus.
- A 1-year daily chart with 12 annotations renders in under 2 s.

## Related

[[Markup Spec]] · [[Charting Engine]] · [[Agent — Chart Markup]] ·
[[Agent — Multi Timeframe]] · [[Agent — Strategy Author]] · [[MCP Gateway]]
