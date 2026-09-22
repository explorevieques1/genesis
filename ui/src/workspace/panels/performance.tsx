// Spec: Genesis Markdown/60-UI/Widget Catalog.md · 10-Architecture/Market Data Sources.md
//
// `PFM` — what moved, across two universes and four windows.
//
// Two axes of one board, not four panels. **View** is `barchart` or `heatmap`;
// **market** is `stocks` (the eleven sector ETFs) or `futures` (front-month
// contracts, plus the cash indices a futures board conventionally shows). Both
// toggles are typed words as well as buttons, because the command line is the
// door everything else has to fit through (`Operating Model` §1).
//
// **No chart library here, deliberately.** `HM` earns echarts because a
// squarified treemap over a 275× range of market caps is real geometry. This
// board is bars whose width is a percentage and tiles in a grid — CSS does both
// exactly, in fewer lines than configuring a library to do them, and the result
// inherits the surface's own type and spacing instead of approximating it.
//
// **Colour is `changeColour`**, shared with `HM`, clamped per window: a 1D
// column spans ±3% and a 3M column ±12%, so one clamp would paint every 3M bar
// the same green. The clamp in force is named under each column.
//
// **It refreshes on the bell, and does not poll.** Stocks re-read when the
// daemon emits `market.close` — the daemon owns the real exchange calendar, so
// holidays and half-days are handled where that knowledge already lives. Futures
// have no such event (Open Questions §1 — the calendar is XNYS-only), so they
// get one timer to the next CME daily settlement at 17:00 ET. Neither is a poll:
// one is a push, the other fires once and reschedules itself.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type PerformanceBody, type PerformanceRow } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Loading } from '@/components/States'
import { Chip } from '@/components/Primitives'
import { changeColour } from '@/lib/format'
import { useGenesis } from '@/store/useGenesis'

type View = 'barchart' | 'heatmap'
type Market = 'stocks' | 'futures'

/**
 * How wide the colour ramp runs, per window.
 *
 * Not arithmetic on the data: an auto-scale computed from the visible rows
 * would make the same −2% a different colour on a quiet day and a violent one,
 * which is the opposite of what a colour scale is for.
 */
const CLAMP: Record<string, number> = { '1D': 3, '1W': 5, '1M': 8, '3M': 12 }

/** CME daily settlement — 17:00 America/New_York, the futures board's "close". */
function msUntilSettlement(now = Date.now()): number {
  const et = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', hour12: false,
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).formatToParts(new Date(now))
  const part = (t: string) => Number(et.find((p) => p.type === t)?.value ?? 0)
  const secondsNow = part('hour') * 3600 + part('minute') * 60 + part('second')
  const target = 17 * 3600
  // Already past it today: aim at tomorrow's.
  const delta = target > secondsNow ? target - secondsNow : 86400 - secondsNow + target
  return delta * 1000
}

/** Rows in board order, grouped, each group's members keeping feed order. */
function grouped(body: PerformanceBody): [string, PerformanceRow[]][] {
  return body.groups.map((g) => [g, body.rows.filter((r) => r.group === g)])
}

