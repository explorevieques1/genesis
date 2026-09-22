// Spec: Genesis Markdown/60-UI/Chart Tools.md · 70-Schemas/Markup Spec Schema.md
//
// What a person can draw on a chart, as data.
//
// The vocabulary is the markup schema's, on purpose: a hand-drawn box is a
// `zone`, a trendline is a `line`, the position tool is a `trade_plan`. Genesis
// draws the same eight shapes from `charting/spec.py`, and two vocabularies for
// one set of shapes would mean an agent's box and yours could never share a
// chart — [[Operating Model]] §1 points the other way.
//
// One deliberate divergence: **times here are epoch seconds**, because that is
// what Lightweight Charts speaks and what `/v1/market/bars` already returns.
// The markup spec uses ISO strings. The converter is a `Date` call and is not
// written until something needs both on one chart.
//
// Geometry lives here rather than in the layer that paints it, so the fib
// levels and the reward-to-risk arithmetic can be read — and reasoned about —
// without a canvas in scope.

/** The discriminator, matching `spec.Annotation`. */
export type DrawingKind =
  | 'level' | 'zone' | 'line' | 'fib' | 'trade_plan' | 'marker' | 'text'

interface Base {
  id: string
  label?: string
  /** Set per drawing so a chart can carry more than one idea. */
  color?: string
}

/** A horizontal price. Spans the whole chart, like a level should. */
export interface LevelDrawing extends Base { kind: 'level'; price: number }

/** A box: a price band between two times. */
export interface ZoneDrawing extends Base {
  kind: 'zone'
  from: number
  to: number
  from_time: number
  to_time: number
}

/** A trendline. `[time, price]` pairs, exactly as the schema's `line`. */
export interface LineDrawing extends Base { kind: 'line'; points: [number, number][] }

export interface FibDrawing extends Base {
  kind: 'fib'
  anchor_from: [number, number]
  anchor_to: [number, number]
  retracements: number[]
}

/**
 * The position tool. Entry, stop, targets — and **no size, no account, no
 * broker**, which is `spec.TradePlan`'s own guarantee and the reason this
 * object cannot become an order (Safety Invariants §1).
 */
export interface TradePlanDrawing extends Base {
  kind: 'trade_plan'
  side: 'long' | 'short'
  entry: number
  stop: number
  targets: number[]
  from_time: number
  to_time: number
}

/** The little arrow — where the entry actually was. */
export interface MarkerDrawing extends Base {
  kind: 'marker'
  time: number
  price: number
  direction: 'up' | 'down'
}

/** A comment pinned to a price and a time. */
export interface TextDrawing extends Base {
  kind: 'text'
  content: string
  position: [number, number]
}

export type Drawing =
  | LevelDrawing | ZoneDrawing | LineDrawing | FibDrawing
  | TradePlanDrawing | MarkerDrawing | TextDrawing

/**
 * A drawing before the store has given it an id.
 *
 * Distributed over the union deliberately: a plain `Omit<Drawing, 'id'>`
 * collapses the seven shapes into one object with no fields in common, and
 * then nothing type-checks.
 */
export type NewDrawing<D extends Drawing = Drawing> = D extends unknown ? Omit<D, 'id'> : never

/** What the toolbar offers. `clicks` is how many anchors the tool needs. */
export type ToolId = DrawingKind | 'long' | 'short' | 'none'

export interface Tool {
  id: ToolId
  /** Two or three letters. The button, and what the tooltip leads with. */
  title: string
  hint: string
  clicks: 1 | 2
}

export const TOOLS: Tool[] = [
  { id: 'none', title: 'cursor', hint: 'Click a drawing to select it — then drag its handles, or press Delete', clicks: 1 },
  { id: 'level', title: 'horizontal line', hint: 'Click a price', clicks: 1 },
  { id: 'line', title: 'trend line', hint: 'Drag from one end to the other', clicks: 2 },
  { id: 'zone', title: 'box', hint: 'Drag across the corners', clicks: 2 },
  { id: 'fib', title: 'fib retracement', hint: 'Drag along the swing, start to end', clicks: 2 },
  { id: 'long', title: 'long position', hint: 'Drag from entry down to the stop — target lands at 2R, then drag it', clicks: 2 },
  { id: 'short', title: 'short position', hint: 'Drag from entry up to the stop — target lands at 2R, then drag it', clicks: 2 },
  { id: 'marker', title: 'entry arrow', hint: 'Click where the entry was — alt-click points it down', clicks: 1 },
  { id: 'text', title: 'note', hint: 'Click, then type', clicks: 1 },
]

/** The standard set, plus the 0 and 1 anchors the eye needs to read them. */
export const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]

/** How many bars a position sketch and its boxes span by default. */
export const PLAN_BARS = 24

