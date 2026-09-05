// Spec: Genesis Markdown/10-Architecture/Charting Engine.md · 10-Architecture/Market Data Sources.md
//
// The charting panels. Every one of them reads the bar store — there is no
// symbol here that Genesis does not hold data for.
//
// That is a deliberate constraint and it is why there is no "add symbol" box.
// A watchlist that lets you type `TSLA` and then shows an empty chart has
// taught you nothing except that the UI accepts text. The series list *is* the
// universe, because the universe is whatever has been ingested, and the way to
// add to it is to ingest it.

import { useState } from 'react'
import { api, get, type BarRow, type SymbolRow } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { Chip, Metric, Num, PanelBody, Section, Table } from '@/components/Primitives'
import { PriceChart } from '@/components/charts/PriceChart'
import { useDefaultSymbol, useWorkspace } from '@/workspace/context'
import { stagger } from '@/lib/motion'
import { price, pricePrecision } from '@/lib/format'

/** A stable empty array, so the default-selection effect does not re-fire. */
const EMPTY: { symbol_id: string; timeframe: string }[] = []

/** Trust tier → how it should read. Lower is better; 1 is the venue's book. */
function tierTone(tier: number): 'good' | 'warn' | 'neutral' {
  if (tier <= 1) return 'good'
  if (tier <= 2) return 'neutral'
  return 'warn'
}

function ago(iso: string | null): string {
  if (!iso) return 'never'
  const delta = Date.now() - new Date(iso).getTime()
  const days = Math.floor(delta / 86_400_000)
  if (days > 0) return `${days}d ago`
  const hours = Math.floor(delta / 3_600_000)
  return hours > 0 ? `${hours}h ago` : 'today'
}

// ---------------------------------------------------------------------------
// Series list — the watchlist, and the universe
// ---------------------------------------------------------------------------

