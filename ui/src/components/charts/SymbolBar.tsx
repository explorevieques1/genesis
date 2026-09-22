// Spec: Genesis Markdown/10-Architecture/Charting Engine.md §Symbol search
//
// The chart's symbol bar: a search box that behaves like a palette, the
// timeframe row, and the live toggle for the series on screen.
//
// Two sources in one list, labelled. **Held** is the bar store, filtered as you
// type, so switching between series Genesis already has is instant and needs
// no gateway. **IBKR** is the broker's contract directory — every instrument
// the paper account can see that has a Genesis symbol id (stocks, dated
// futures, indices, FX, crypto). Picking an IBKR row selects it; `CH` then
// loads its bars into the store, so the chart never draws a symbol Genesis
// does not hold.
//
// No model anywhere on this path: the symbol id shown is the one IBKR's
// directory produced, and ambiguous matches are listed side by side.

import { useEffect, useMemo, useRef, useState } from 'react'
import { api, TransportError, type SearchResult, type SymbolRow } from '@/api/client'
import { useRead } from '@/api/useRead'
import { useWorkspace } from '@/workspace/context'
import { useGenesis } from '@/store/useGenesis'

/** IBKR bar sizes, in the order a trader reads them. `BAR_SIZES` server-side. */
export const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1H', '4H', '1D', '1W'] as const

type Row =
  | { kind: 'held'; symbol_id: string; symbol: string; detail: string }
  | { kind: 'ibkr'; symbol_id: string; symbol: string; detail: string }

