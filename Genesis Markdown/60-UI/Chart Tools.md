---
title: Chart Tools
tags: [ui, charting]
status: built
implemented_by: [src/genesis/charting/drawings.py, src/genesis/server/drawing_routes.py, ui/src/components/charts/DrawingLayer.tsx, ui/src/components/charts/ChartControls.tsx, ui/src/components/charts/drawings.ts, ui/src/components/charts/drawings.check.ts, tests/charting/test_drawings.py]
---

# Chart Tools

What a person can do to `CH` by hand: draw on it, and change how it looks.

Two halves that behave differently on purpose. **Drawings are data** — saved on
the daemon, keyed to a series, still there next month and on another machine.
**Settings are pixels** — per-viewer, `localStorage`, and losing them costs a
colour.

## The drawing vocabulary is the markup schema's

A hand-drawn box is a `zone`. A trendline is a `line`. The position tool is a
`trade_plan`. Same `kind` names, same field names as
[[Markup Spec Schema]], because [[Operating Model]] §1 says a person and Genesis
work through the same door — and two vocabularies for one set of shapes would
guarantee that your box and an agent's box could never be shown on one chart.

| Tool | Kind | Gesture |
|---|---|---|
| horizontal line | `level` | click a price |
| trend line | `line` | drag end to end |
| box | `zone` | drag across the corners |
| fib retracement | `fib` | drag along the swing |
| long / short position | `trade_plan` | drag entry → stop; target lands at 2R |
| entry arrow | `marker` | click; alt-click points it down |
| note | `text` | click, then type |

Three deliberate divergences from the schema, each because a hand is not an
agent:

1. **No `why` is required.** An agent that draws an unexplained line is
   producing noise, and the validator says so. A person drawing on their own
   chart is thinking, and demanding a justification per stroke would stop them
   doing it. That difference is the whole reason `chart_drawings` is a separate
   table rather than a looser mode of the markup store.
2. **Times are epoch seconds**, not ISO — it is what Lightweight Charts speaks
   and what `/v1/market/bars` already returns. The converter is a `Date` call,
   written when something first needs both on one chart.
3. **`zone` carries times and `marker` carries a direction.** A hand-drawn box
   is bounded in time; the schema's zone is a price band across the whole chart.

**A `trade_plan` drawing is not an order and cannot become one.** Entry, stop,
targets — no size, no account, no broker, which is `spec.TradePlan`'s own
guarantee. [[Safety Invariants]] §1 keeps the only path to a broker through
`propose_order` → approval → `place_approved`.

## The sheet must be above the canvas

Lightweight Charts gives its own canvases `z-index: 1` and `2`. A sheet that is
merely *later in the DOM* still loses to an explicit z-index, so the chart
painted over it and swallowed every pointer event: the tools armed, the hint
appeared, the cursor changed, and not one press reached the layer. Nothing was
drawn and nothing was written, which reads exactly like a broken save.

`zIndex: 3` on the sheet is the whole fix, and it is worth stating here because
the failure is invisible from the code — every handler was correct.

**Verified by driving a real browser**: headless Chromium over CDP, real mouse
events, six tools drawn and read back out of the store, a handle dragged and
the new geometry persisted. A layer this stateful cannot be checked by
inspection, and a second wrong diagnosis costs more than the harness did.

## Press, drag, release — and then drag the handles

The gesture is the one every charting package uses. Click-click also works
(press and release without moving, then click again), because a person who has
learned that gesture should not be told they are holding it wrong. The
difference between the two is measured in pixels, so a hand tremor cannot
commit a box with no height.

What you see while dragging *is* the drawing, at 65% opacity — the preview is
built by the same `buildDrawing` the release calls.

A drawing arrives selected, wearing its handles:

| Kind | Handles |
|---|---|
| `level` | the price, on the right edge |
| `line`, `fib` | both ends, dragged to any angle |
| `zone` | four corners |
| `trade_plan` | entry, stop, target, and the right edge for width |
| `marker`, `text` | the point |

Two rules the geometry enforces rather than the person, both in `moveHandle`
and both covered by `drawings.check.ts`:

1. **A box stays a box.** Drag a corner past its opposite and the bounds
   re-sort, so a zone is never stored inverted — which would render as nothing
   next time it was opened.
2. **A plan keeps its side.** A long whose stop is above its entry is not a
   long, and `spec.TradePlan` refuses it. Dragging the stop through the entry
   clamps; it does not silently flip the side, because a tool called "short"
   that quietly becomes a long is worse than one that stops moving.

The reshape is written with the drawing's own id, so the store replaces in
place rather than accumulating a copy per drag.

## Anchored in time and price, never in pixels

A box round Tuesday's open is round Tuesday's open at every zoom. Time anchors
**snap to bars**: Lightweight Charts can only convert a time it actually holds,
and an anchor between two bars would vanish the moment the series changed.
Price is free — that is where the judgement is.

Drawings are keyed by `<symbol_id>|<timeframe>`, so what you drew on NVDA daily
does not appear on NVDA 5-minute. A level that matters on one is noise on the
other. `CR:<range_id>` keys like any other series, which is how a
[[Candle Ranges|candle range]] carries its own markup.

## The surface

An SVG sheet over the chart rather than a Lightweight Charts primitive. A
primitive paints on the chart's canvas and is called on every repaint, which is
the tidy answer for lines and the wrong one for a text box you can click, a fib
whose labels must stay legible, and a shape you select and delete. The cost is
that nothing announces a repaint, so the layer polls one `requestAnimationFrame`
and compares two numbers — the ceiling is recorded in the file.

Handles are dragged; the shape's *body* is not. Moving a whole drawing without
reshaping it means grabbing an edge, and every edge is already a handle — so it
is deferred until it is actually missed.

The geometry is pure and lives in `drawings.ts`, checked by
`drawings.check.ts`, which plain `node` runs (`npm run check:charts`) — it
strips the types itself, so the check costs no test framework and no
dependency.

## Settings

Grid lines, volume, crosshair, the clock on the time axis, wicks, hollow up
bars, candle colours, and the price axis mode (linear, logarithmic, percent).

The price axis also **drag-scales** now. It was pinned —
`axisPressedMouseMove: { price: false }` — which left autoscale as the only way
to frame a move, and stretching price while leaving time alone is exactly what
studying a range wants.

## Deliberately not built

- **Dragging a whole drawing.** Reshape by the handles; move by redrawing.
- **Drawings shared with agents.** The store is readable and the vocabulary is
  the schema's, so an agent that wants to read the trader's marks can; nothing
  does yet, and inventing the consumer first would be inventing the requirement.
- **A colour per drawing.** One `color` field exists on every kind and nothing
  sets it.

## Related

[[Charting Engine]] · [[Markup Spec Schema]] · [[Markup Spec]] · [[Terminal]] ·
[[Candle Ranges]] · [[Operating Model]] · [[Safety Invariants]] · [[UI Stack]]