export function WatchlistPanel() {
  const { symbolId, select } = useWorkspace()
  const { state, reload } = useRead(() => api.symbols(), [])
  useDefaultSymbol(state.status === 'ready' ? state.data.symbols : EMPTY)

  if (state.status === 'loading') return <Loading rows={4} label="series" />
  if (state.status === 'error') return <Absent reason={state.reason} onRetry={reload} />
  if (state.status === 'absent') return <Absent reason={state.reason} onRetry={reload} />

  const rows = state.data.symbols
  if (!rows.length) {
    return (
      <Empty hint="The bar store is empty. Ingest a series — `genesis chart AAPL` will fetch and store one — and it will appear here.">
        no series held
      </Empty>
    )
  }

  return (
    <div className="flex flex-col h-full min-h-0" data-focus-scope="true">
      {rows.map((row, index) => {
        const focused = symbolId === null || symbolId === row.symbol_id
        const selected = symbolId === row.symbol_id
        return (
          <button
            key={`${row.symbol_id}:${row.timeframe}`}
            className="row-hit lift flex flex-col gap-0.5"
            data-selected={selected}
            data-focused={focused}
            style={{
              ['--i' as string]: stagger(index),
              padding: '5px 8px', textAlign: 'left',
              borderBottom: '1px solid var(--bg-raised)',
            }}
            onClick={() => select({ symbolId: row.symbol_id, timeframe: row.timeframe })}
          >
            <div className="flex items-baseline gap-2">
              <span style={{ fontSize: 'var(--fs-sm)', fontWeight: 600, letterSpacing: '0.02em' }}>
                {row.symbol}
              </span>
              <span className="label" style={{ letterSpacing: '0.1em' }}>{row.timeframe}</span>
              <span style={{ flex: 1 }} />
              <Chip tone={tierTone(row.coverage[0]?.tier ?? 9)}>
                T{row.coverage[0]?.tier ?? '?'}
              </Chip>
            </div>
            <div className="flex items-baseline gap-2 label" style={{ color: 'var(--ink-ghost)' }}>
              <span className="num">{row.bars.toLocaleString()} bars</span>
              <span>·</span>
              <span>{ago(row.last_bar_at)}</span>
            </div>
          </button>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// The chart
// ---------------------------------------------------------------------------

export function ChartPanel() {
  const { symbolId, timeframe } = useWorkspace()
  const [hover, setHover] = useState<BarRow | null>(null)

  const { state, reload } = useRead(
    () => api.bars(symbolId ?? '', timeframe, 1000),
    [symbolId, timeframe],
  )

  if (!symbolId) {
    return <Empty hint="Everything drawn here comes from bars Genesis holds.">pick a series</Empty>
  }
  if (state.status === 'loading') return <Loading rows={5} label={symbolId} />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  const { bars, symbol, count, last_bar_at } = state.data
  if (!bars.length) return <Empty>no bars in this window</Empty>

  const tier = Math.max(...bars.map((b) => b.tier))
  // DuckDB returns the column's full scale, so AAPL's close arrives as
  // "319.97000122". Printing that implies eight decimals of a price quoted in
  // cents. Inferred from the data rather than hardcoded to 2, because a future
  // and an FX pair are both real and both wrong at 2.
  const places = pricePrecision(bars.map((b) => b.close))
  const shown = hover ?? bars[bars.length - 1]
  const previous = hover
    ? bars[bars.indexOf(hover) - 1]
    : bars[bars.length - 2]
  const change =
    previous ? Number(shown.close) - Number(previous.close) : null
  const changePct =
    previous && Number(previous.close) !== 0
      ? (Number(shown.close) / Number(previous.close) - 1) * 100
      : null

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* The readout. Follows the crosshair, and shows the last CLOSED bar
          when the pointer is away -- never a synthesised live price. */}
      <div
        className="flex items-baseline gap-3 hairline-b"
        style={{ padding: '4px 8px', flexShrink: 0 }}
      >
        <span style={{ fontSize: 'var(--fs-base)', fontWeight: 600 }}>{symbol}</span>
        <span className="label">{timeframe}</span>
        <span style={{ fontSize: 'var(--fs-lg)' }}>
          {/* Trimmed, never parsed: `price()` slices the decimal string, so
              the value keeps its exact digits and simply stops showing
              storage padding. */}
          <span className="num">{price(shown.close, places)}</span>
        </span>
        {change !== null && (
          <>
            <Num value={change} digits={2} signed tone />
            <Num value={changePct} digits={2} suffix="%" signed tone />
          </>
        )}
        <span style={{ flex: 1 }} />
        <Chip tone={tierTone(tier)} title="Market Data Sources trust tier — 1 is the venue's own book">
          tier {tier} · {shown.source}
        </Chip>
        <span className="label" style={{ color: 'var(--ink-ghost)' }}>
          {count} bars · last {ago(last_bar_at)}
        </span>
      </div>

      <div style={{ flex: 1, minHeight: 0 }}>
        <PriceChart bars={bars} tier={tier} onCrosshair={setHover} />
      </div>

      {/* Said once, plainly, rather than implied by a still chart. */}
      <div
        className="hairline-t label"
        style={{ padding: '2px 8px', flexShrink: 0, color: 'var(--ink-ghost)',
          textTransform: 'none', letterSpacing: 0 }}
      >
        closed bars only — no realtime feed is wired, so the right edge is the
        last bar on disk
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Instrument detail
// ---------------------------------------------------------------------------

export function SymbolDetailPanel() {
  const { symbolId, timeframe } = useWorkspace()
  const { state } = useRead(
    () => api.bars(symbolId ?? '', timeframe, 400),
    [symbolId, timeframe],
  )

  if (!symbolId) return <Empty>pick a series</Empty>
  if (state.status === 'loading') return <Loading rows={4} />
  if (state.status !== 'ready') return <Absent reason={state.reason} />

  const bars = state.data.bars
  if (!bars.length) return <Empty>no bars</Empty>

  const closes = bars.map((b) => Number(b.close))
  const last = closes[closes.length - 1]
  const high = Math.max(...bars.map((b) => Number(b.high)))
  const low = Math.min(...bars.map((b) => Number(b.low)))
  const first = closes[0]
  const volumes = bars.map((b) => Number(b.volume))
  const avgVolume = volumes.reduce((a, b) => a + b, 0) / volumes.length

  // Realised volatility, annualised on 252 sessions. Labelled with its window
  // because a 400-bar sigma and a 20-bar sigma are different claims.
  const returns = closes.slice(1).map((c, i) => Math.log(c / closes[i]))
  const mean = returns.reduce((a, b) => a + b, 0) / (returns.length || 1)
  const variance =
    returns.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(returns.length - 1, 1)
  const vol = Math.sqrt(variance * 252) * 100

  return (
    <PanelBody>
      <Section title="window" dense>
        <div className="flex flex-wrap gap-1.5">
          <Metric label="last close" value={bars[bars.length - 1].close} />
          <Metric label="change" value={(last / first - 1) * 100} suffix="%" signed tone />
          <Metric label="high" value={high} />
          <Metric label="low" value={low} />
          <Metric
            label="realised vol"
            value={vol}
            suffix="%"
            hint={`annualised, ${returns.length} sessions`}
          />
          <Metric label="avg volume" value={avgVolume / 1e6} suffix="M" digits={1} />
        </div>
      </Section>

      <Section title="identity" dense>
        <dl className="flex flex-col gap-1" style={{ margin: 0, fontSize: 'var(--fs-tiny)' }}>
          {[
            ['symbol id', state.data.symbol_id],
            ['timeframe', state.data.timeframe],
            ['bars held', String(state.data.count)],
            ['adjusted', bars[bars.length - 1].adjusted ? 'yes (splits & dividends)' : 'no'],
          ].map(([term, value]) => (
            <div key={term} className="flex justify-between gap-3">
              <dt className="label" style={{ letterSpacing: '0.08em' }}>{term}</dt>
              <dd className="num" style={{ margin: 0, color: 'var(--ink-dim)' }}>{value}</dd>
            </div>
          ))}
        </dl>
      </Section>
    </PanelBody>
  )
}

// ---------------------------------------------------------------------------
// Coverage — provenance, per window
// ---------------------------------------------------------------------------

export function CoveragePanel() {
  const { symbolId, select } = useWorkspace()
  const { state, reload } = useRead(() => api.symbols(), [])

  if (state.status === 'loading') return <Loading rows={3} label="coverage" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  const rows: (SymbolRow & { window: SymbolRow['coverage'][number] })[] = []
  for (const symbol of state.data.symbols) {
    for (const window of symbol.coverage) rows.push({ ...symbol, window })
  }
  if (!rows.length) return <Empty>nothing ingested yet</Empty>

  return (
    <PanelBody pad={0}>
      <Table
        rows={rows}
        keyOf={(row, i) => `${row.symbol_id}:${i}`}
        selectedKey={symbolId ? `${symbolId}:0` : null}
        onSelect={(row) => select({ symbolId: row.symbol_id, timeframe: row.timeframe })}
        columns={[
          {
            key: 'symbol', header: 'series', width: 92,
            render: (row) => (
              <span style={{ color: 'var(--ink)' }}>{row.symbol} <span className="label">{row.timeframe}</span></span>
            ),
          },
          {
            key: 'from', header: 'from', width: 82,
            render: (row) => <span className="num">{row.window.start.slice(0, 10)}</span>,
          },
          {
            key: 'to', header: 'to', width: 82,
            render: (row) => <span className="num">{row.window.end.slice(0, 10)}</span>,
          },
          {
            key: 'bars', header: 'bars', align: 'right', width: 58,
            render: (row) => <Num value={row.window.bar_count} digits={0} />,
          },
          {
            key: 'source', header: 'source',
            render: (row) => (
              <span className="label" style={{ letterSpacing: 0, textTransform: 'none' }}>
                {row.window.source}
              </span>
            ),
          },
          {
            key: 'tier', header: 'tier', align: 'right', width: 46,
            render: (row) => <Chip tone={tierTone(row.window.tier)}>T{row.window.tier}</Chip>,
          },
        ]}
      />
      <div
        className="label"
        style={{ padding: '4px 8px', color: 'var(--ink-ghost)',
          textTransform: 'none', letterSpacing: 0, lineHeight: 1.5 }}
      >
        Tier is trust, not quality: tier 1 is the venue's own book and the only
        thing the pre-trade risk engine may read. Everything here is tier 3.
      </div>
    </PanelBody>
  )
}

// ---------------------------------------------------------------------------
// Markup — the charts Genesis drew, as opposed to the price
// ---------------------------------------------------------------------------

export function MarkupSpecsPanel() {
  const { state, reload } = useRead(
    () => get<{ count: number; active: Record<string, unknown>[] }>('/v1/charting/specs'),
    [],
  )

  if (state.status === 'loading') return <Loading rows={3} label="markup" />
  if (state.status === 'absent') {
    return (
      <Absent
        reason={`${state.reason} — Genesis writes markup specs when it analyses a chart; none have been written on this machine.`}
        onRetry={reload}
      />
    )
  }
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  const specs = state.data.active
  if (!specs.length) {
    return (
      <Empty hint="A markup spec is a chart annotation Genesis produced — levels, patterns, structure. Ask it to analyse a chart and one appears here.">
        no active markup
      </Empty>
    )
  }

  return (
    <PanelBody pad={0}>
      <Table
        rows={specs}
        keyOf={(row, i) => String(row.spec_id ?? i)}
        columns={[
          {
            key: 'symbol', header: 'symbol', width: 80,
            render: (row) => <span style={{ color: 'var(--ink)' }}>{String(row.symbol ?? '—')}</span>,
          },
          {
            key: 'timeframe', header: 'tf', width: 44,
            render: (row) => <span className="label">{String(row.timeframe ?? '')}</span>,
          },
          {
            key: 'author', header: 'drawn by',
            render: (row) => (
              <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>
                {String(row.author ?? row.agent ?? 'unknown')}
              </span>
            ),
          },
          {
            key: 'created', header: 'when', align: 'right', width: 84,
            render: (row) => (
              <span className="num">{String(row.created_at ?? '').slice(0, 10) || '—'}</span>
            ),
          },
        ]}
      />
    </PanelBody>
  )
}
