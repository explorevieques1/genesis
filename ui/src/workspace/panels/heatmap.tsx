// Spec: Genesis Markdown/60-UI/Widget Catalog.md · 10-Architecture/Market Data Sources.md
//
// The Nasdaq-100 on the day, as a treemap: area is market cap, colour is the
// session's change. One picture answering *"what moved, and did it matter?"* —
// a 6% move in a $20B name and a 2% move in a $4T one are the same size in a
// list and nothing like the same size here.
//
// **echarts, not a hand-rolled squarified layout.** It is already a dependency
// (`package.json`) and its treemap brings the two things this panel is nothing
// without: a squarified layout that stays readable across a 275× range of
// market caps, and `roam` + `zoomToNode`, which is the zoom into the small-cap
// corners the screenshot version of this only fakes.
//
// **Colour is computed, not mapped by `visualMap`.** A continuous visual map
// over a treemap fights the series' own `levels` styling. `changeColour` in
// `lib/format` is the ramp, shared with the `PFM` board, so the tiles here, the
// legend at the foot, and every other red/green surface are one function.
//
// **Tier 3, and it says so.** Public feed, settled close after the session —
// the same stance the watchlist takes, and for the same reason: this is
// research scaffolding, never a number the risk engine reads.
//
// It does not poll. `UI Stack §9` — nothing on this surface refetches on its
// own, so the session label tells you what you are looking at and the refresh
// is yours to press.

import { useEffect, useMemo, useRef } from 'react'
import * as echarts from 'echarts'
import { api, type HeatmapRow } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Loading } from '@/components/States'
import { Chip } from '@/components/Primitives'
import { changeColour } from '@/lib/format'
import { revealPanel } from '@/workspace/dock'
import { symbolLink, useWorkspace } from '@/workspace/context'

/** Sector parents, biggest first, each holding its members biggest first. */
function tree(rows: HeatmapRow[]) {
  const sectors = new Map<string, HeatmapRow[]>()
  for (const row of rows) {
    const bucket = sectors.get(row.sector) ?? []
    bucket.push(row)
    sectors.set(row.sector, bucket)
  }
  return [...sectors.entries()]
    .map(([sector, members]) => ({
      name: sector,
      // A parent with no explicit value sums its children, which is what we
      // want: the sector block is the sector's weight in the index.
      children: members
        .slice()
        .sort((a, b) => b.market_cap - a.market_cap)
        .map((row) => ({
          name: row.symbol,
          value: row.market_cap,
          itemStyle: { color: changeColour(row.change_pct) },
          row,
        })),
    }))
    .sort(
      (a, b) =>
        b.children.reduce((s, c) => s + c.value, 0) -
        a.children.reduce((s, c) => s + c.value, 0),
    )
}

function cap(value: number): string {
  return value >= 1e12 ? `${(value / 1e12).toFixed(2)}T`
    : value >= 1e9 ? `${(value / 1e9).toFixed(1)}B`
      : `${(value / 1e6).toFixed(0)}M`
}

