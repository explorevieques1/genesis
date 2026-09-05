// Spec: Genesis Markdown/20-Agents/Strategy/Agent — Backtest Runner.md
//
// The backtest surface: what `nautilus_trader` produced, made readable.
//
// This is the page that replaces reading a tearsheet in a terminal, and the
// design problem it has is not "how do I draw an equity curve". It is that a
// backtest report is the most over-trusted artefact in trading. Every number
// here is conditional — on the sample, on the data tier, on whether the
// strategy even ran — and a report that presents them as flat facts is worse
// than no report, because it is persuasive.
//
// So the layout inverts the usual order. **Caveats come first, above the
// numbers, in prose.** Not a footnote, not an icon, not collapsed behind a
// disclosure triangle. If a run produced two trades, the first thing on the
// screen says that two trades is not a sample — before the Sharpe ratio it
// would otherwise be read against.
//
// The statistics keep Nautilus' own three-way split (`pnls` / `returns` /
// `general`) rather than being flattened into one grid. That split is
// meaningful: a currency-denominated figure, a dimensionless ratio and a
// position-count statistic are three different kinds of claim, and mixing them
// into one wall of tiles invites comparing things that are not comparable.

import { useCallback, useMemo, useState } from 'react'
import { api, get, post } from '@/api/client'
import { useRead } from '@/api/useRead'
import { useCapability } from '@/api/capabilities'
import { Absent, Empty, Loading, RequiresCapability } from '@/components/States'
import {
  Caveats, Chip, Metric, Num, PanelBody, Section, Table,
} from '@/components/Primitives'
import { EquityCurve } from '@/components/charts/EquityCurve'
import { useDefaultSymbol, useWorkspace } from '@/workspace/context'

/** A stable empty array, so the default-selection effect does not re-fire. */
const EMPTY: { symbol_id: string; timeframe: string }[] = []

interface Template {
  id: string
  label: string
  params: { name: string; type: string; default: number; min: number; max: number }[]
}

interface RunBody {
  run_id: string
  spec: Record<string, unknown>
  stats: {
    pnls: Record<string, Record<string, number | null>>
    returns: Record<string, number | null>
    general: Record<string, number | null>
  }
  equity: { time: number; ts: string; total: string; free: string; currency: string }[]
  returns_series: { time: number; value: number | null }[]
  positions: Record<string, unknown>[]
  orders: Record<string, unknown>[]
  fills: Record<string, unknown>[]
  diagnostics: { bars_seen: number; undecidable_bars: number; errors: string[] }
  meta: Record<string, unknown>
  warnings: string[]
}

// ---------------------------------------------------------------------------
// Runner — choose a strategy, run it
// ---------------------------------------------------------------------------

export function BacktestRunnerPanel() {
  const capability = useCapability('backtest.engine')
  return (
    <RequiresCapability capability={capability}>
      {() => <Runner />}
    </RequiresCapability>
  )
}

