// Spec: Genesis Markdown/60-UI/Chart Tools.md
//
// The drawing surface: an SVG sheet over the chart, in the chart's own
// coordinates.
//
// **The gesture is press, drag, release** — the one every charting package
// uses, and the one a hand already knows. A first version took two separate
// clicks instead; a drag then delivered one click, the tool waited forever for
// a second, and nothing was ever drawn. Click-click still works as a fallback
// (press and release without moving, then click again), because a person who
// has learned that gesture should not be told they are holding it wrong.
//
// **Everything is anchored in time and price, never in pixels.** A box drawn
// round Tuesday's open is round Tuesday's open at every zoom, and that is the
// whole difference between a chart annotation and a sticker.
//
// Time anchors **snap to bars**. Lightweight Charts can only convert a time it
// actually holds, and an anchor between two bars would vanish the moment the
// series changed. Price is free — that is where the judgement is.
//
// **Why SVG and not a Lightweight Charts primitive.** v5 can attach a series
// primitive that paints on the chart's canvas and is called on every repaint,
// which is the tidy answer for lines. It is not the tidy answer for a text box
// you can click, a fib whose labels must stay legible, or a handle you drag —
// all of which SVG gives for free and canvas makes you build. The cost is that
// nothing tells us when the chart repainted, so the layer polls.
// `ponytail:` one requestAnimationFrame per chart, reading two numbers and
// comparing a string — move to a series primitive if it ever shows up in a
// profile. rAF stops on its own when the tab is hidden.

import { useEffect, useReducer, useRef, useState } from 'react'
import type { IChartApi, ISeriesApi, UTCTimestamp } from 'lightweight-charts'
import type { BarRow } from '@/api/client'
import { withAlpha } from '@/lib/format'
import {
  PLAN_BARS, buildDrawing, fibPrices, handlesOf, moveHandle, rewardToRisk,
  type Anchor, type Drawing, type HandleId, type NewDrawing, type ToolId,
} from './drawings'

interface Props {
  chart: IChartApi
  series: ISeriesApi<'Candlestick'>
  bars: BarRow[]
  drawings: Drawing[]
  tool: ToolId
  selectedId: string | null
  places: number
  onSelect: (id: string | null) => void
  onDelete: (id: string) => void
  /** A finished drawing, without its id — the store assigns that. */
  onCommit: (drawing: NewDrawing) => void
  /** A reshaped drawing, with its id — the store replaces in place. */
  onUpdate: (drawing: Drawing) => void
  /** The tool is spent once it has drawn; the panel puts the cursor back. */
  onDone: () => void
}

/** Tools that are done in one press. Everything else takes two points. */
const ONE_POINT = new Set<ToolId>(['level', 'marker', 'text'])

/** Below this, a press-release was a click rather than a drag. */
const DRAG_PX = 4

type Draft = { from: Anchor; fromPx: [number, number]; to: Anchor; live: boolean }
type Edit = { id: string; handle: HandleId; at: Anchor }

function palette() {
  const style = getComputedStyle(document.documentElement)
  const read = (name: string, fallback: string) =>
    style.getPropertyValue(name).trim() || fallback
  return {
    ink: read('--ink', '#d6e2f0'),
    core: read('--core', '#3d8bff'),
    up: read('--verdict-pass', '#35c48a'),
    down: read('--verdict-blocked', '#ff4d5e'),
    panel: read('--bg-panel', '#0d1622'),
  }
}