/**
 * Ratio → price for one fib. Derived from the anchors on every render rather
 * than stored, so a level can never disagree with the swing it came from.
 */
export function fibPrices(fib: FibDrawing): { ratio: number; price: number }[] {
  const [, from] = fib.anchor_from
  const [, to] = fib.anchor_to
  return fib.retracements.map((ratio) => ({ ratio, price: to - (to - from) * ratio }))
}

/**
 * Reward-to-risk, computed from the geometry — never trusted from a field.
 * `null` when the risk is zero, which is a drawing mistake rather than an
 * infinite trade.
 */
export function rewardToRisk(plan: TradePlanDrawing): number | null {
  const risk = Math.abs(plan.entry - plan.stop)
  if (risk <= 0 || !plan.targets.length) return null
  return Math.round((Math.abs(plan.targets[0] - plan.entry) / risk) * 100) / 100
}

/** Where a two-click position sketch puts its target: two units of risk out. */
export function targetFor(side: 'long' | 'short', entry: number, stop: number): number {
  const risk = Math.abs(entry - stop)
  return side === 'long' ? entry + 2 * risk : entry - 2 * risk
}

// ---------------------------------------------------------------------------
// geometry
// ---------------------------------------------------------------------------
//
// Pure, and here rather than in the layer that paints it, so the handle
// arithmetic can be read — and checked — without a canvas in scope. See
// `drawings.check.ts`, which runs on plain `node`.

/** A point on the chart, in the chart's own units. */
export interface Anchor { time: number; price: number }

/** The grab points a selected drawing offers. */
export type HandleId =
  | 'a' | 'b' | 'p' | 'entry' | 'stop' | 'target'
  | 'tl' | 'tr' | 'bl' | 'br'

export interface Handle {
  id: HandleId
  /** `null` means the drawing has no time at this handle — a level. */
  time: number | null
  price: number
  hint: string
}

/** Where a drawing can be grabbed. Empty for nothing that can be reshaped. */
export function handlesOf(d: Drawing): Handle[] {
  switch (d.kind) {
    case 'level':
      return [{ id: 'p', time: null, price: d.price, hint: 'price' }]
    case 'zone':
      return [
        { id: 'tl', time: d.from_time, price: d.to, hint: 'corner' },
        { id: 'tr', time: d.to_time, price: d.to, hint: 'corner' },
        { id: 'bl', time: d.from_time, price: d.from, hint: 'corner' },
        { id: 'br', time: d.to_time, price: d.from, hint: 'corner' },
      ]
    case 'line':
      return [
        { id: 'a', time: d.points[0][0], price: d.points[0][1], hint: 'end' },
        { id: 'b', time: d.points[1][0], price: d.points[1][1], hint: 'end' },
      ]
    case 'fib':
      return [
        { id: 'a', time: d.anchor_from[0], price: d.anchor_from[1], hint: 'swing start' },
        { id: 'b', time: d.anchor_to[0], price: d.anchor_to[1], hint: 'swing end' },
      ]
    case 'trade_plan':
      return [
        { id: 'entry', time: d.from_time, price: d.entry, hint: 'entry' },
        { id: 'stop', time: d.to_time, price: d.stop, hint: 'stop' },
        ...(d.targets.length
          ? [{ id: 'target' as const, time: d.to_time, price: d.targets[0], hint: 'target' }]
          : []),
        { id: 'b', time: d.to_time, price: d.entry, hint: 'width' },
      ]
    case 'marker':
      return [{ id: 'p', time: d.time, price: d.price, hint: 'point' }]
    case 'text':
      return [{ id: 'p', time: d.position[0], price: d.position[1], hint: 'point' }]
  }
}

/**
 * Drag one handle to a new point. Returns a new drawing; never mutates.
 *
 * Two rules the geometry enforces rather than the person:
 *
 * **A box stays a box.** Drag a corner past its opposite one and the bounds
 * re-sort, so `from` is always the lower price and `from_time` the earlier
 * time. Without that, a drawing that looked fine on screen would be stored
 * inverted and render as nothing next time.
 *
 * **A plan keeps its side.** A long whose stop is above its entry is not a
 * long, and `spec.TradePlan` refuses it outright. Dragging the stop through
 * the entry clamps rather than flipping the side, because a tool called
 * "short" that quietly becomes a long is worse than one that stops moving.
 */