export function HeatmapPanel() {
  const { state, reload, fetchedAt } = useRead(() => api.heatmap(), [])
  const { select } = useWorkspace()
  const host = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)
  const rows = state.data?.rows
  const data = useMemo(() => (rows ? tree(rows) : []), [rows])

  useEffect(() => {
    if (!host.current || !data.length) return
    const style = getComputedStyle(document.documentElement)
    const token = (name: string, fallback: string) =>
      style.getPropertyValue(name).trim() || fallback
    const mono = token('--font-mono', 'monospace')
    const ink = token('--ink', '#d6e2f0')
    const bg = token('--bg-panel', '#0a1019')

    const ec = echarts.init(host.current, undefined, { renderer: 'canvas' })
    chart.current = ec
    ec.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        backgroundColor: token('--bg-raised', '#131c28'),
        borderColor: token('--hairline', '#16202e'),
        textStyle: { color: ink, fontFamily: mono, fontSize: 11 },
        formatter: (p: { data?: { row?: HeatmapRow; name?: string } }) => {
          const row = p.data?.row
          if (!row) return String(p.data?.name ?? '')
          const sign = row.change_pct >= 0 ? '+' : ''
          return [
            `<b>${row.symbol}</b> &nbsp; ${sign}${row.change_pct.toFixed(2)}%`,
            row.name,
            `${row.sector} · cap ${cap(row.market_cap)}`,
            `close ${row.close} · prev ${row.prev_close}`,
          ].join('<br/>')
        },
      },
      series: [
        {
          type: 'treemap',
          // Scroll to zoom, drag to pan, click a sector to drill into it —
          // the only way the $20B corner of a board led by a $5T name is ever
          // legible.
          roam: true,
          nodeClick: 'zoomToNode',
          animationDuration: 240,
          // The breadcrumb is the only way back out of a drilled-in sector,
          // so the treemap gives up a strip for it rather than letting it sit
          // on top of the tiles it is meant to help you leave.
          top: 0, left: 0, right: 0, bottom: 20,
          breadcrumb: {
            bottom: 0, height: 18,
            itemStyle: { color: token('--bg-deep', '#070c14'), borderColor: 'transparent',
              textStyle: { color: token('--ink-dim', '#8fa3b8'), fontFamily: mono, fontSize: 10 } },
          },
          // Sector header strip, like the boards this replaces.
          upperLabel: {
            show: true, height: 16, color: ink, fontFamily: mono, fontSize: 10,
            padding: [0, 4],
          },
          itemStyle: { borderColor: bg, borderWidth: 1, gapWidth: 1 },
          levels: [
            {
              itemStyle: { borderColor: bg, borderWidth: 3, gapWidth: 3 },
              color: [token('--bg-deep', '#070c14')],
            },
            {
              itemStyle: { borderColor: bg, borderWidth: 1, gapWidth: 1 },
              upperLabel: { show: true },
            },
          ],
          label: {
            fontFamily: mono, fontSize: 11, color: '#fff', overflow: 'truncate',
            formatter: (p: { data?: { row?: HeatmapRow }; name?: string }) => {
              const row = p.data?.row
              if (!row) return p.name ?? ''
              const sign = row.change_pct >= 0 ? '+' : ''
              return `${row.symbol}\n${sign}${row.change_pct.toFixed(2)}%`
            },
          },
          data,
        },
      ],
    })

    // A dock panel is resized by dragging a splitter, which fires no window
    // event — observe the host instead.
    const observer = new ResizeObserver(() => ec.resize())
    observer.observe(host.current)
    // Same link group the watchlist drives: pick a tile, the TradingView
    // panels on this page follow. Genesis holds no bars for most of these, so
    // this deliberately does not touch `CH`.
    ec.on('click', (p) => {
      const row = (p.data as { row?: HeatmapRow } | undefined)?.row
      if (row) {
        select(symbolLink(row.symbol))
        revealPanel('tradingview')
      }
    })
    return () => {
      observer.disconnect()
      ec.dispose()
      chart.current = null
    }
  }, [data, select])

  if (state.status === 'loading') return <Loading rows={6} label="pricing the index" />
  if (state.status !== 'ready') {
    return <Absent reason={state.reason} onRetry={reload} />
  }

  const body = state.data
  const settled = body.market_state !== 'REGULAR'

  return (
    <div className="flex flex-col h-full min-h-0" style={{ gap: 6, padding: 6 }}>
      <div className="flex items-center" style={{ gap: 6, flexWrap: 'wrap' }}>
        <span className="label" style={{ color: 'var(--ink)' }}>{body.index} · 1D</span>
        <Chip tone="warn" title="Public feed. Research scaffolding — never a number the risk engine reads.">TIER 3</Chip>
        <Chip tone={settled ? 'neutral' : 'core'} title={`Yahoo market state: ${body.market_state}`}>
          {settled ? 'SETTLED CLOSE' : 'INTRADAY — NOT THE CLOSE'}
        </Chip>
        <span className="label" style={{ color: 'var(--ink-faint)' }}>
          {body.rows.length} names
          {body.missing.length ? ` · ${body.missing.length} unpriced: ${body.missing.join(' ')}` : ''}
        </span>
        <button type="button" className="label" onClick={reload}
          style={{ marginLeft: 'auto', color: 'var(--ink-dim)', background: 'none',
            border: '1px solid var(--hairline)', borderRadius: 'var(--r-sm)', padding: '1px 6px' }}>
          refresh
        </button>
      </div>

      <div ref={host} style={{ flex: 1, minHeight: 0 }} />

      <div className="flex items-center" style={{ gap: 8 }}>
        <div className="flex" style={{ flex: '0 0 auto' }}>
          {[-3, -2, -1, 0, 1, 2, 3].map((pct) => (
            <div key={pct} title={`${pct > 0 ? '+' : ''}${pct}%`}
              style={{ width: 30, height: 10, background: changeColour(pct) }} />
          ))}
        </div>
        <span className="label" style={{ color: 'var(--ink-faint)' }}>
          −3% … +3%, clamped · area = market cap · scroll to zoom, click a sector to drill in
        </span>
        <span className="label" style={{ marginLeft: 'auto', color: 'var(--ink-ghost)' }}>
          {fetchedAt ? `read ${new Date(fetchedAt).toLocaleTimeString()}` : ''}
        </span>
      </div>
    </div>
  )
}