export function DrawingLayer({
  chart, series, bars, drawings, tool, selectedId, places,
  onSelect, onDelete, onCommit, onUpdate, onDone,
}: Props) {
  const host = useRef<HTMLDivElement>(null)
  const [, repaint] = useReducer((n: number) => n + 1, 0)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [edit, setEdit] = useState<Edit | null>(null)
  const [typing, setTyping] = useState<Anchor | null>(null)

  // -- repaint when the chart moved -------------------------------------
  useEffect(() => {
    let frame = 0
    let last = ''
    const probe = bars.length ? Number(bars[0].close) : 0
    const tick = () => {
      const range = chart.timeScale().getVisibleLogicalRange()
      const key = [
        range?.from, range?.to,
        series.priceToCoordinate(probe),
        host.current?.clientWidth, host.current?.clientHeight,
        // The axes resize with their labels; the sheet is inset by them.
        chart.priceScale('right').width(), chart.timeScale().height(),
      ].join(',')
      if (key !== last) {
        last = key
        repaint()
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [chart, series, bars])

  // -- Delete removes the selection -------------------------------------
  useEffect(() => {
    if (!selectedId) return
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (target && /^(INPUT|TEXTAREA)$/.test(target.tagName)) return
      if (e.key === 'Delete' || e.key === 'Backspace') onDelete(selectedId)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedId, onDelete])

  // -- Escape abandons whatever is half-done ----------------------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setDraft(null)
      setEdit(null)
      setTyping(null)
      onSelect(null)
      onDone()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onDone, onSelect])

  // A half-drawn shape belongs to the tool that started it. Switching tools
  // with an anchor on the chart would otherwise draw the new shape from the
  // old tool's starting point.
  useEffect(() => { setDraft(null) }, [tool])

  // Lightweight Charts hands out coordinates relative to the *pane* — the
  // candles, without the axes round them. So the sheet is inset by the axis
  // sizes, which makes the two coordinate systems the same one and keeps fib
  // labels and level lines from painting across the price scale.
  const width = host.current?.clientWidth ?? 0

  // -- coordinates ------------------------------------------------------
  const toX = (time: number): number | null => {
    const x = chart.timeScale().timeToCoordinate(time as UTCTimestamp)
    return x === null ? null : Number(x)
  }
  const toY = (price: number): number | null => {
    const y = series.priceToCoordinate(price)
    return y === null ? null : Number(y)
  }
  /** A pixel column -> the time of the bar under it. Snapped; see the header. */
  const fromX = (x: number): number => {
    const logical = chart.timeScale().coordinateToLogical(x)
    if (logical === null || !bars.length) return bars[bars.length - 1]?.time ?? 0
    const index = Math.min(bars.length - 1, Math.max(0, Math.round(Number(logical))))
    return bars[index].time
  }
  const fromY = (y: number): number => Number(series.coordinateToPrice(y) ?? 0)
  /** `PLAN_BARS` to the right of a time, clamped to the data we hold. */
  const rightEdge = (time: number): number => {
    const index = bars.findIndex((b) => b.time === time)
    if (index < 0) return time
    return bars[Math.min(bars.length - 1, index + PLAN_BARS)].time
  }

  /** Pointer -> chart units. Always measured against the sheet, never the
   *  element the event happened to land on. */
  function at(event: { clientX: number; clientY: number }): Anchor {
    const rect = host.current?.getBoundingClientRect()
    if (!rect) return { time: 0, price: 0 }
    return {
      time: fromX(event.clientX - rect.left),
      price: fromY(event.clientY - rect.top),
    }
  }

  const p = palette()
  const drawingTool = tool !== 'none'

  // -- drawing ----------------------------------------------------------

  function down(event: React.PointerEvent) {
    if (!drawingTool || typing) return
    const point = at(event)
    const px: [number, number] = [event.clientX, event.clientY]
    host.current?.setPointerCapture(event.pointerId)
    // A second press with a draft already waiting closes it — the click-click
    // fallback described in the header.
    setDraft(draft ? { ...draft, to: point, live: true } : { from: point, fromPx: px, to: point, live: true })
  }

  function move(event: React.PointerEvent) {
    if (edit) {
      setEdit({ ...edit, at: at(event) })
      return
    }
    // The rubber band follows whether or not the button is down, so the
    // click-click fallback previews too.
    if (draft) setDraft({ ...draft, to: at(event) })
  }

  function up(event: React.PointerEvent) {
    host.current?.releasePointerCapture?.(event.pointerId)
    if (edit) {
      finishEdit()
      return
    }
    if (!draft || !drawingTool) return
    const point = at(event)
    const moved = Math.hypot(event.clientX - draft.fromPx[0], event.clientY - draft.fromPx[1])

    if (tool === 'text') {
      setDraft(null)
      setTyping(draft.from)
      return
    }
    if (ONE_POINT.has(tool)) {
      const made = buildDrawing(tool, draft.from, point, rightEdge)
      if (made) {
        onCommit(
          tool === 'marker' && event.altKey
            ? ({ ...made, direction: 'down' } as NewDrawing)
            : made,
        )
      }
      setDraft(null)
      onDone()
      return
    }
    // A real drag finishes the shape. A press that went nowhere leaves the
    // first anchor on the chart and waits for the next click -- and measuring
    // that in *pixels* is what stops a 2px hand tremor from committing a box
    // with no height.
    if (moved < DRAG_PX) {
      setDraft({ ...draft, live: false })
      return
    }
    const made = buildDrawing(tool, draft.from, point, rightEdge)
    if (made) onCommit(made)
    setDraft(null)
    onDone()
  }

  function finishEdit() {
    if (!edit) return
    // Reshape the *stored* drawing, never the preview: a box re-sorts its
    // corners as it is dragged, so applying the same handle twice would move
    // a different corner the second time.
    const original = drawings.find((d) => d.id === edit.id)
    if (original) onUpdate(moveHandle(original, edit.handle, edit.at))
    setEdit(null)
  }

  const fmt = (value: number) => value.toFixed(places)

  // What is on screen: the stored drawings, with the one being dragged shown
  // where the pointer has it rather than where it was saved.
  const shown = edit
    ? drawings.map((d) => (d.id === edit.id ? moveHandle(d, edit.handle, edit.at) : d))
    : drawings
  const ghost = draft ? buildDrawing(tool, draft.from, draft.to, rightEdge) : null

  /** One shape. Selection is a halo rather than a colour change. */
  function render(d: Drawing, preview = false) {
    const selected = !preview && d.id === selectedId
    const stroke = d.color || p.core
    const hit = preview
      ? { pointerEvents: 'none' as const }
      : {
        onPointerDown: (event: React.PointerEvent) => {
          if (drawingTool) return
          event.stopPropagation()
          onSelect(d.id)
        },
        pointerEvents: (drawingTool ? 'none' : 'visiblePainted') as 'none' | 'visiblePainted',
      }
    const halo = {
      cursor: drawingTool ? 'crosshair' : 'pointer',
      opacity: preview ? 0.65 : 1,
      ...(selected ? { filter: 'drop-shadow(0 0 3px currentColor)' } : {}),
    }

    switch (d.kind) {
      case 'level': {
        const y = toY(d.price)
        if (y === null) return null
        return (
          <g key={d.id} color={stroke} style={halo}>
            <line x1={0} y1={y} x2={width} y2={y} stroke={stroke}
              strokeWidth={selected ? 2 : 1} strokeDasharray="6 4" {...hit} />
            <Tag x={4} y={y - 4} text={d.label || fmt(d.price)} fill={stroke} bg={p.panel} />
          </g>
        )
      }
      case 'zone': {
        const x1 = toX(d.from_time), x2 = toX(d.to_time)
        const y1 = toY(d.to), y2 = toY(d.from)
        if (x1 === null || x2 === null || y1 === null || y2 === null) return null
        return (
          <g key={d.id} color={stroke} style={halo}>
            <rect
              x={Math.min(x1, x2)} y={Math.min(y1, y2)}
              width={Math.abs(x2 - x1)} height={Math.abs(y2 - y1)}
              fill={withAlpha(stroke, 0.12)} stroke={stroke}
              strokeWidth={selected ? 2 : 1} {...hit}
            />
            {d.label && (
              <Tag x={Math.min(x1, x2) + 3} y={Math.min(y1, y2) - 3}
                text={d.label} fill={stroke} bg={p.panel} />
            )}
          </g>
        )
      }
      case 'line': {
        const [a, b] = d.points
        const x1 = toX(a[0]), y1 = toY(a[1])
        const x2 = toX(b[0]), y2 = toY(b[1])
        if (x1 === null || y1 === null || x2 === null || y2 === null) return null
        return (
          <g key={d.id} color={stroke} style={halo}>
            {/* A wide, invisible line under the visible one: a 1.5px stroke is
                a 1.5px target, and nobody can click that. */}
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="transparent" strokeWidth={10}
              {...hit} />
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={stroke}
              strokeWidth={selected ? 2.5 : 1.5} pointerEvents="none" />
          </g>
        )
      }
      case 'fib': {
        const x1 = toX(d.anchor_from[0]), x2 = toX(d.anchor_to[0])
        if (x1 === null || x2 === null) return null
        const left = Math.min(x1, x2)
        return (
          <g key={d.id} color={stroke} style={halo} {...hit}>
            {fibPrices(d).map(({ ratio, price }) => {
              const y = toY(price)
              if (y === null) return null
              const emphatic = ratio === 0.5 || ratio === 0.618
              return (
                <g key={ratio}>
                  <line x1={left} y1={y} x2={width} y2={y} stroke={stroke}
                    strokeWidth={emphatic ? 1.4 : 0.8}
                    strokeOpacity={emphatic ? 0.9 : 0.55} />
                  <Tag x={left + 3} y={y - 3} text={`${ratio} · ${fmt(price)}`}
                    fill={stroke} bg={p.panel} />
                </g>
              )
            })}
          </g>
        )
      }
      case 'trade_plan': {
        const x1 = toX(d.from_time), x2 = toX(d.to_time)
        const entry = toY(d.entry), stop = toY(d.stop)
        const target = d.targets.length ? toY(d.targets[0]) : null
        if (x1 === null || x2 === null || entry === null || stop === null) return null
        const left = Math.min(x1, x2)
        const w = Math.max(24, Math.abs(x2 - x1))
        const rr = rewardToRisk(d)
        return (
          <g key={d.id} color={stroke} style={halo} {...hit}>
            {/* risk, then reward — the two boxes of the TradingView tool */}
            <rect x={left} y={Math.min(entry, stop)} width={w}
              height={Math.abs(stop - entry)}
              fill={withAlpha(p.down, 0.18)} stroke={withAlpha(p.down, 0.7)} />
            {target !== null && (
              <rect x={left} y={Math.min(entry, target)} width={w}
                height={Math.abs(target - entry)}
                fill={withAlpha(p.up, 0.18)} stroke={withAlpha(p.up, 0.7)} />
            )}
            <line x1={left} y1={entry} x2={left + w} y2={entry}
              stroke={p.ink} strokeWidth={1} />
            <Tag x={left + 3} y={entry - 3}
              text={`${d.side} ${fmt(d.entry)}${rr ? ` · ${rr}R` : ''}`}
              fill={p.ink} bg={p.panel} />
            <Tag x={left + 3} y={stop + (d.side === 'long' ? 11 : -3)}
              text={`stop ${fmt(d.stop)}`} fill={p.down} bg={p.panel} />
            {target !== null && (
              <Tag x={left + 3} y={target + (d.side === 'long' ? -3 : 11)}
                text={`target ${fmt(d.targets[0])}`} fill={p.up} bg={p.panel} />
            )}
          </g>
        )
      }
      case 'marker': {
        const x = toX(d.time), y = toY(d.price)
        if (x === null || y === null) return null
        const up = d.direction === 'up'
        const colour = d.color || (up ? p.up : p.down)
        // Below the price for an up arrow, above for a down one, so the tip
        // lands on the bar rather than covering it.
        const tip = up ? y - 2 : y + 2
        const tail = up ? tip + 13 : tip - 13
        return (
          <g key={d.id} color={colour} style={halo} {...hit}>
            <path
              d={`M ${x} ${tip} L ${x - 4.5} ${tail} L ${x + 4.5} ${tail} Z`}
              fill={colour} stroke={colour}
              strokeWidth={selected ? 2 : 0}
            />
            {d.label && <Tag x={x + 7} y={tail} text={d.label} fill={colour} bg={p.panel} />}
          </g>
        )
      }
      case 'text': {
        const x = toX(d.position[0]), y = toY(d.position[1])
        if (x === null || y === null) return null
        return (
          <g key={d.id} color={stroke} style={halo}>
            <Tag x={x} y={y} text={d.content} fill={d.color || p.ink} bg={p.panel}
              boxed selected={selected} {...hit} />
          </g>
        )
      }
    }
  }

  /** The grab points on the selected drawing. */
  function handles(d: Drawing) {
    if (d.id !== selectedId || drawingTool) return null
    return handlesOf(d).map((handle) => {
      // A level has no time: its handle rides the right edge, where a price
      // label would be.
      const x = handle.time === null ? width - 16 : toX(handle.time)
      const y = toY(handle.price)
      if (x === null || y === null) return null
      return (
        <rect
          key={handle.id}
          x={x - 4} y={y - 4} width={8} height={8}
          fill={p.panel} stroke={p.core} strokeWidth={1.4}
          style={{ cursor: 'grab' }}
          pointerEvents="visiblePainted"
          onPointerDown={(event) => {
            event.stopPropagation()
            ;(event.target as Element).setPointerCapture(event.pointerId)
            setEdit({ id: d.id, handle: handle.id, at: { time: handle.time ?? 0, price: handle.price } })
          }}
          onPointerMove={(event) => {
            if (edit?.id === d.id && edit.handle === handle.id) setEdit({ ...edit, at: at(event) })
          }}
          onPointerUp={(event) => {
            // Stopped here, or the sheet's own release handler finishes the
            // same drag a second time and writes the drawing twice.
            event.stopPropagation()
            ;(event.target as Element).releasePointerCapture?.(event.pointerId)
            finishEdit()
          }}
        >
          <title>{handle.hint}</title>
        </rect>
      )
    })
  }

  return (
    <div
      ref={host}
      style={{
        position: 'absolute',
        top: 0, left: 0,
        right: chart.priceScale('right').width(),
        bottom: chart.timeScale().height(),
        // Above the chart's own canvases, which carry `z-index: 1` and `2`.
        // Being later in the DOM is not enough against an explicit z-index:
        // without this the canvas paints over the sheet and swallows every
        // pointer event, which is exactly what it did -- the tools armed, the
        // hint appeared, and not one press ever reached this element.
        zIndex: 3,
        // Transparent to the mouse unless a tool is out or a drag is running,
        // so panning, zooming and the crosshair keep working exactly as they
        // did. The shapes and handles set `pointer-events` back on, which is
        // how a drawing can be clicked while the chart behind it stays live.
        pointerEvents: drawingTool || draft || edit ? 'auto' : 'none',
        cursor: drawingTool ? 'crosshair' : 'default',
      }}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
    >
      <svg width="100%" height="100%" style={{ display: 'block' }}>
        {shown.map((d) => render(d))}
        {shown.map((d) => <g key={`h-${d.id}`}>{handles(d)}</g>)}
        {/* The preview is the real thing, drawn faint: what you see while
            dragging is exactly what lands when you let go. */}
        {ghost && render({ ...ghost, id: '__ghost' } as Drawing, true)}
      </svg>

      {typing && (
        <TextEntry
          x={toX(typing.time) ?? 0}
          y={toY(typing.price) ?? 0}
          onCancel={() => { setTyping(null); onDone() }}
          onCommit={(content) => {
            setTyping(null)
            if (content.trim()) {
              onCommit({
                kind: 'text', content: content.trim(),
                position: [typing.time, typing.price],
              })
            }
            onDone()
          }}
        />
      )}
    </div>
  )
}

/** A label with a ground under it, because chart text over candles is unreadable. */
function Tag({
  x, y, text, fill, bg, boxed, selected, ...rest
}: {
  x: number; y: number; text: string; fill: string; bg: string
  boxed?: boolean; selected?: boolean
} & React.SVGProps<SVGGElement>) {
  const width = text.length * 5.6 + 8
  return (
    <g {...rest}>
      <rect
        x={x - 3} y={y - 9} width={width} height={13} rx={2}
        fill={withAlpha(bg, boxed ? 0.92 : 0.72)}
        stroke={boxed ? fill : 'none'}
        strokeWidth={selected ? 1.5 : 0.6}
        strokeOpacity={boxed ? 0.6 : 0}
      />
      <text x={x} y={y} fill={fill} fontSize={9.5} fontFamily="var(--font-mono, monospace)">
        {text}
      </text>
    </g>
  )
}

/** Type the comment where you clicked. Enter commits, Escape abandons. */
function TextEntry({
  x, y, onCommit, onCancel,
}: { x: number; y: number; onCommit: (text: string) => void; onCancel: () => void }) {
  return (
    <input
      className="field"
      autoFocus
      placeholder="note…"
      style={{ position: 'absolute', left: x, top: y - 10, width: 180, zIndex: 5 }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onCommit((e.target as HTMLInputElement).value)
        if (e.key === 'Escape') onCancel()
      }}
      onBlur={(e) => onCommit(e.target.value)}
    />
  )
}
