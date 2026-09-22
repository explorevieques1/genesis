// Spec: Genesis Markdown/60-UI/Candle Ranges.md · 10-Architecture/Market Data Sources.md
//
// `CR` — capture a window of price, name it, keep it.
//
// The job is reviewing a setup you took: the forty bars around the trade, under
// a name you chose, frozen. So this panel is a form and a list, and neither of
// them is a chart — a saved range opens in `CH` through the ordinary series
// selection, because a snippet you can only look at inside the tool that made
// it is a snippet you cannot compare with anything.
//
// Distinct from `SR`/Series next door in one way that matters: `SR` is the bar
// store, canonical symbol ids and immutable history. A range is the trader's
// scrapbook, keyed by whatever ticker the vendor answers to. That is what lets
// `ES=F` in here and keeps it out of there — Yahoo's ES is a continuous
// front-month series with an undocumented roll, honest as a labelled snippet
// and corrupting as a row beside a dated contract.
//
// **Tier 3, and the panel says so.** Every range is a free public feed.

import { useState } from 'react'
import { api, TransportError, type CandleRange } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { Chip } from '@/components/Primitives'
import { revealPanel } from '@/workspace/dock'
import { useWorkspace } from '@/workspace/context'
import { stagger } from '@/lib/motion'

/** What yfinance serves. Intraday history is short and the hint says so. */
const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1H', '1D'] as const

/** `2026-09-08T13:30:00+00:00` → `08 Sep 13:30`, in the window's own zone. */
function when(iso: string, tz: string): string {
  try {
    return new Date(iso).toLocaleString('en-GB', {
      day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
      timeZone: tz,
    })
  } catch {
    return iso
  }
}

function clock(iso: string, tz: string): string {
  try {
    return new Date(iso).toLocaleTimeString('en-GB', {
      hour: '2-digit', minute: '2-digit', timeZone: tz,
    })
  } catch {
    return iso
  }
}