function signed(value: number | null): string {
  return value === null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}`
}

// ---------------------------------------------------------------------------
// bar chart — one column per window, sorted best to worst, like the boards it
// replaces. Sorting per column rather than fixing one order is the point: the
// question is "what led over this window", and that is a different ranking per
// window.
// ---------------------------------------------------------------------------

function BarColumn({ window: label, rows }: { window: string; rows: PerformanceRow[] }) {
  const clamp = CLAMP[label] ?? 5
  const ranked = rows
    .filter((r) => r.returns[label] !== null && r.returns[label] !== undefined)
    .sort((a, b) => (b.returns[label] as number) - (a.returns[label] as number))
  // One scale for the column, from its own widest move, so bar length is
  // comparable down the column and never wider than the track.
  const widest = Math.max(...ranked.map((r) => Math.abs(r.returns[label] as number)), 0.01)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
      <div className="label" style={{ color: 'var(--ink)' }}>
        {label} PERFORMANCE
        <span style={{ color: 'var(--ink-ghost)', marginLeft: 6 }}>
          scale ±{clamp}%
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {ranked.map((row) => {
          const value = row.returns[label] as number
          return (
            <div key={row.symbol} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              {/* Not `.label`: uppercase plus 0.14em tracking cost enough
                  width that "Crude Oil WTI" and "Crude Oil Brent" both
                  truncated to "CRUDE O…" — two different contracts rendered
                  as the same row. Names are read here, not scanned. */}
              <span title={`${row.name} · ${row.symbol}`}
                style={{ width: 150, flex: '0 0 auto', textAlign: 'right',
                  fontSize: 'var(--fs-micro)', color: 'var(--ink-dim)',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {row.name}
              </span>
              {/* The track is the full column; the bar is the share of the
                  column's widest move. A right-aligned number outside the bar
                  stays readable at every length, including near-zero. */}
              <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 4 }}>
                <div style={{
                  width: `${(Math.abs(value) / widest) * 100}%`,
                  height: 13,
                  background: changeColour(value, clamp),
                  borderRadius: 2,
                  minWidth: 2,
                }} />
                <span className="label" style={{ flex: '0 0 auto', color: 'var(--ink-dim)' }}>
                  {signed(value)}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// heatmap — the quote board. Equal tiles in board order, grouped by row, so a
// name stays where you last saw it. Area carries no meaning here and must not
// pretend to: futures have no market cap, and eleven sector ETFs sized by AUM
// would say something true about fund flows and nothing about performance.
// ---------------------------------------------------------------------------

function TileBoard({ body, window: label }: { body: PerformanceBody; window: string }) {
  const clamp = CLAMP[label] ?? 5
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {grouped(body).map(([group, rows]) => (
        <div key={group} style={{ display: 'flex', gap: 6, alignItems: 'stretch' }}>
          <div className="label" style={{
            width: 74, flex: '0 0 auto', color: 'var(--ink-faint)',
            writingMode: 'horizontal-tb', paddingTop: 4,
          }}>
            {group}
          </div>
          <div style={{
            flex: 1, minWidth: 0, display: 'grid', gap: 3,
            gridTemplateColumns: 'repeat(auto-fill, minmax(124px, 1fr))',
          }}>
            {rows.map((row) => {
              const value = row.returns[label]
              return (
                <div key={row.symbol}
                  title={`${row.symbol} · ${row.name} · last ${row.last}`}
                  style={{
                    background: value === null ? 'var(--bg-raised)' : changeColour(value, clamp),
                    borderRadius: 'var(--r-sm)', padding: '5px 6px',
                    display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0,
                  }}>
                  <span style={{
                    fontSize: 'var(--fs-micro)', fontWeight: 600, color: '#fff',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {row.name}
                  </span>
                  {/* Flex, not a float: a float wraps the change onto its own
                      line whenever the price is long, so tiles in one row
                      disagreed about how many lines they had. The price gives
                      up width first — the change is why you are looking. */}
                  <span style={{
                    fontSize: 'var(--fs-micro)', color: '#fff', opacity: 0.85,
                    display: 'flex', justifyContent: 'space-between', gap: 4,
                  }}>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {row.last}
                    </span>
                    <span style={{ flex: '0 0 auto' }}>{signed(value)}%</span>
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------

function Toggle<T extends string>({ options, value, onChange }: {
  options: readonly T[]
  value: T
  onChange: (next: T) => void
}) {
  return (
    <div style={{ display: 'flex', border: '1px solid var(--hairline)', borderRadius: 'var(--r-sm)' }}>
      {options.map((option) => (
        <button key={option} type="button" className="label"
          aria-pressed={option === value}
          onClick={() => onChange(option)}
          style={{
            padding: '1px 8px', border: 'none', background: option === value ? 'var(--bg-raised)' : 'none',
            color: option === value ? 'var(--ink)' : 'var(--ink-faint)', cursor: 'pointer',
          }}>
          {option}
        </button>
      ))}
    </div>
  )
}

export function PerformancePanel({ params }: { params?: { view?: View; market?: Market } }) {
  // `params` is the dock's own door (`dock.ts` §OpenOptions), so a caller that
  // knows which board it wants can open straight onto it. The palette does not
  // pass trailing words today — typing `PFM` opens the default and both toggles
  // are one click — so this is symmetric: neither Genesis nor the operator has a
  // route the other lacks, which is the only reason it is worth keeping.
  const [view, setView] = useState<View>(params?.view === 'heatmap' ? 'heatmap' : 'barchart')
  const [market, setMarket] = useState<Market>(params?.market === 'futures' ? 'futures' : 'stocks')
  const [window_, setWindow] = useState('1D')

  const { state, reload, fetchedAt } = useRead(() => api.performance(market), [market])
  const reloadRef = useRef(reload)
  reloadRef.current = reload

  // -- the closing bell -------------------------------------------------
  // Pushed, not polled. The daemon crosses the session boundary against the
  // real exchange calendar and says so; this just listens for it.
  const lastClose = useGenesis(
    useCallback((s) => s.events.find((e) => e.event === 'market.close')?.id ?? null, []),
  )
  useEffect(() => {
    if (lastClose && market === 'stocks') reloadRef.current()
  }, [lastClose, market])

  // Futures settle at 17:00 ET and the daemon's calendar is XNYS-only, so this
  // is the one place a clock is unavoidable. It fires once and reschedules —
  // never an interval, which would be the poll the surface forbids.
  useEffect(() => {
    if (market !== 'futures') return
    let timer: number
    const arm = () => {
      timer = window.setTimeout(() => {
        reloadRef.current()
        arm()
      }, msUntilSettlement())
    }
    arm()
    return () => window.clearTimeout(timer)
  }, [market])

  const body = state.data
  const windows = useMemo(() => body?.windows ?? ['1D'], [body])
  useEffect(() => {
    if (!windows.includes(window_)) setWindow(windows[0])
  }, [windows, window_])

  return (
    <div className="flex flex-col h-full min-h-0" style={{ gap: 6, padding: 6 }}>
      <div className="flex items-center" style={{ gap: 6, flexWrap: 'wrap' }}>
        <Toggle options={['barchart', 'heatmap'] as const} value={view} onChange={setView} />
        <Toggle options={['stocks', 'futures'] as const} value={market} onChange={setMarket} />
        {view === 'heatmap' && (
          <Toggle options={windows} value={window_} onChange={setWindow} />
        )}
        <Chip tone="warn" title="Public feed. Research scaffolding — never a number the risk engine reads.">TIER 3</Chip>
        {body && (
          <Chip tone={body.settled ? 'neutral' : 'core'}
            title={body.settled
              ? 'The last bar is a finished session.'
              : 'The last bar is a session still trading — these numbers will move.'}>
            {body.settled ? `SETTLED ${body.as_of}` : `IN SESSION ${body.as_of}`}
          </Chip>
        )}
        {body?.missing.length ? (
          <span className="label" style={{ color: 'var(--ink-faint)' }}>
            {body.missing.length} unpriced: {body.missing.join(' ')}
          </span>
        ) : null}
        <button type="button" className="label" onClick={reload}
          style={{ marginLeft: 'auto', color: 'var(--ink-dim)', background: 'none',
            border: '1px solid var(--hairline)', borderRadius: 'var(--r-sm)', padding: '1px 6px' }}>
          refresh
        </button>
      </div>

      <div className="flex-1 min-h-0 scroll-y">
        {state.status === 'loading' && <Loading rows={6} label={`reading ${market}`} />}
        {(state.status === 'absent' || state.status === 'error') && (
          <Absent reason={state.reason} onRetry={reload} />
        )}
        {body && view === 'barchart' && (
          <div style={{
            display: 'grid', gap: 14,
            gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
          }}>
            {body.windows.map((label) => (
              <BarColumn key={label} window={label} rows={body.rows} />
            ))}
          </div>
        )}
        {body && view === 'heatmap' && <TileBoard body={body} window={window_} />}
      </div>

      <div className="flex items-center" style={{ gap: 8 }}>
        <span className="label" style={{ color: 'var(--ink-faint)' }}>
          {market === 'stocks'
            ? 'SPDR sector ETFs · refreshes on the daemon’s closing bell'
            : 'front-month continuous contracts · refreshes at 17:00 ET settlement'}
        </span>
        <span className="label" style={{ marginLeft: 'auto', color: 'var(--ink-ghost)' }}>
          {fetchedAt ? `read ${new Date(fetchedAt).toLocaleTimeString()}` : ''}
        </span>
      </div>
    </div>
  )
}