function Runner() {
  const { symbolId, timeframe, select, setRun } = useWorkspace()
  const templates = useRead(
    () => get<{ templates: Template[] }>('/v1/backtest/templates'), [],
  )
  const symbols = useRead(() => api.symbols(), [])
  useDefaultSymbol(symbols.state.status === 'ready' ? symbols.state.data.symbols : EMPTY)

  const [templateId, setTemplateId] = useState('macd')
  const [params, setParams] = useState<Record<string, number>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const template = useMemo(
    () => templates.state.status === 'ready'
      ? templates.state.data.templates.find((t) => t.id === templateId) ?? null
      : null,
    [templates.state, templateId],
  )

  const run = useCallback(async () => {
    if (!symbolId) { setError('pick a series first'); return }
    setBusy(true)
    setError(null)
    try {
      const body = await post<{ ok: boolean; error?: string } & RunBody>(
        '/v1/backtest/run',
        { template: templateId, symbol: symbolId, timeframe, params },
      )
      if (!body.ok) { setError(body.error ?? 'the run failed'); return }
      setRun(body as unknown as Record<string, unknown>)
      select({ runId: body.run_id })
    } catch (exc) {
      // The daemon's own message, verbatim. A 422 here means the engine
      // refused the window, which is a real answer and worth reading.
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }, [symbolId, timeframe, templateId, params, select, setRun])

  if (templates.state.status === 'loading') return <Loading rows={4} label="strategies" />
  if (templates.state.status !== 'ready') {
    return <Absent reason={templates.state.reason} onRetry={templates.reload} />
  }

  const available = symbols.state.status === 'ready' ? symbols.state.data.symbols : []

  return (
    <PanelBody>
      <Section title="series" dense>
        {available.length === 0 ? (
          <Empty hint="A backtest runs over bars on disk. Ingest a series first.">
            no series held
          </Empty>
        ) : (
          <div className="flex flex-col gap-0.5">
            {available.map((row) => (
              <button
                key={row.symbol_id}
                className="row-hit"
                data-selected={symbolId === row.symbol_id}
                style={{ padding: '3px 7px', textAlign: 'left', fontSize: 'var(--fs-tiny)' }}
                onClick={() => select({ symbolId: row.symbol_id, timeframe: row.timeframe })}
              >
                <span style={{ color: 'var(--ink)' }}>{row.symbol}</span>{' '}
                <span className="label">{row.timeframe} · {row.bars} bars</span>
              </button>
            ))}
          </div>
        )}
      </Section>

      <Section title="strategy" dense>
        <div className="flex flex-col gap-1">
          {templates.state.data.templates.map((t) => (
            <button
              key={t.id}
              className="row-hit"
              data-selected={templateId === t.id}
              style={{ padding: '3px 7px', textAlign: 'left', fontSize: 'var(--fs-tiny)' }}
              onClick={() => { setTemplateId(t.id); setParams({}) }}
            >
              {t.label}
            </button>
          ))}
        </div>
      </Section>

      {template && (
        <Section title="parameters" dense>
          <div className="flex flex-col gap-1.5">
            {template.params.map((param) => (
              <label key={param.name} className="flex items-center gap-2">
                <span className="label" style={{ width: 82, letterSpacing: '0.06em' }}>
                  {param.name.replace(/_/g, ' ')}
                </span>
                <input
                  className="field num"
                  type="number"
                  style={{ width: 66 }}
                  min={param.min}
                  max={param.max}
                  value={params[param.name] ?? param.default}
                  onChange={(e) =>
                    setParams((p) => ({ ...p, [param.name]: Number(e.target.value) }))
                  }
                />
              </label>
            ))}
          </div>
        </Section>
      )}

      <button
        className="btn"
        disabled={busy || !symbolId}
        onClick={run}
        style={{ justifyContent: 'center', padding: '6px 10px' }}
      >
        {busy ? 'running…' : 'run backtest'}
      </button>

      {error && (
        <div
          style={{
            fontSize: 'var(--fs-tiny)', color: 'var(--state-down)',
            border: '1px solid var(--hairline)', borderLeft: '2px solid var(--state-down)',
            background: 'var(--bg-inset)', padding: '6px 8px',
            borderRadius: 'var(--r-sm)', lineHeight: 1.5,
          }}
        >
          {error}
        </div>
      )}

      <div
        className="label"
        style={{ color: 'var(--ink-ghost)', textTransform: 'none',
          letterSpacing: 0, lineHeight: 1.5, marginTop: 'auto' }}
      >
        Simulated by nautilus_trader against stored bars. Strategies are selected
        from a closed vocabulary — nothing here writes or runs generated code.
      </div>
    </PanelBody>
  )
}

// ---------------------------------------------------------------------------
// Equity
// ---------------------------------------------------------------------------

export function BacktestEquityPanel() {
  const { run } = useWorkspace()
  if (!run) return <Empty hint="Pick a strategy and run it, or open a past run from History.">no run open</Empty>

  const body = run as unknown as RunBody
  const meta = body.meta ?? {}

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-baseline gap-3 hairline-b" style={{ padding: '5px 8px', flexShrink: 0 }}>
        <span style={{ fontSize: 'var(--fs-base)', fontWeight: 600 }}>
          {String((body.spec as { name?: string })?.name ?? 'run')}
        </span>
        <span className="label">{String(meta.symbol_id ?? '')} · {String(meta.timeframe ?? '')}</span>
        <span style={{ flex: 1 }} />
        <Chip tone="core" title="the engine that produced these numbers">
          {String(meta.engine ?? '?')} {String(meta.engine_version ?? '')}
        </Chip>
        <span className="label" style={{ color: 'var(--ink-ghost)' }}>
          {String(meta.bars ?? 0)} bars · {String(meta.wall_ms ?? 0)}ms
        </span>
      </div>

      {/* Caveats above the numbers. See the module docstring. */}
      {body.warnings?.length > 0 && (
        <div style={{ padding: 8, flexShrink: 0 }}>
          <Caveats items={body.warnings} />
        </div>
      )}

      <div style={{ flex: 1, minHeight: 0, padding: 8 }}>
        {body.equity?.length > 1 ? (
          <EquityCurve
            points={body.equity.map((p) => ({ time: p.time, value: Number(p.total) }))}
            markers={(body.positions ?? []).map((position) => ({
              time: Math.floor(new Date(String(position.ts_closed ?? position.ts_opened)).getTime() / 1000),
              won: Number(String(position.realized_pnl ?? '0').split(' ')[0]) > 0,
            }))}
          />
        ) : (
          <Empty hint="The account balance never changed, because no position was opened.">
            no equity movement
          </Empty>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Statistics — Nautilus' three groups, kept apart
// ---------------------------------------------------------------------------

export function BacktestStatsPanel() {
  const { run } = useWorkspace()
  if (!run) return <Empty>no run open</Empty>

  const body = run as unknown as RunBody
  const stats = body.stats ?? { pnls: {}, returns: {}, general: {} }
  const positions = body.positions?.length ?? 0
  // The threshold `genesis.metrics` uses for a sample it will act on.
  const conclusive = positions >= 30

  return (
    <PanelBody>
      {Object.entries(stats.pnls ?? {}).map(([currency, block]) => (
        <Section key={currency} title={`profit & loss · ${currency}`} dense>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(block).map(([name, value]) => (
              <Metric
                key={name}
                label={name}
                value={value}
                digits={name.includes('%') || name.includes('Rate') ? 3 : 2}
                tone={name.includes('PnL') || name.includes('Expectancy')}
                signed={name.includes('PnL')}
              />
            ))}
          </div>
        </Section>
      ))}

      <Section
        title="returns"
        dense
        actions={
          !conclusive ? (
            <Chip tone="warn" title="genesis.metrics treats 30 closed trades as the threshold for acting on a statistic">
              {positions} trades
            </Chip>
          ) : null
        }
      >
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(stats.returns ?? {}).map(([name, value]) => (
            <Metric
              key={name}
              label={name}
              value={value}
              digits={3}
              wide={name.length > 18}
              // Every ratio inherits the sample's authority, so each one says
              // what it rests on rather than letting the reader assume.
              hint={conclusive ? undefined : `over ${positions} trades`}
            />
          ))}
        </div>
      </Section>

      {Object.keys(stats.general ?? {}).length > 0 && (
        <Section title="general" dense>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(stats.general).map(([name, value]) => (
              <Metric key={name} label={name} value={value} digits={3} />
            ))}
          </div>
        </Section>
      )}

      <Section title="run" dense>
        <div className="flex flex-wrap gap-1.5">
          <Metric label="bars seen" value={body.diagnostics?.bars_seen} digits={0} />
          <Metric
            label="undecidable"
            value={body.diagnostics?.undecidable_bars}
            digits={0}
            hint="indicators still warming up"
          />
          <Metric label="orders" value={Number(body.meta?.total_orders ?? 0)} digits={0} />
          <Metric label="positions" value={positions} digits={0} />
        </div>
      </Section>

      {body.diagnostics?.errors?.length > 0 && (
        <Section title="the strategy raised" dense>
          <Caveats items={body.diagnostics.errors} />
        </Section>
      )}
    </PanelBody>
  )
}

// ---------------------------------------------------------------------------
// Trades
// ---------------------------------------------------------------------------

export function BacktestTradesPanel() {
  const { run } = useWorkspace()
  const [tab, setTab] = useState<'positions' | 'orders' | 'fills'>('positions')
  if (!run) return <Empty>no run open</Empty>

  const body = run as unknown as RunBody
  const rows = body[tab] ?? []

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-1 hairline-b" style={{ padding: '3px 6px', flexShrink: 0 }}>
        {(['positions', 'orders', 'fills'] as const).map((id) => (
          <button
            key={id}
            className="btn-ghost"
            data-active={tab === id}
            style={{
              color: tab === id ? 'var(--ink)' : undefined,
              borderColor: tab === id ? 'var(--hairline-bright)' : undefined,
            }}
            onClick={() => setTab(id)}
          >
            {id} <span className="num">{(body[id] ?? []).length}</span>
          </button>
        ))}
      </div>

      {rows.length === 0 ? (
        <Empty hint="Nautilus produced no rows of this kind for this run.">nothing to show</Empty>
      ) : (
        <Table
          rows={rows}
          keyOf={(row, i) => String(row.position_id ?? row.client_order_id ?? i)}
          columns={columnsFor(tab)}
        />
      )}
    </div>
  )
}