export function CandleRangesPanel() {
  const { symbolId, select } = useWorkspace()
  const { state, reload } = useRead(() => api.ranges(), [])

  const [name, setName] = useState('')
  const [ticker, setTicker] = useState('')
  const [timeframe, setTimeframe] = useState<string>('5m')
  const [date, setDate] = useState('')
  const [from, setFrom] = useState('09:30')
  const [to, setTo] = useState('11:05')
  const [renaming, setRenaming] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function act(fn: () => Promise<unknown>): Promise<boolean> {
    setBusy(true)
    setErr(null)
    try {
      await fn()
      reload()
      return true
    } catch (e) {
      setErr(e instanceof TransportError ? e.message : String(e))
      return false
    } finally {
      setBusy(false)
    }
  }

  function open(range: CandleRange) {
    // A range is a series as far as the rest of the surface is concerned.
    select({ symbolId: `CR:${range.id}`, timeframe: range.timeframe })
    revealPanel('chart')
  }

  const ranges = state.status === 'ready' ? state.data.ranges : []

  return (
    <div className="flex flex-col h-full min-h-0" data-focus-scope="true">
      {/* capture */}
      <form
        className="flex flex-col gap-1 hairline-b"
        style={{ padding: '6px 8px', flexShrink: 0 }}
        onSubmit={(e) => {
          e.preventDefault()
          if (!ticker.trim() || !date) return
          act(async () => {
            const r = await api.rangeNew({
              name: name.trim(),
              ticker: ticker.trim(),
              timeframe,
              start: `${date}T${from}`,
              end: `${date}T${to}`,
            })
            const fresh = r.ranges.find((x) => x.id === r.range_id)
            if (fresh) open(fresh)
          }).then((ok) => { if (ok) setName('') })
        }}
      >
        <div className="flex items-center gap-1">
          <input
            className="field" placeholder="symbol — ES=F, NVDA" spellCheck={false}
            value={ticker} onChange={(e) => setTicker(e.target.value)}
            style={{ flex: 1, minWidth: 80 }}
          />
          <select
            className="field" value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
            style={{ width: 62 }}
          >
            {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-1">
          {/* Native pickers. A date and a time are solved problems and the
              browser's own controls know the operator's locale. */}
          <input
            className="field" type="date" value={date}
            onChange={(e) => setDate(e.target.value)} style={{ flex: 1 }}
          />
          <input
            className="field" type="time" value={from}
            onChange={(e) => setFrom(e.target.value)} style={{ width: 78 }}
          />
          <input
            className="field" type="time" value={to}
            onChange={(e) => setTo(e.target.value)} style={{ width: 78 }}
          />
        </div>
        <div className="flex items-center gap-1">
          <input
            className="field" placeholder="name it — “ES opening drive”"
            value={name} onChange={(e) => setName(e.target.value)}
            style={{ flex: 1 }}
          />
          <button type="submit" className="btn-ghost" disabled={busy || !ticker.trim() || !date}>
            {busy ? 'fetching…' : 'capture'}
          </button>
        </div>
        <div className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}>
          exchange time (New York) · tier 3, Yahoo · 1m history lasts 30 days, 5m and 15m 60
        </div>
      </form>

      {err && (
        <div className="label" style={{ padding: '3px 8px', color: 'var(--verdict-blocked)', textTransform: 'none', letterSpacing: 0 }}>
          {err}
        </div>
      )}

      {/* the scrapbook */}
      {state.status === 'loading' ? (
        <Loading rows={3} label="ranges" />
      ) : state.status !== 'ready' ? (
        <Absent reason={state.reason} onRetry={reload} />
      ) : ranges.length === 0 ? (
        <Empty hint="A range is a window of price you keep — the bars around one setup, named, frozen, and chartable in CH like any other series. Fill the form above.">
          nothing captured yet
        </Empty>
      ) : (
        <div className="flex flex-col min-h-0" style={{ overflowY: 'auto', flex: 1 }}>
          {ranges.map((r, index) => (
            <div
              key={r.id}
              className="row-hit lift flex flex-col gap-0.5"
              data-selected={symbolId === `CR:${r.id}`}
              style={{
                ['--i' as string]: stagger(index),
                padding: '5px 8px',
                borderBottom: '1px solid var(--bg-raised)',
              }}
            >
              <div className="flex items-baseline gap-2">
                {renaming === r.id ? (
                  <input
                    className="field" autoFocus defaultValue={r.name} style={{ flex: 1 }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        act(() => api.rangeRename(r.id, (e.target as HTMLInputElement).value))
                          .then(() => setRenaming(null))
                      }
                      if (e.key === 'Escape') setRenaming(null)
                    }}
                    onBlur={() => setRenaming(null)}
                  />
                ) : (
                  <button
                    className="btn-ghost"
                    style={{ flex: 1, textAlign: 'left', fontSize: 'var(--fs-sm)', fontWeight: 600 }}
                    onClick={() => open(r)}
                    onDoubleClick={() => setRenaming(r.id)}
                    title="chart it — double-click to rename"
                  >
                    {r.name}
                  </button>
                )}
                <Chip tone="warn" title="Market Data Sources trust tier — 3 is a free public feed">
                  T{r.tier}
                </Chip>
                <button
                  className="btn-ghost" title="delete this range" disabled={busy}
                  onClick={() => act(() => api.rangeDelete(r.id))}
                >
                  ×
                </button>
              </div>
              <div className="flex items-baseline gap-2 label" style={{ color: 'var(--ink-ghost)' }}>
                <span>{r.ticker}</span>
                <span>·</span>
                <span>{r.timeframe}</span>
                <span>·</span>
                <span className="num">{when(r.start, r.tz)}–{clock(r.end, r.tz)}</span>
                <span>·</span>
                <span className="num">{r.bars} bars</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
