// Spec: Genesis Markdown/60-UI/Index Movers.md
//
// `MOV` — one index on the day: a sunburst of its members (inner ring sectors,
// outer ring stocks, angle = index weight, colour = change) beside its top five
// gainers and losers. Click a sector to hone in: the pie, the centre figure and
// both lists all narrow to that group. Click a stock to put it on TradingView
// and in `CO`.
//
// Membership is the SPDR fund's own daily holdings (see `index_map.py`); every
// number here is computed server-side — this file picks a group and draws it.
// Tier 3, and it does not poll (`UI Stack §9`).

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts'
import { api, type MoverGroup, type MoverRow, type MoversBody } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Loading } from '@/components/States'
import { Chip } from '@/components/Primitives'
import { changeColour } from '@/lib/format'
import { revealPanel } from '@/workspace/dock'
import { useWorkspace } from '@/workspace/context'

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
const tone = (v: number | null | undefined) =>
  !v ? 'var(--ink-dim)' : v > 0 ? 'var(--verdict-pass)' : 'var(--verdict-blocked)'
const compact = (v: number | null, prefix = '') =>
  v === null ? '—' : prefix + new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(v)

// What a slice's angle measures. A row with no figure for the chosen basis is left out, not drawn as zero.
const SIZES = {
  weight: { label: 'Index wt', of: (r: MoverRow) => r.weight },
  market_cap: { label: 'Mkt cap', of: (r: MoverRow) => r.market_cap },
  close: { label: 'Price', of: (r: MoverRow) => r.close },
  volume: { label: 'Volume', of: (r: MoverRow) => r.volume },
  dollar_volume: { label: '$ Volume', of: (r: MoverRow) => r.dollar_volume },
  move: { label: '|Chg|', of: (r: MoverRow) => Math.abs(r.change_pct) },
  equal: { label: 'Equal', of: () => 1 },
} as const
type SizeBy = keyof typeof SIZES

// The whole-market universes get a button each; the eleven sector SPDRs are a
// dropdown of sector names, because nobody reads an index as "XLRE".
const INDEXES = ['SPX', 'NDX', 'DJIA', 'SML'] as const
const LABELS: Record<string, string> = { SPX: 'S&P 500', NDX: 'NAS 100', DJIA: 'DOW', SML: 'S&P 600' }