export function SymbolBar() {
  const { symbolId, timeframe, select } = useWorkspace()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [cursor, setCursor] = useState(0)
  const [remote, setRemote] = useState<{ q: string; results: SearchResult[]; reason?: string } | null>(null)
  const [searching, setSearching] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  const held = useRead(() => api.symbols(), [open])
  const feed = useRead(() => api.brokerSettings(), [])

  // IBKR paces symbol lookups at about one a second; 300ms after the last
  // keystroke keeps a fast typist inside that.
  useEffect(() => {
    const q = query.trim()
    if (!open || !q) { setRemote(null); return }
    let cancelled = false
    const timer = setTimeout(() => {
      setSearching(true)
      api.symbolSearch(q)
        .then((body) => {
          if (cancelled) return
          setRemote(body.available
            ? { q, results: body.results }
            : { q, results: [], reason: body.reason })
        })
        .catch((e) => {
          if (!cancelled) setRemote({ q, results: [], reason: e instanceof TransportError ? e.message : String(e) })
        })
        .finally(() => { if (!cancelled) setSearching(false) })
    }, 300)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [query, open])

  const rows: Row[] = useMemo(() => {
    const q = query.trim().toUpperCase()
    const symbols: SymbolRow[] = held.state.status === 'ready' ? held.state.data.symbols : []
    const byId = new Map<string, string[]>()
    for (const s of symbols) {
      if (s.symbol_id.startsWith('CR:')) continue
      if (q && !s.symbol.toUpperCase().includes(q) && !s.symbol_id.includes(q)) continue
      byId.set(s.symbol_id, [...(byId.get(s.symbol_id) ?? []), s.timeframe])
    }
    const local: Row[] = [...byId].map(([id, tfs]) => ({
      kind: 'held', symbol_id: id, symbol: id.split(':')[2] ?? id, detail: `${id} · held ${tfs.join(' ')}`,
    }))
    const ibkr: Row[] = (remote?.results ?? [])
      .filter((r) => !byId.has(r.symbol_id))
      .map((r) => ({
        kind: 'ibkr', symbol_id: r.symbol_id, symbol: r.symbol,
        detail: [r.sec_type, r.exchange, r.currency, r.description].filter(Boolean).join(' · '),
      }))
    return [...local.slice(0, 8), ...ibkr]
  }, [query, held.state, remote])

  useEffect(() => { setCursor(0) }, [rows.length])

  function pick(row: Row) {
    select({ symbolId: row.symbol_id })
    setQuery('')
    setOpen(false)
    input.current?.blur()
  }

  // -- live: the same `feed.live` list `LD` and `CON` edit, through the same route
  //
  // Per symbol, like `LD`: a saved contract streams at the chart's timeframe
  // and `LD` re-points it when that changes. Per-timeframe entries here used to
  // be collapsed straight back by `LD` -- two writers, two IBKR reconnects.
  const [liveErr, setLiveErr] = useState<string | null>(null)
  const feedBody = feed.state.status === 'ready' ? feed.state.data.feed : null
  const streaming = !!feedBody?.live.some((l) => l.symbol_id === symbolId)
  const { reload: reloadFeed } = feed
  // Every save reconnects the session, so a connection event is how an edit
  // made in `LD` or `CON` reaches this toggle.
  useEffect(() => useGenesis.subscribe((s, prev) => {
    const e = s.events[0] as { event: string } | undefined
    if (e && e !== prev.events[0] && e.event === 'broker.connection') reloadFeed()
  }), [reloadFeed])
  async function toggleLive() {
    if (!feedBody || !symbolId) return
    setLiveErr(null)
    const live = streaming
      ? feedBody.live.filter((l) => l.symbol_id !== symbolId)
      : [...feedBody.live, { symbol_id: symbolId, timeframe }]
    try {
      await api.brokerFeed({ ...feedBody, live })
      feed.reload()
    } catch (e) {
      setLiveErr(e instanceof TransportError ? e.message : String(e))
    }
  }

  return (
    <div className="flex items-center gap-2 hairline-b" style={{ padding: '4px 8px', flexShrink: 0, position: 'relative' }}>
      <input
        ref={input}
        className="field"
        placeholder={symbolId ? `${symbolId} — search symbols` : 'search symbols — NVDA, NQ, EUR, BTC'}
        spellCheck={false}
        value={query}
        style={{ flex: 1, minWidth: 120, maxWidth: 360 }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, rows.length - 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)) }
          else if (e.key === 'Enter' && rows[cursor]) pick(rows[cursor])
          else if (e.key === 'Escape') { setOpen(false); input.current?.blur() }
        }}
      />

      <div className="flex items-center" role="group" aria-label="timeframe">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            className="btn-ghost"
            data-active={tf === timeframe}
            aria-pressed={tf === timeframe}
            onClick={() => select({ timeframe: tf })}
            style={{ padding: '2px 6px' }}
          >
            {tf}
          </button>
        ))}
      </div>

      <span style={{ flex: 1 }} />
      {feedBody && symbolId && !symbolId.startsWith('CR:') && (
        <button
          className="btn-ghost"
          data-active={streaming}
          disabled={!feedBody.enabled}
          title={!feedBody.enabled
            ? 'the IBKR feed is off — turn it on in CON'
            : streaming ? `remove ${symbolId} from Live data` : `save ${symbolId} to Live data and stream it from IBKR (${feedBody.market_data_type})`}
          onClick={toggleLive}
        >
          {streaming ? '● live' : '+ live'}
        </button>
      )}
      {liveErr && <span className="label" style={{ color: 'var(--verdict-blocked)', textTransform: 'none', letterSpacing: 0 }}>{liveErr}</span>}

      {open && (query.trim() || rows.length > 0) && (
        <div
          role="listbox"
          style={{
            position: 'absolute', top: '100%', left: 8, zIndex: 30, width: 'min(520px, calc(100% - 16px))',
            maxHeight: 360, overflowY: 'auto', background: 'var(--bg-raised)',
            border: '1px solid var(--line, var(--bg-raised))', borderRadius: 4,
            boxShadow: '0 8px 24px rgba(0,0,0,.35)',
          }}
        >
          {rows.map((row, i) => (
            <button
              key={`${row.kind}:${row.symbol_id}`}
              role="option"
              aria-selected={i === cursor}
              className="row-hit flex items-baseline gap-2"
              data-selected={i === cursor}
              onMouseDown={(e) => { e.preventDefault(); pick(row) }}
              onMouseEnter={() => setCursor(i)}
              style={{ width: '100%', padding: '5px 8px', textAlign: 'left' }}
            >
              <span style={{ fontWeight: 600, minWidth: 64 }}>{row.symbol}</span>
              <span className="label" style={{ textTransform: 'none', letterSpacing: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {row.detail}
              </span>
              <span className="label" style={{ color: row.kind === 'held' ? 'var(--verdict-pass)' : 'var(--ink-ghost)' }}>
                {row.kind === 'held' ? 'held' : 'ibkr'}
              </span>
            </button>
          ))}
          {query.trim() && (
            <div className="label" style={{ padding: '4px 8px', color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}>
              {searching ? 'searching IBKR…'
                : remote?.reason ? `IBKR: ${remote.reason}`
                : remote && !remote.results.length ? 'IBKR: no matches with a Genesis symbol id'
                : 'enter charts it · the chart loads bars it does not hold yet'}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