/** Column sets, per report. Field names are Nautilus'. */
function columnsFor(tab: 'positions' | 'orders' | 'fills') {
  const time = (value: unknown) => String(value ?? '').slice(0, 16).replace('T', ' ')
  // Nautilus formats money as "-557.61 USD"; split so the figure can be
  // right-aligned and toned while the currency stays legible.
  const money = (value: unknown) => {
    const [amount] = String(value ?? '').split(' ')
    return <Num value={amount} digits={2} signed tone />
  }

  if (tab === 'positions') {
    return [
      { key: 'opened', header: 'opened', width: 106, render: (r: Record<string, unknown>) => <span className="num">{time(r.ts_opened)}</span> },
      { key: 'closed', header: 'closed', width: 106, render: (r: Record<string, unknown>) => <span className="num">{time(r.ts_closed)}</span> },
      { key: 'side', header: 'side', width: 46, render: (r: Record<string, unknown>) => <span className="label">{String(r.entry ?? r.side ?? '')}</span> },
      { key: 'qty', header: 'qty', align: 'right' as const, width: 54, render: (r: Record<string, unknown>) => <Num value={String(r.peak_qty ?? r.quantity ?? '')} digits={0} /> },
      { key: 'open', header: 'entry', align: 'right' as const, width: 72, render: (r: Record<string, unknown>) => <Num value={r.avg_px_open as number} digits={2} /> },
      { key: 'close', header: 'exit', align: 'right' as const, width: 72, render: (r: Record<string, unknown>) => <Num value={r.avg_px_close as number} digits={2} /> },
      { key: 'pnl', header: 'pnl', align: 'right' as const, width: 80, render: (r: Record<string, unknown>) => money(r.realized_pnl) },
      { key: 'ret', header: 'return', align: 'right' as const, width: 68, render: (r: Record<string, unknown>) => <Num value={(r.realized_return as number) * 100} digits={2} suffix="%" signed tone /> },
    ]
  }
  if (tab === 'orders') {
    return [
      { key: 'ts', header: 'submitted', width: 118, render: (r: Record<string, unknown>) => <span className="num">{time(r.ts_init)}</span> },
      { key: 'side', header: 'side', width: 46, render: (r: Record<string, unknown>) => <span className="label">{String(r.side ?? '')}</span> },
      { key: 'type', header: 'type', width: 92, render: (r: Record<string, unknown>) => <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>{String(r.type ?? '')}</span> },
      { key: 'qty', header: 'qty', align: 'right' as const, width: 54, render: (r: Record<string, unknown>) => <Num value={String(r.quantity ?? '')} digits={0} /> },
      { key: 'filled', header: 'filled', align: 'right' as const, width: 54, render: (r: Record<string, unknown>) => <Num value={String(r.filled_qty ?? '')} digits={0} /> },
      { key: 'status', header: 'status', render: (r: Record<string, unknown>) => <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>{String(r.status ?? '')}</span> },
    ]
  }
  return [
    { key: 'ts', header: 'filled at', width: 118, render: (r: Record<string, unknown>) => <span className="num">{time(r.ts_event)}</span> },
    { key: 'side', header: 'side', width: 46, render: (r: Record<string, unknown>) => <span className="label">{String(r.order_side ?? '')}</span> },
    { key: 'qty', header: 'qty', align: 'right' as const, width: 54, render: (r: Record<string, unknown>) => <Num value={String(r.last_qty ?? '')} digits={0} /> },
    { key: 'px', header: 'price', align: 'right' as const, width: 76, render: (r: Record<string, unknown>) => <Num value={String(r.last_px ?? '')} digits={2} /> },
    { key: 'liq', header: 'liquidity', width: 74, render: (r: Record<string, unknown>) => <span className="label">{String(r.liquidity_side ?? '')}</span> },
    { key: 'comm', header: 'commission', align: 'right' as const, render: (r: Record<string, unknown>) => <span className="num" style={{ color: 'var(--ink-dim)' }}>{String(r.commission ?? '—')}</span> },
  ]
}

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