export function moveHandle(d: Drawing, handle: HandleId, at: Anchor): Drawing {
  switch (d.kind) {
    case 'level':
      return { ...d, price: at.price }
    case 'marker':
      return { ...d, time: at.time, price: at.price }
    case 'text':
      return { ...d, position: [at.time, at.price] }
    case 'line': {
      const points: [number, number][] = [...d.points]
      points[handle === 'b' ? 1 : 0] = [at.time, at.price]
      return { ...d, points }
    }
    case 'fib':
      return handle === 'b'
        ? { ...d, anchor_to: [at.time, at.price] }
        : { ...d, anchor_from: [at.time, at.price] }
    case 'zone': {
      const left = handle === 'tl' || handle === 'bl'
      const top = handle === 'tl' || handle === 'tr'
      const times = [left ? at.time : d.from_time, left ? d.to_time : at.time]
      const prices = [top ? d.from : at.price, top ? at.price : d.to]
      return {
        ...d,
        from_time: Math.min(...times), to_time: Math.max(...times),
        from: Math.min(...prices), to: Math.max(...prices),
      }
    }
    case 'trade_plan': {
      const long = d.side === 'long'
      if (handle === 'b') return { ...d, to_time: Math.max(at.time, d.from_time) }
      if (handle === 'entry') {
        // The entry drags alone. Moving stop and target with it would be a
        // different gesture (move the whole plan), and doing both from one
        // handle means neither is predictable.
        const entry = long
          ? Math.max(at.price, d.stop)
          : Math.min(at.price, d.stop)
        return { ...d, entry, from_time: at.time }
      }
      if (handle === 'stop') {
        return { ...d, stop: long ? Math.min(at.price, d.entry) : Math.max(at.price, d.entry) }
      }
      const target = long ? Math.max(at.price, d.entry) : Math.min(at.price, d.entry)
      return { ...d, targets: [target, ...d.targets.slice(1)] }
    }
  }
}

/**
 * Two points and a tool -> the drawing they make. `null` for a tool that draws
 * nothing (the cursor).
 *
 * `rightEdge` turns the entry time into the time the plan's boxes end at,
 * which the caller supplies because only it knows how many bars there are.
 */
export function buildDrawing(
  tool: ToolId, a: Anchor, b: Anchor, rightEdge: (time: number) => number,
): NewDrawing | null {
  switch (tool) {
    case 'level':
      return { kind: 'level', price: a.price }
    case 'marker':
      return { kind: 'marker', time: a.time, price: a.price, direction: 'up' }
    case 'line':
      return { kind: 'line', points: [[a.time, a.price], [b.time, b.price]] }
    case 'zone':
      return {
        kind: 'zone',
        from: Math.min(a.price, b.price), to: Math.max(a.price, b.price),
        from_time: Math.min(a.time, b.time), to_time: Math.max(a.time, b.time),
      }
    case 'fib':
      return {
        kind: 'fib',
        anchor_from: [a.time, a.price], anchor_to: [b.time, b.price],
        retracements: FIB_LEVELS,
      }
    case 'long':
    case 'short': {
      // Entry first, then stop. The side comes from the button, not from which
      // way the mouse went: guessing it would hide the mistake instead of
      // showing it, and the schema refuses an incoherent plan anyway.
      const side = tool === 'long' ? 'long' : 'short'
      const entry = a.price
      const stop = side === 'long' ? Math.min(b.price, entry) : Math.max(b.price, entry)
      return {
        kind: 'trade_plan', side, entry, stop,
        targets: [targetFor(side, entry, stop)],
        from_time: a.time, to_time: rightEdge(a.time),
      }
    }
    default:
      return null
  }
}

// ---------------------------------------------------------------------------
// settings
// ---------------------------------------------------------------------------

/**
 * Chart appearance. Per-viewer and per-browser, so `localStorage` is the right
 * home — it is a preference about pixels, not fleet state, and losing it costs
 * a colour. Drawings are the opposite and live on the daemon.
 */
export interface ChartSettings {
  grid: boolean
  volume: boolean
  /** Percent and logarithmic are the two the price axis actually needs. */
  scale: 'normal' | 'logarithmic' | 'percentage'
  up: string
  down: string
  /** Hollow candles: body outlined rather than filled. */
  hollow: boolean
  wicks: boolean
  crosshair: boolean
  /** Intraday series want the clock; a daily one does not. */
  timeVisible: boolean
}

export const DEFAULT_SETTINGS: ChartSettings = {
  grid: true,
  volume: true,
  scale: 'normal',
  up: '',
  down: '',
  hollow: false,
  wicks: true,
  crosshair: true,
  timeVisible: false,
}

const SETTINGS_KEY = 'genesis.chart.settings'

export function loadSettings(): ChartSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY)
    return raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : DEFAULT_SETTINGS
  } catch {
    // Private window, blocked storage, or a shape from an older build. The
    // chart must draw either way.
    return DEFAULT_SETTINGS
  }
}

export function saveSettings(settings: ChartSettings): void {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings))
  } catch {
    /* a preference that cannot be stored is still a preference */
  }
}