export function MoversPanel() {
  const [index, setIndex] = useState('SPX')
  const [sector, setSector] = useState<string | null>(null)
  const [view, setView] = useState<'map' | 'table'>('map')
  const [scope, setScope] = useState<'movers' | 'all'>('movers')
  const [sizeBy, setSizeBy] = useState<SizeBy>('weight')
  const { state, reload, fetchedAt } = useRead(() => api.movers(index), [index])
  const { select } = useWorkspace()

  // A sector from the last index means nothing in this one.
  useEffect(() => setSector(null), [index])

  const pick = useCallback((row: MoverRow) => {
    select({ tvSymbol: row.symbol, ticker: row.symbol })
    revealPanel('tradingview')
  }, [select])

  const body = state.status === 'ready' ? state.data : null
  const universes = body?.universes ?? INDEXES.map((code) => ({ code, name: code }))
  const sectors = universes.filter((u) => !INDEXES.includes(u.code as never))
  const single = body ? Object.keys(body.sectors).length <= 1 : false
  const group: MoverGroup | null = body ? (sector ? body.sectors[sector] ?? body.total : body.total) : null
  const rows = body ? (sector ? body.rows.filter((r) => r.sector === sector) : body.rows) : []

  return (
    <div className="flex flex-col h-full min-h-0" style={{ fontSize: 'var(--fs-sm)' }}>
      <div className="flex items-center gap-1 hairline-b" style={{ padding: '4px 8px', flexWrap: 'wrap', flexShrink: 0 }}>
        <select value={INDEXES.includes(index as never) ? '' : index} onChange={(e) => e.target.value && setIndex(e.target.value)}
          title="One GICS sector — the Select Sector SPDR that holds it"
          style={{ background: 'var(--bg-deep)', color: 'var(--ink)', border: '1px solid var(--hairline)', font: 'inherit', padding: '1px 4px' }}>
          <option value="">Sector…</option>
          {sectors.map((u) => <option key={u.code} value={u.code}>{u.name}</option>)}
        </select>
        {universes.filter((u) => INDEXES.includes(u.code as never)).map((u) => (
          <button key={u.code} type="button" className="btn-ghost" data-active={u.code === index}
            title={u.name} onClick={() => setIndex(u.code)}>
            {LABELS[u.code] ?? u.code}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <button type="button" className="btn-ghost" data-active={scope === 'movers'} title="Pie shows only the top gainers and losers"
          onClick={() => setScope('movers')}>Movers</button>
        <button type="button" className="btn-ghost" data-active={scope === 'all'} onClick={() => setScope('all')}>All</button>
        {view === 'map' && (
          <label className="label flex items-center gap-1" style={{ color: 'var(--ink-dim)' }}>
            size
            <select value={sizeBy} onChange={(e) => setSizeBy(e.target.value as SizeBy)}
              style={{ background: 'var(--bg-deep)', color: 'var(--ink)', border: '1px solid var(--hairline)', font: 'inherit', padding: '1px 4px' }}>
              {Object.entries(SIZES).map(([k, s]) => <option key={k} value={k}>{s.label}</option>)}
            </select>
          </label>
        )}
        <button type="button" className="btn-ghost" data-active={view === 'map'} onClick={() => setView('map')}>Map</button>
        <button type="button" className="btn-ghost" data-active={view === 'table'} onClick={() => setView('table')}>Table</button>
        {body && <span className="label" style={{ color: 'var(--ink-dim)' }}>{rows.length} members</span>}
        <button type="button" className="btn-ghost" onClick={reload}>refresh</button>
      </div>

      {state.status === 'loading' ? <Loading rows={6} label={`pricing ${index}`} />
        : state.status !== 'ready' || !body || !group ? <Absent reason={state.reason ?? 'no data'} onRetry={reload} />
          : (
            <>
              <div className="flex min-h-0" style={{ flex: 1, flexWrap: 'wrap', overflow: 'auto' }}>
                <div style={{ flex: '1 1 280px', minHeight: 260, position: 'relative' }}>
                  {view === 'map'
                    ? <Sunburst body={body} sector={sector} single={single} moversOnly={scope === 'movers'} sizeBy={sizeBy} onSector={setSector} onPick={pick} group={group} />
                    : <MemberTable rows={rows} onPick={pick} />}
                </div>
                <div style={{ flex: '0 1 320px', minWidth: 240, borderLeft: '1px solid var(--hairline)', padding: '6px 8px' }}>
                  {sector && (
                    <button type="button" className="btn-ghost" onClick={() => setSector(null)} style={{ marginBottom: 4 }}>
                      ← all of {body.index}
                    </button>
                  )}
                  <Movers title="Top gainers" rows={group.gainers} onPick={pick} />
                  <Movers title="Top losers" rows={group.losers} onPick={pick} />
                  <div className="label" style={{ color: 'var(--ink-faint)', marginTop: 6 }}>
                    {group.advancers} up · {group.decliners} down
                  </div>
                </div>
              </div>
              <Footer body={body} fetchedAt={fetchedAt} sizeBy={view === 'map' ? sizeBy : 'weight'} />
            </>
          )}
    </div>
  )
}

function Movers({ title, rows, onPick }: { title: string; rows: MoverRow[]; onPick: (r: MoverRow) => void }) {
  return (
    <section style={{ marginBottom: 8 }}>
      <div className="label" style={{ background: 'var(--bg-deep)', padding: '2px 6px', color: 'var(--ink-dim)' }}>{title.toUpperCase()}</div>
      {rows.length === 0 ? <div className="label" style={{ padding: '4px 6px', color: 'var(--ink-faint)' }}>none</div>
        : rows.map((r) => (
          <button key={r.symbol} type="button" onClick={() => onPick(r)} title={`${r.name} · ${r.sector} · ${r.weight.toFixed(2)}% of index · close ${r.close}`}
            className="flex items-center gap-2" style={{ width: '100%', background: 'none', border: 0, padding: '3px 6px', color: 'var(--ink)', cursor: 'pointer', textAlign: 'left' }}>
            <span className="num" style={{ width: 48, flexShrink: 0, fontWeight: 600 }}>{r.symbol}</span>
            <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--ink-dim)', fontSize: 'var(--fs-tiny)' }}>{r.name}</span>
            <span className="num" style={{ color: tone(r.change_pct) }}>{pct(r.change_pct)}</span>
          </button>
        ))}
    </section>
  )
}

function Sunburst({ body, sector, single, moversOnly, sizeBy, group, onSector, onPick }: {
  body: MoversBody; sector: string | null; single: boolean; moversOnly: boolean; sizeBy: SizeBy; group: MoverGroup
  onSector: (s: string) => void; onPick: (r: MoverRow) => void
}) {
  const host = useRef<HTMLDivElement>(null)
  // Outer ring only when one sector is in view; sectors wrap their members otherwise.
  // Movers-only draws just the group's top gainers and losers, still angled by weight,
  // with the colour scale stretched to the biggest move so the heat reads.
  const data = useMemo(() => {
    const size = SIZES[sizeBy].of
    const pool = (moversOnly ? [...group.gainers, ...group.losers] : body.rows).filter((r) => (size(r) ?? 0) > 0)
    const clamp = moversOnly ? Math.max(3, ...pool.map((r) => Math.abs(r.change_pct))) : 3
    const leaf = (r: MoverRow) => ({ name: r.symbol, value: size(r), itemStyle: { color: changeColour(r.change_pct, clamp) }, row: r })
    if (single || sector) return pool.filter((r) => !sector || r.sector === sector).map(leaf)
    return Object.entries(body.sectors)
      .map(([name, g]) => ({
        name,
        itemStyle: { color: changeColour(g.change_pct ?? 0) },
        group: g,
        children: pool.filter((r) => r.sector === name).map(leaf),
      }))
      .filter((s) => s.children.length > 0)
  }, [body, group, sector, single, moversOnly, sizeBy])

  useEffect(() => {
    if (!host.current) return
    const css = getComputedStyle(document.documentElement)
    const token = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback
    const bg = token('--bg-panel', '#0d1622')
    const ink = token('--ink', '#eef4fc')
    const mono = token('--font-mono', 'monospace')
    const sans = token('--font-ui', 'sans-serif')
    const dim = token('--ink-dim', '#8a9bb0')
    const hairline = token('--hairline', '#16202e')
    const up = token('--verdict-pass', '#22c55e')
    const down = token('--verdict-blocked', '#ef4444')
    const nested = !(single || sector)
    const esc = (s: string) => s.replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`)
    const stat = (k: string, v: string, colour = ink) =>
      `<div style="color:${dim};font-size:10px;letter-spacing:.06em">${k}</div><div style="text-align:right;font-family:${mono};color:${colour}">${v}</div>`
    // A small company card: who it is, what it did, how much of the index it is.
    const card = (title: string, subtitle: string, change: number | null, stats: string, hint: string) => `
      <div style="min-width:220px;font-family:${sans}">
        <div style="display:flex;align-items:baseline;gap:10px">
          <span style="font-family:${mono};font-size:14px;font-weight:700;color:${ink}">${esc(title)}</span>
          <span style="margin-left:auto;font-family:${mono};font-weight:600;color:${!change ? dim : change > 0 ? up : down}">${pct(change)}</span>
        </div>
        <div style="color:${dim};font-size:11px;margin:2px 0 8px;max-width:260px;white-space:normal">${esc(subtitle)}</div>
        <div style="display:grid;grid-template-columns:auto 1fr;gap:3px 16px;border-top:1px solid ${hairline};padding-top:6px">${stats}</div>
        <div style="color:${dim};font-size:10px;margin-top:6px;opacity:.7">${hint}</div>
      </div>`
    const symbolLabel = (fontSize: number) => ({
      show: true, rotate: 'radial', color: '#fff', fontFamily: mono, fontWeight: 700, fontSize, minAngle: 5,
      letterSpacing: 0.5, textShadowColor: 'rgba(0,0,0,.45)', textShadowBlur: 3,
    })
    const ec = echarts.init(host.current, undefined, { renderer: 'canvas' })
    ec.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        backgroundColor: token('--bg-raised', '#131c28'), borderColor: hairline, padding: [10, 12],
        extraCssText: 'border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,.45);',
        textStyle: { color: ink, fontFamily: sans, fontSize: 12 },
        formatter: (p: { data?: { row?: MoverRow; group?: MoverGroup; name?: string } }) => {
          const r = p.data?.row, g = p.data?.group
          if (r) return card(r.symbol, r.name, r.change_pct,
            stat('SECTOR', esc(r.sector)) + stat('CLOSE', r.close.toFixed(2)) + stat('INDEX WEIGHT', `${r.weight.toFixed(2)}%`)
              + stat('MARKET CAP', compact(r.market_cap, '$')) + stat('VOLUME', compact(r.volume)) + stat('$ VOLUME', compact(r.dollar_volume, '$')),
            'click to open chart')
          if (g) return card(p.data?.name ?? '', `${g.count} names in ${body.code}`, g.change_pct,
            stat('INDEX WEIGHT', `${g.weight.toFixed(1)}%`) + stat('UP / DOWN', `<span style="color:${up}">${g.advancers}</span> / <span style="color:${down}">${g.decliners}</span>`),
            'click to hone in')
          return esc(String(p.data?.name ?? ''))
        },
      },
      series: [{
        type: 'sunburst',
        data,
        radius: ['28%', '92%'],
        sort: undefined,
        // Drill-down is handled by React state, so the lists narrow with the pie.
        nodeClick: false,
        itemStyle: { borderColor: bg, borderWidth: 1 },
        label: { show: false },
        levels: nested
          ? [{}, { r0: '28%', r: '52%', label: { show: true, rotate: 'tangential', color: 'rgba(255,255,255,.85)', fontFamily: sans, fontSize: 10, fontWeight: 500, minAngle: 14 } },
            { r0: '53%', r: '92%', label: symbolLabel(moversOnly ? 12 : 9) }]
          : [{}, { r0: '28%', r: '92%', label: symbolLabel(moversOnly ? 13 : 10) }],
        emphasis: { focus: 'ancestor' },
      }],
    })
    const observer = new ResizeObserver(() => ec.resize())
    observer.observe(host.current)
    ec.on('click', (p) => {
      const d = p.data as { row?: MoverRow; group?: MoverGroup; name?: string } | undefined
      if (d?.row) onPick(d.row)
      else if (d?.group && d.name) onSector(d.name)
    })
    return () => { observer.disconnect(); ec.dispose() }
  }, [data, single, sector, moversOnly, onPick, onSector])

  return (
    <>
      <div ref={host} style={{ position: 'absolute', inset: 0 }} role="img"
        aria-label={`${sector ?? body.index} ${moversOnly ? 'top gainers and losers' : 'members'} by index weight, coloured by change`} />
      <div className="num" style={{
        position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%, -50%)',
        textAlign: 'center', pointerEvents: 'none', maxWidth: '24%',
      }}>
        <div style={{ color: 'var(--ink)', fontSize: 'var(--fs-sm)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sector ?? body.code}</div>
        <div style={{ color: tone(group.change_pct), fontSize: 'var(--fs-tiny)' }}>{pct(group.change_pct)}</div>
      </div>
    </>
  )
}

function MemberTable({ rows, onPick }: { rows: MoverRow[]; onPick: (r: MoverRow) => void }) {
  const sorted = [...rows].sort((a, b) => b.change_pct - a.change_pct)
  return (
    <div style={{ position: 'absolute', inset: 0, overflow: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr className="label" style={{ color: 'var(--ink-dim)', textAlign: 'left', position: 'sticky', top: 0, background: 'var(--bg-panel)' }}>
            <th style={{ padding: '3px 8px' }}>Symbol</th><th>Name</th><th>Sector</th>
            <th style={{ textAlign: 'right' }}>Weight</th><th style={{ textAlign: 'right' }}>Close</th><th style={{ textAlign: 'right', paddingRight: 8 }}>Chg</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.symbol} onClick={() => onPick(r)} style={{ cursor: 'pointer', borderTop: '1px solid var(--hairline)' }}>
              <td className="num" style={{ padding: '2px 8px', fontWeight: 600 }}>{r.symbol}</td>
              <td style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--ink-dim)' }}>{r.name}</td>
              <td style={{ color: 'var(--ink-dim)', whiteSpace: 'nowrap' }}>{r.sector}</td>
              <td className="num" style={{ textAlign: 'right' }}>{r.weight.toFixed(2)}%</td>
              <td className="num" style={{ textAlign: 'right' }}>{r.close.toFixed(2)}</td>
              <td className="num" style={{ textAlign: 'right', paddingRight: 8, color: tone(r.change_pct) }}>{pct(r.change_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Footer({ body, fetchedAt, sizeBy }: { body: MoversBody; fetchedAt: number | null; sizeBy: SizeBy }) {
  const settled = body.market_state !== 'REGULAR'
  return (
    <div className="flex items-center gap-2 hairline-t" style={{ padding: '4px 8px', flexWrap: 'wrap', flexShrink: 0 }}>
      <Chip tone="warn" title="Public feed. Research scaffolding — never a number the risk engine reads.">TIER 3</Chip>
      <Chip tone={settled ? 'neutral' : 'core'} title={`Yahoo market state: ${body.market_state}`}>
        {settled ? 'SETTLED CLOSE' : 'INTRADAY — NOT THE CLOSE'}
      </Chip>
      <span className="label" style={{ color: 'var(--ink-faint)' }}>
        angle = {sizeBy === 'weight'
          ? `${body.weight_basis}${body.holdings_as_of ? ` as of ${body.holdings_as_of}` : ''}`
          : SIZES[sizeBy].label.toLowerCase()} · centre = weighted member change
        {body.missing.length ? ` · unpriced: ${body.missing.join(' ')}` : ''}
      </span>
      <span className="label" style={{ marginLeft: 'auto', color: 'var(--ink-ghost)' }}>
        {fetchedAt ? `read ${new Date(fetchedAt).toLocaleTimeString()}` : ''}
      </span>
    </div>
  )
}
