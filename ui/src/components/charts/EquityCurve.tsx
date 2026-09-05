// Spec: Genesis Markdown/60-UI/UI Stack.md §5 Data surfaces — uPlot for dense series
//
// The account balance over time, with drawdown underneath it.
//
// uPlot rather than Lightweight Charts: the note assigns price series to one
// and dense time series to the other, and an equity curve is the second kind.
// It is also 40 KB and draws to a single canvas, which matters on the 8 GB
// machine this runs on.
//
// **The drawdown band is the point of this chart, not decoration.** An equity
// line alone is the most flattering way to present a strategy: it ends where it
// ends, and the eye reads the endpoint. Drawing the distance from the running
// peak underneath it puts the worst moment on the same screen as the final
// number, at the same scale, which is the comparison a person actually needs to
// make before deciding whether they could have held it.
//
// The curve comes from Nautilus' account report — the engine's own bookkeeping,
// marked at every balance change. A curve accumulated from closed-trade P&L
// would show no drawdown while a position was open, which understates it
// exactly when it matters.

import { useEffect, useMemo, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { withAlpha } from '@/lib/format'

export interface EquityMarker {
  time: number
  won: boolean
}

interface Props {
  /** `{ time: epoch seconds, value }`, chronological. */
  points: { time: number; value: number }[]
  markers?: EquityMarker[]
}

function tokens() {
  const style = getComputedStyle(document.documentElement)
  const read = (name: string, fallback: string) =>
    style.getPropertyValue(name).trim() || fallback
  return {
    core: read('--core', '#3d8bff'),
    grid: read('--hairline', '#16202e'),
    ink: read('--ink-faint', '#4d6076'),
    down: read('--verdict-blocked', '#ff4d5e'),
    up: read('--verdict-pass', '#35c48a'),
    font: read('--font-mono', 'monospace'),
  }
}

export function EquityCurve({ points, markers }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const plot = useRef<uPlot | null>(null)

  const data = useMemo<uPlot.AlignedData>(() => {
    const xs = points.map((p) => p.time)
    const ys = points.map((p) => p.value)
    // Drawdown from the running peak, as a percentage — negative or zero.
    let peak = ys[0] ?? 0
    const drawdown = ys.map((value) => {
      peak = Math.max(peak, value)
      return peak > 0 ? ((value - peak) / peak) * 100 : 0
    })
    return [xs, ys, drawdown]
  }, [points])

  useEffect(() => {
    if (!host.current || points.length < 2) return
    const t = tokens()

    const axis = {
      stroke: t.ink,
      grid: { stroke: t.grid, width: 1 },
      ticks: { stroke: t.grid, width: 1 },
      font: `9px ${t.font}`,
    }

    const chart = new uPlot(
      {
        width: host.current.clientWidth,
        height: host.current.clientHeight,
        padding: [8, 8, 0, 0],
        cursor: {
          drag: { x: true, y: false },
          points: { size: 5, width: 1 },
        },
        legend: { show: false },
        scales: {
          x: { time: true },
          // Drawdown gets its own scale pinned to the bottom third, so the
          // equity line keeps the resolution it needs while the band stays
          // readable against a common zero.
          dd: { range: (_u, _min, max) => [Math.min(-1, _min * 1.1), Math.max(0, max)] },
        },
        axes: [
          { ...axis },
          { ...axis, scale: 'y', size: 56 },
          {
            ...axis, scale: 'dd', side: 1, size: 44,
            values: (_u, splits) => splits.map((v) => `${v.toFixed(0)}%`),
          },
        ],
        series: [
          {},
          {
            label: 'equity',
            scale: 'y',
            stroke: t.core,
            width: 1.5,
            fill: withAlpha(t.core, 0.12),
            points: { show: false },
          },
          {
            label: 'drawdown',
            scale: 'dd',
            stroke: withAlpha(t.down, 0.6),
            width: 1,
            fill: withAlpha(t.down, 0.16),
            points: { show: false },
          },
        ],
      },
      data,
      host.current,
    )
    plot.current = chart

    // uPlot is not responsive on its own; a ResizeObserver is the supported pattern and
    // is cheaper than re-creating the plot on every window resize.
    const observer = new ResizeObserver(([entry]) => {
      chart.setSize({
        width: Math.max(entry.contentRect.width, 80),
        height: Math.max(entry.contentRect.height, 80),
      })
    })
    observer.observe(host.current)

    return () => {
      observer.disconnect()
      chart.destroy()
      plot.current = null
    }
    // Rebuilt when the series identity changes; `setData` handles the rest.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points.length])

  useEffect(() => {
    plot.current?.setData(data)
  }, [data])

  if (points.length < 2) return null

  const last = points[points.length - 1].value
  const first = points[0].value
  const t = tokens()

  return (
    <div className="flex flex-col h-full min-h-0" style={{ gap: 4 }}>
      <div className="flex items-baseline gap-3" style={{ flexShrink: 0 }}>
        <span className="label">equity</span>
        <span className="num" style={{ fontSize: 'var(--fs-lg)' }}>
          {last.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </span>
        <span
          className="num"
          style={{ color: last >= first ? t.up : t.down, fontSize: 'var(--fs-sm)' }}
        >
          {last >= first ? '+' : ''}
          {((last / first - 1) * 100).toFixed(2)}%
        </span>
        <span style={{ flex: 1 }} />
        <span className="label" style={{ color: 'var(--ink-ghost)' }}>
          {markers?.length ? `${markers.length} closes` : ''} · drawdown shaded below
        </span>
      </div>
      <div ref={host} style={{ flex: 1, minHeight: 0, width: '100%' }} />
    </div>
  )
}
