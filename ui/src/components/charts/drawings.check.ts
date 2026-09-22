// Spec: Genesis Markdown/60-UI/Chart Tools.md
//
// The handle arithmetic, checked. Run it with:
//
//     npm run check:charts        # or: node src/components/charts/drawings.check.ts
//
// Plain node — it strips the types itself, so this costs no test framework and
// no dependency. It covers the two rules a person cannot see going wrong: a box
// dragged inside out, and a position sketch whose stop crossed its entry.

import assert from 'node:assert/strict'
import {
  buildDrawing, fibPrices, handlesOf, moveHandle, rewardToRisk, targetFor,
  type Drawing, type TradePlanDrawing, type ZoneDrawing,
} from './drawings.ts'

const id = (d: object): Drawing => ({ id: 'dr_test', ...d }) as Drawing
const edge = (t: number) => t + 24

// -- building ---------------------------------------------------------------

const plan = id(buildDrawing('long', { time: 10, price: 100 }, { time: 12, price: 96 }, edge)!)
assert.equal(plan.kind, 'trade_plan')
assert.deepEqual(
  { entry: (plan as TradePlanDrawing).entry, stop: (plan as TradePlanDrawing).stop },
  { entry: 100, stop: 96 },
)
// Target is two units of risk out, and R:R is computed from the geometry.
assert.equal((plan as TradePlanDrawing).targets[0], 108)
assert.equal(rewardToRisk(plan as TradePlanDrawing), 2)
assert.equal((plan as TradePlanDrawing).to_time, 34, 'the plan spans bars to the right')

// A short is the mirror, and a stop drawn on the wrong side is clamped, not
// silently turned into a long.
const short = buildDrawing('short', { time: 10, price: 100 }, { time: 12, price: 104 }, edge)!
assert.equal((short as TradePlanDrawing).stop, 104)
const wrong = buildDrawing('short', { time: 10, price: 100 }, { time: 12, price: 90 }, edge)!
assert.equal((short as TradePlanDrawing).side, 'short')
assert.equal((wrong as TradePlanDrawing).stop, 100, 'a short stop below entry clamps to entry')

// A box takes its bounds from two corners in any order.
const box = id(buildDrawing('zone', { time: 20, price: 90 }, { time: 10, price: 110 }, edge)!) as ZoneDrawing
assert.deepEqual(
  [box.from_time, box.to_time, box.from, box.to],
  [10, 20, 90, 110],
)

assert.equal(buildDrawing('none', { time: 1, price: 1 }, { time: 2, price: 2 }, edge), null)

// -- dragging ---------------------------------------------------------------

// Drag a box's bottom-left corner past its top-right one: the bounds re-sort,
// so a stored zone is never inverted.
const flipped = moveHandle(box, 'bl', { time: 40, price: 130 }) as ZoneDrawing
assert.deepEqual(
  [flipped.from_time, flipped.to_time, flipped.from, flipped.to],
  [20, 40, 110, 130],
)

// The plan's three handles move independently, and the stop cannot cross.
const wide = moveHandle(plan, 'target', { time: 30, price: 120 }) as TradePlanDrawing
assert.equal(rewardToRisk(wide), 5)
const crossed = moveHandle(plan, 'stop', { time: 30, price: 140 }) as TradePlanDrawing
assert.equal(crossed.stop, 100, 'a long stop dragged above entry stops at entry')
assert.equal(crossed.side, 'long')

// A trendline's ends move one at a time.
const line = id(buildDrawing('line', { time: 1, price: 10 }, { time: 5, price: 20 }, edge)!)
const tilted = moveHandle(line, 'b', { time: 9, price: 5 })
assert.deepEqual(
  tilted.kind === 'line' ? tilted.points : null,
  [[1, 10], [9, 5]],
)

// Every handle a drawing offers must move it. A handle that renders and does
// nothing is the bug this loop exists to catch.
for (const drawing of [plan, box, line, id(buildDrawing('fib', { time: 1, price: 10 }, { time: 5, price: 20 }, edge)!)]) {
  for (const handle of handlesOf(drawing)) {
    const moved = moveHandle(drawing, handle.id, { time: 7, price: 15 })
    assert.notDeepEqual(moved, drawing, `${drawing.kind}/${handle.id} did not move`)
  }
}

// -- fib --------------------------------------------------------------------

const fib = id(buildDrawing('fib', { time: 1, price: 100 }, { time: 5, price: 200 }, edge)!)
const levels = fibPrices(fib as never)
// 0 sits on the swing end, 1 on its start, 0.5 halfway. Anything else means
// the retracement is drawn upside down.
assert.equal(levels[0].price, 200)
assert.equal(levels[levels.length - 1].price, 100)
assert.equal(levels.find((l) => l.ratio === 0.5)!.price, 150)

assert.equal(targetFor('short', 100, 105), 90)
assert.equal(rewardToRisk({ ...(plan as TradePlanDrawing), targets: [] }), null)

// eslint-disable-next-line no-console -- a check script that says nothing has no result
console.log('drawings: ok')