interface StoredRun {
  run_id: string
  created_at: string
  name: string
  symbol_id: string
  timeframe: string
  positions: number
  pnl_total: number | null
  pnl_pct: number | null
  win_rate: number | null
  sharpe: number | null
  prompt: string | null
}

export function BacktestHistoryPanel() {
  const { runId, select, setRun } = useWorkspace()
  const { state, reload } = useRead(
    () => get<{ runs: StoredRun[] }>('/v1/backtest/runs'), [],
  )

  const open = useCallback(async (row: StoredRun) => {
    const body = await get<RunBody>(`/v1/backtest/runs/${row.run_id}`)
    if (body.available) {
      const { available: _a, ...rest } = body
      setRun(rest as unknown as Record<string, unknown>)
      select({ runId: row.run_id, symbolId: row.symbol_id, timeframe: row.timeframe })
    }
  }, [select, setRun])

  if (state.status === 'loading') return <Loading rows={3} label="history" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  if (!state.data.runs.length) {
    return <Empty hint="Every run is kept, so a strategy can be compared to itself later.">no runs yet</Empty>
  }

  return (
    <PanelBody pad={0}>
      <Table
        rows={state.data.runs}
        keyOf={(row) => row.run_id}
        selectedKey={runId}
        onSelect={open}
        columns={[
          {
            key: 'when', header: 'when', width: 96,
            render: (row) => <span className="num">{row.created_at.slice(5, 16).replace('T', ' ')}</span>,
          },
          {
            key: 'name', header: 'strategy',
            render: (row) => (
              <span style={{ color: 'var(--ink)' }}>
                {row.name}
                <span className="label"> {row.symbol_id.split(':').pop()}</span>
              </span>
            ),
          },
          {
            key: 'n', header: 'trades', align: 'right', width: 52,
            render: (row) => <Num value={row.positions} digits={0} />,
          },
          {
            key: 'pnl', header: 'pnl %', align: 'right', width: 64,
            render: (row) => <Num value={row.pnl_pct} digits={2} signed tone />,
          },
          {
            key: 'sharpe', header: 'sharpe', align: 'right', width: 60,
            render: (row) => <Num value={row.sharpe} digits={2} />,
          },
        ]}
      />
    </PanelBody>
  )
}
