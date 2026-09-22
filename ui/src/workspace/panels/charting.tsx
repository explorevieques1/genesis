// Spec: Genesis Markdown/10-Architecture/Charting Engine.md · 10-Architecture/Market Data Sources.md
//
// The charting panels. Every one of them reads the bar store — the chart never
// draws a symbol Genesis does not hold data for.
//
// That constraint used to mean there was no "add symbol" box: a box that let
// you type `TSLA` and then showed an empty chart taught nothing. The symbol bar
// (`components/charts/SymbolBar.tsx`) keeps the constraint and removes the dead
// end: picking a symbol the store does not hold makes `CH` *load* it — the same
// fetch `genesis chart TSLA` runs — and then draws what landed, with its source
// and tier. A symbol no feed will serve says so, with the reason.
//
// `WL` (`panels/watchlist.tsx`, [[Watchlist Store]]) is still the place for
// symbols you only want to glance at; it charts into `TV`, not here.

import { useMemo, useEffect, useRef, useState } from 'react'
import { api, get, TransportError, type BarRow, type JournalMark, type LiveSeries, type SearchResult, type SymbolRow } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { Caveats, Chip, Metric, Num, PanelBody, Section, Table } from '@/components/Primitives'
import { PriceChart, type PriceLine } from '@/components/charts/PriceChart'
import { useExecState } from '@/api/useExecState'
import {
  TOOLS, loadSettings, saveSettings,
  type ChartSettings, type Drawing, type NewDrawing, type ToolId,
} from '@/components/charts/drawings'
import { ChartToolbar, ChartSettingsMenu } from '@/components/charts/ChartControls'
import { SymbolBar } from '@/components/charts/SymbolBar'
import { useDefaultSymbol, useWorkspace } from '@/workspace/context'
import { useGenesis } from '@/store/useGenesis'
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

  // Re-read when the IBKR feed changes state, or a closed bar lands for a
  // series this list has not seen yet -- that is how a fresh live feed appears.
  const known = state.status === 'ready' ? state.data.symbols : EMPTY
  useEffect(() => useGenesis.subscribe((s, prev) => {
    const e = s.events[0] as { event: string; data: Record<string, unknown> } | undefined
    if (!e || e === prev.events[0]) return
    if (e.event === 'broker.connection') reload()
    if (e.event === 'market.bar' && e.data.closed
      && !known.some((r) => r.symbol_id === e.data.symbol_id && r.timeframe === e.data.timeframe)) reload()
  }), [known, reload])

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
              {row.live && <LiveBadge state={row.live} />}
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
// Live data — the IBKR contracts, and nothing else
// ---------------------------------------------------------------------------

/** `feed.live` is one entry per (symbol, timeframe); the panel lists symbols. */
export function groupBySymbol(live: LiveSeries[]): [string, string[]][] {
  const out = new Map<string, string[]>()
  for (const l of live) out.set(l.symbol_id, [...(out.get(l.symbol_id) ?? []), l.timeframe])
  return [...out]
}

/**
 * `LD`. The contracts the IBKR session is configured to stream, from
 * `feed.live` in the broker settings — the same list `CON` edits. Separate
 * from `SR` on purpose: Series is the whole bar store, this is the feed. A
 * contract appears here the moment it is configured, before its first bar, and
 * clicking it drives `CH` exactly the way a Series row does.
 */
export function LiveDataPanel() {
  const { symbolId, timeframe, select } = useWorkspace()
  const settings = useRead(() => api.brokerSettings(), [])
  const symbols = useRead(() => api.symbols(), [])
  const { reload: reloadSettings } = settings
  const { reload: reloadSymbols } = symbols

  // Connection changes flip the badge; closed bars move the counts.
  useEffect(() => useGenesis.subscribe((s, prev) => {
    const e = s.events[0] as { event: string; data: Record<string, unknown> } | undefined
    if (!e || e === prev.events[0]) return
    if (e.event === 'broker.connection') { reloadSettings(); reloadSymbols() }
    if (e.event === 'market.bar' && e.data.closed) reloadSymbols()
  }), [reloadSettings, reloadSymbols])

  // -- search IBKR's contract directory ------------------------------------
  //
  // The same `/v1/market/search` the chart's symbol bar uses. `CL` returns the
  // root plus its next dated months (CLX6, CLZ6…) — the month is picked by the
  // operator, never guessed.
  const [query, setQuery] = useState('')
  const [found, setFound] = useState<{ results: SearchResult[]; reason?: string } | null>(null)
  const [searching, setSearching] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    const q = query.trim()
    if (!q) { setFound(null); return }
    let cancelled = false
    // IBKR paces lookups at ~1/s; wait for the typing to stop.
    const timer = setTimeout(() => {
      setSearching(true)
      api.symbolSearch(q)
        .then((b) => { if (!cancelled) setFound(b.available ? { results: b.results } : { results: [], reason: b.reason }) })
        .catch((e) => { if (!cancelled) setFound({ results: [], reason: e instanceof TransportError ? e.message : String(e) }) })
        .finally(() => { if (!cancelled) setSearching(false) })
    }, 300)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [query])

  // -- the stream follows the chart ---------------------------------------
  //
  // A contract saved here has no timeframe of its own; the chart owns that. When
  // the chart is on a saved symbol at a timeframe IBKR is not streaming for it,
  // re-point that symbol's stream to the chart's timeframe. Debounced, because
  // each save reconnects the session and backfills — clicking 1m → 5m → 15m
  // should cost one reconnect, not three.
  const feedNow = settings.state.status === 'ready' ? settings.state.data.feed : null
  useEffect(() => {
    if (!feedNow?.enabled || !symbolId) return
    const mine = feedNow.live.filter((l) => l.symbol_id === symbolId)
    if (!mine.length || (mine.length === 1 && mine[0].timeframe === timeframe)) return
    const timer = setTimeout(() => {
      const live = [...feedNow.live.filter((l) => l.symbol_id !== symbolId), { symbol_id: symbolId, timeframe }]
      api.brokerFeed({ ...feedNow, live })
        .then(() => reloadSettings())
        .catch((e) => setErr(e instanceof TransportError ? e.message : String(e)))
    }, 800)
    return () => clearTimeout(timer)
  }, [feedNow, symbolId, timeframe, reloadSettings])

  if (settings.state.status === 'loading') return <Loading rows={3} label="live data" />
  if (settings.state.status !== 'ready') return <Absent reason={settings.state.reason} onRetry={reloadSettings} />

  const { feed } = settings.state.data
  if (!feed.enabled) {
    return (
      <Empty hint="Turn the IBKR feed on in CON — Connections — then search contracts here.">
        IBKR feed is off
      </Empty>
    )
  }

  /** Write `feed.live` through the one door the session reads — the same route `CON` saves. */
  async function saveLive(live: LiveSeries[]) {
    setBusy(true)
    setErr(null)
    try {
      await api.brokerFeed({ ...feed, live })
      reloadSettings()
    } catch (e) {
      setErr(e instanceof TransportError ? e.message : String(e))
      throw e
    } finally {
      setBusy(false)
    }
  }

  const saved = (sid: string) => feed.live.some((l) => l.symbol_id === sid)

  /** Save once. Streams at whatever the chart shows; the effect above keeps it there. */
  async function save(hit: SearchResult) {
    if (!saved(hit.symbol_id)) await saveLive([...feed.live, { symbol_id: hit.symbol_id, timeframe }])
  }

  async function add(hit: SearchResult) {
    try { await save(hit) } catch { return }
    setQuery('')
    // Onto the chart now, at the chart's timeframe; `CH` loads the backfill.
    select({ symbolId: hit.symbol_id })
  }

  const held = symbols.state.status === 'ready' ? symbols.state.data.symbols : []
  const note = { textTransform: 'none', letterSpacing: 0, color: 'var(--ink-ghost)' } as const
  return (
    <div className="flex flex-col h-full min-h-0" data-focus-scope="true">
      <div className="label flex items-center gap-2" style={{ padding: '5px 8px', color: 'var(--ink-ghost)' }}>
        <span>IBKR · port {feed.port}</span>
        <span style={{ flex: 1 }} />
        {/* Delayed is ~15 minutes behind. Said on the panel, not buried in settings. */}
        <Chip tone={feed.market_data_type === 'realtime' ? 'good' : 'warn'}>{feed.market_data_type}</Chip>
      </div>

      <form
        className="flex items-center gap-1 hairline-b"
        style={{ padding: '4px 8px' }}
        // No enter-adds-first: `CL` is Colgate stock *and* crude futures. Ambiguity is
        // shown and the operator clicks — Operating Model rule 4.
        onSubmit={(e) => e.preventDefault()}
      >
        <input
          className="field" spellCheck={false} placeholder="search IBKR — CL, GC, ES, AAPL"
          value={query} onChange={(e) => setQuery(e.target.value)} style={{ flex: 1, minWidth: 80 }}
        />
      </form>

      <div className="scroll-y" style={{ flex: 1, minHeight: 0 }}>
        {query.trim() && (
          <div className="hairline-b">
            {found?.results.map((hit) => (
              <div key={hit.symbol_id} className="flex items-center">
                <button
                  className="row-hit flex items-baseline gap-2"
                  disabled={busy}
                  style={{ flex: 1, minWidth: 0, padding: '4px 8px', textAlign: 'left' }}
                  title={`save ${hit.symbol_id} and chart it at ${timeframe}`}
                  onClick={() => void add(hit)}
                >
                  <span style={{ fontWeight: 600, minWidth: 56 }}>{hit.symbol}</span>
                  <span className="label" style={{ ...note, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {[hit.sec_type, hit.exchange, hit.description].filter(Boolean).join(' · ')}
                  </span>
                </button>
                <button
                  className="btn-ghost"
                  disabled={busy || saved(hit.symbol_id)}
                  aria-label={saved(hit.symbol_id) ? `${hit.symbol_id} is saved` : `save ${hit.symbol_id}`}
                  title={saved(hit.symbol_id) ? 'already in Live data' : 'save to Live data without leaving the chart'}
                  onClick={() => void save(hit).catch(() => {})}
                  style={{ padding: '2px 8px' }}
                >
                  {saved(hit.symbol_id) ? '✓' : '+'}
                </button>
              </div>
            ))}
            <div className="label" style={{ ...note, padding: '4px 8px' }}>
              {searching ? 'searching IBKR…'
                : found?.reason ? `IBKR: ${found.reason}`
                : found && !found.results.length ? 'no IBKR matches with a Genesis symbol id'
                : '+ saves it · click a contract to save and chart it'}
            </div>
          </div>
        )}
        {err && <div className="label" style={{ ...note, color: 'var(--verdict-blocked)', padding: '4px 8px' }}>{err}</div>}

        {!feed.live.length && !query.trim() && (
          <div className="label" style={{ ...note, padding: '8px' }}>no contracts streamed — search above to add one</div>
        )}
        {/* One row per saved contract, like a watchlist. No timeframe here:
            clicking keeps the chart's, and the stream follows it (see above). */}
        {groupBySymbol(feed.live).map(([sid], index) => {
          const rows = held.filter((r) => r.symbol_id === sid)
          const selected = symbolId === sid
          const shown = selected ? rows.find((r) => r.timeframe === timeframe) : rows[0]
          const streaming = rows.some((r) => r.live === 'streaming')
          return (
            <div key={sid} className="flex items-center" style={{ borderBottom: '1px solid var(--bg-raised)' }}>
              <button
                className="row-hit lift flex flex-col gap-0.5"
                data-selected={selected}
                style={{ ['--i' as string]: stagger(index), padding: '5px 8px', textAlign: 'left', flex: 1, minWidth: 0 }}
                onClick={() => select({ symbolId: sid })}
              >
                <div className="flex items-baseline gap-2">
                  <span style={{ fontSize: 'var(--fs-sm)', fontWeight: 600, letterSpacing: '0.02em' }}>
                    {rows[0]?.symbol ?? sid}
                  </span>
                  <span style={{ flex: 1 }} />
                  <LiveBadge state={streaming ? 'streaming' : 'configured'} />
                </div>
                <div className="flex items-baseline gap-2 label" style={{ color: 'var(--ink-ghost)' }}>
                  {shown
                    ? <><span className="num">{shown.timeframe} · {shown.bars.toLocaleString()} bars</span><span>·</span><span>{ago(shown.last_bar_at)}</span></>
                    : <span>no bars yet — backfilling</span>}
                </div>
              </button>
              <button
                className="btn-ghost" disabled={busy} title="stop streaming this symbol — bars already stored are kept"
                onClick={() => void saveLive(feed.live.filter((l) => l.symbol_id !== sid)).catch(() => {})}
                style={{ padding: '2px 8px' }}
              >
                ✕
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// The chart
// ---------------------------------------------------------------------------

export function ChartPanel() {
  return (
    <div className="flex flex-col h-full min-h-0">
      <SymbolBar />
      <div style={{ flex: 1, minHeight: 0 }}><ChartBody /></div>
    </div>
  )
}

function ChartBody() {
  const { symbolId, timeframe } = useWorkspace()
  const orderLines = useOrderLines(symbolId)
  const [hover, setHover] = useState<BarRow | null>(null)

  // -- the drawing surface ----------------------------------------------
  //
  // `series` keys everything: the drawings you made on NVDA daily are not the
  // ones on NVDA 5-minute, because a level that matters on one is noise on the
  // other. It is the same string the store indexes on.
  const series = symbolId ? `${symbolId}|${timeframe}` : ''
  const [tool, setTool] = useState<ToolId>('none')
  const [selected, setSelected] = useState<string | null>(null)
  const [settings, setSettings] = useState<ChartSettings>(loadSettings)
  const [gearOpen, setGearOpen] = useState(false)
  const [drawErr, setDrawErr] = useState<string | null>(null)
  const [drawings, setDrawings] = useState<Drawing[]>([])
  // Open only while the trader is writing the note for a marked range.
  const [marking, setMarking] = useState(false)

  const { state, reload } = useRead(
    () => api.bars(symbolId ?? '', timeframe, 1000),
    [symbolId, timeframe],
  )

  // Drawings are fetched per series and held here rather than through
  // `useRead`, because every write answers with the new list -- re-fetching
  // after a save would be a second round trip for an answer already in hand.
  const held = useRef(series)
  useEffect(() => {
    held.current = series
    setSelected(null)
    setDrawings([])
    if (!series) return
    let cancelled = false
    api.drawings(series)
      // `available: false` is a real answer here: no drawings have ever been
      // saved on this machine, so the store does not exist yet. An empty
      // chart, not an error.
      .then((body) => {
        if (!cancelled) setDrawings(body.available ? body.drawings : [])
      })
      .catch((e) => {
        // A chart that cannot reach the drawing store still draws price.
        if (!cancelled) setDrawErr(e instanceof TransportError ? e.message : String(e))
      })
    return () => { cancelled = true }
  }, [series])

  useEffect(() => { saveSettings(settings) }, [settings])
  useEffect(() => { setMarking(false) }, [series, selected])

  // A mark is made of two time anchors, so only a zone can carry one. Every
  // other drawing kind is a price or a single point.
  const held_zone = drawings.find((d) => d.id === selected && d.kind === 'zone')

  // -- the live edge ----------------------------------------------------
  //
  // `market.bar` from the IBKR session in `genesis serve`. Closed bars are
  // already in the store by the time this arrives; the forming bar exists only
  // here, and only until the next reload.
  const [live, setLive] = useState<BarRow | null>(null)
  useEffect(() => {
    setLive(null)
    return useGenesis.subscribe((s, prev) => {
      const e = s.events[0] as { event: string; data: unknown } | undefined
      if (!e || e === prev.events[0] || e.event !== 'market.bar') return
      const d = e.data as { symbol_id: string; timeframe: string; bar: BarRow }
      if (d.symbol_id === symbolId && d.timeframe === timeframe) setLive(d.bar)
    })
  }, [symbolId, timeframe])

  // -- loading what the store does not hold --------------------------------
  //
  // Every switch asks the store first, so a held series draws at once. The
  // load runs beside it: it fills a series never fetched, and tops up one whose
  // tail is behind. The chart re-reads only when the load brought a newer bar,
  // so a series that was already current does not flicker.
  const [loading, setLoading] = useState<{ series: string; reason?: string } | null>(null)
  // Only this series' read counts: comparing against the previous series' last
  // bar would skip the re-read for any series whose tail is older.
  const readLast = state.status === 'ready' && state.data.symbol_id === symbolId
    && state.data.timeframe === timeframe ? state.data.last_bar_at : null
  const lastRef = useRef(readLast)
  lastRef.current = readLast
  useEffect(() => {
    if (!symbolId || symbolId.startsWith('CR:')) return
    const mine = `${symbolId}|${timeframe}`
    let cancelled = false
    setLoading({ series: mine })
    api.load(symbolId, timeframe)
      .then((body) => {
        if (cancelled) return
        setLoading(null)
        const before = lastRef.current ? new Date(lastRef.current).getTime() : 0
        if (body.last_bar_at && new Date(body.last_bar_at).getTime() > before) reload()
      })
      .catch((e) => {
        if (!cancelled) setLoading({ series: mine, reason: e instanceof TransportError ? e.message : String(e) })
      })
    return () => { cancelled = true }
    // `reload` is a fresh closure each render; the series is the contract.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbolId, timeframe])
  const pending = loading?.series === series && !loading.reason
  const loadErr = loading?.series === series ? loading.reason : undefined

  async function act(fn: () => Promise<{ drawings: Drawing[]; id?: string }>) {
    setDrawErr(null)
    try {
      const body = await fn()
      // Guard against a stale answer landing after the chart moved on.
      if (held.current !== series) return
      setDrawings(body.drawings)
      // A new drawing arrives selected, so its handles are already there to
      // adjust -- which is what you want the second after you drew it.
      if (body.id) setSelected(body.id)
    } catch (e) {
      setDrawErr(e instanceof TransportError ? e.message : String(e))
    }
  }

  if (!symbolId) {
    return <Empty hint="Search a symbol above — held series and every IBKR instrument with a Genesis id.">pick a series</Empty>
  }
  if (state.status === 'loading') return <Loading rows={5} label={symbolId} />
  const empty = state.status !== 'ready' || !state.data.bars.length
  if (empty && pending) return <Loading rows={5} label={`fetching ${symbolId} ${timeframe}`} />
  if (empty && loadErr) return <Absent reason={loadErr} onRetry={reload} />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  const { bars, symbol, count, last_bar_at } = state.data
  if (!bars.length) return <Empty>no bars in this window</Empty>

  const tier = Math.max(...bars.map((b) => b.tier))
  // DuckDB returns the column's full scale, so AAPL's close arrives as
  // "319.97000122". Printing that implies eight decimals of a price quoted in
  // cents. Inferred from the data rather than hardcoded to 2, because a future
  // and an FX pair are both real and both wrong at 2.
  const places = pricePrecision(bars.map((b) => b.close))
  const last = bars[bars.length - 1]
  const edge = live && live.time >= last.time ? live : null
  const shown = hover ?? edge ?? last
  const previous = hover
    ? bars[bars.indexOf(hover) - 1]
    : edge && edge.time > last.time ? last : bars[bars.length - 2]
  const change =
    previous ? Number(shown.close) - Number(previous.close) : null
  const changePct =
    previous && Number(previous.close) !== 0
      ? (Number(shown.close) / Number(previous.close) - 1) * 100
      : null

  return (
    <div className="flex flex-col h-full min-h-0" style={{ position: 'relative' }}>
      {marking && held_zone && held_zone.kind === 'zone' && (
        <MarkForm
          symbol={symbolId}
          timeframe={timeframe}
          series={series}
          drawingId={held_zone.id}
          start={held_zone.from_time}
          end={held_zone.to_time}
          onClose={() => setMarking(false)}
        />
      )}
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
        {/* The tools sit in the middle of the banner, between what the chart
            is and what it is made of. */}
        <ChartToolbar
          tool={tool}
          onPick={(next) => { setTool(next); setSelected(null) }}
          canDelete={selected !== null}
          onDelete={() => {
            if (!selected) return
            act(() => api.drawingDelete(series, selected))
            setSelected(null)
          }}
          count={drawings.length}
          onClear={() => act(() => api.drawingsClear(series))}
          canJournal={held_zone !== undefined}
          onJournal={() => setMarking(true)}
        />
        <span style={{ flex: 1 }} />

        {edge && <LiveBadge state="streaming" />}
        <Chip tone={tierTone(tier)} title="Market Data Sources trust tier — 1 is the venue's own book">
          tier {tier} · {shown.source}
        </Chip>
        <span className="label" style={{ color: 'var(--ink-ghost)' }}>
          {count} bars · last {ago(last_bar_at)}
        </span>
        {/* Top right, where a settings gear belongs. */}
        <button
          className="btn-ghost"
          data-active={gearOpen}
          title="chart settings"
          onClick={() => setGearOpen((open) => !open)}
          style={{ lineHeight: 1 }}
        >
          <Gear />
        </button>
      </div>

      {gearOpen && (
        <ChartSettingsMenu
          settings={settings}
          onChange={setSettings}
          onClose={() => setGearOpen(false)}
        />
      )}

      {drawErr && (
        <div className="label" style={{ padding: '2px 8px', color: 'var(--verdict-blocked)', textTransform: 'none', letterSpacing: 0 }}>
          {drawErr}
        </div>
      )}

      <div style={{ flex: 1, minHeight: 0 }}>
        <PriceChart
          priceLines={orderLines}
          bars={bars}
          tier={tier}
          onCrosshair={setHover}
          settings={settings}
          showVolume
          drawings={drawings}
          tool={tool}
          live={edge}
          selectedId={selected}
          places={places}
          onSelect={setSelected}
          onDelete={(id) => { act(() => api.drawingDelete(series, id)); setSelected(null) }}
          onCommit={(drawing: NewDrawing) => act(() => api.drawingSave(series, drawing))}
          onUpdate={(drawing: Drawing) => act(() => api.drawingSave(series, drawing))}
          onToolDone={() => setTool('none')}
        />
      </div>

      {/* Said once, plainly, rather than implied by a still chart. */}
      <div
        className="hairline-t label"
        style={{ padding: '2px 8px', flexShrink: 0, color: 'var(--ink-ghost)',
          textTransform: 'none', letterSpacing: 0 }}
      >
        {edge
          ? `live · ${edge.source} tier ${edge.tier} · right edge is the forming bar, not yet stored`
          : 'closed bars only — the right edge is the last bar on disk'}
        {pending && ' · checking for newer bars…'}
        {loadErr && <span style={{ color: 'var(--verdict-blocked)' }}>{` · could not top up: ${loadErr}`}</span>}
        {tool !== 'none' && (
          <span style={{ color: 'var(--core)' }}>
            {' · '}{TOOLS.find((t) => t.id === tool)?.hint} · Esc cancels
          </span>
        )}
      </div>
    </div>
  )
}

/**
 * A series the IBKR session streams. Green dot only while the session is live;
 * a configured feed whose gateway is down reads as `live · off`, never green.
 */
function LiveBadge({ state }: { state: 'streaming' | 'configured' }) {
  const on = state === 'streaming'
  return (
    <span
      className="label flex items-center gap-1"
      title={on ? 'streaming from IBKR — new bars land in the store as they close' : 'configured as a live feed, but the IBKR session is not connected'}
      style={{ color: on ? 'var(--verdict-pass)' : 'var(--ink-ghost)', letterSpacing: '0.08em' }}
    >
      <span style={{ width: 6, height: 6, borderRadius: 3, background: 'currentColor', display: 'inline-block' }} />
      {on ? 'live' : 'live · off'}
    </span>
  )
}

/** The gear. Inline rather than a dependency — it is eight path commands. */
function Gear() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3">
      <circle cx="8" cy="8" r="2.4" />
      <path d="M8 1.6v1.8M8 12.6v1.8M1.6 8h1.8M12.6 8h1.8M3.5 3.5l1.3 1.3M11.2 11.2l1.3 1.3M12.5 3.5l-1.3 1.3M4.8 11.2l-1.3 1.3" />
    </svg>
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


/**
 * The order path drawn on the chart: the position's average price, and every
 * working entry, stop and target on this contract. Read from the same pushed
 * state as `TRD`, so the lines and the ticket cannot disagree.
 */
function useOrderLines(symbolId: string | null): PriceLine[] {
  const { read } = useExecState()
  return useMemo(() => {
    if (read.status !== 'ready' || !symbolId) return []
    const buy = 'rgba(53, 196, 138, 0.9)'
    const sell = 'rgba(255, 77, 94, 0.9)'
    const lines: PriceLine[] = []
    for (const p of read.state.positions.filter((x) => x.symbol_id === symbolId)) {
      const upl = p.unrealized_pnl === null ? '' : ` ${Number(p.unrealized_pnl) >= 0 ? '+' : ''}${Number(p.unrealized_pnl).toFixed(0)}`
      lines.push({ id: `pos-${p.con_id}`, price: p.avg_price, color: 'rgba(61, 139, 255, 0.95)', style: 'solid',
        title: `${p.qty > 0 ? 'LONG' : 'SHORT'} ${Math.abs(p.qty)}${upl}` })
    }
    for (const o of read.state.orders.filter((x) => x.symbol_id === symbolId && x.working)) {
      const q = o.remaining
      if (o.type === 'stop' || o.type === 'trail') {
        if (o.stop !== null) lines.push({ id: o.client_order_id, price: o.stop, color: sell, style: 'dotted',
          title: o.type === 'trail' ? `TRAIL ${o.trail} ×${q}` : `STOP ×${q}` })
      } else if (o.type === 'limit' && o.limit !== null) {
        const target = o.role === 'target'
        lines.push({ id: o.client_order_id, price: o.limit, color: target ? buy : o.side === 'buy' ? buy : sell,
          style: target ? 'dotted' : 'dashed', title: target ? `TP ×${q}` : `${o.side.toUpperCase()} LMT ×${q}` })
      }
    }
    return lines
  }, [read, symbolId])
}

// ---------------------------------------------------------------------------
// journalling a marked range
// ---------------------------------------------------------------------------

/** What a mark can be. Closed on the server too; this is the same list. */
const MARK_KINDS: JournalMark['kind'][] = ['entry', 'exit', 'idea']

function stamp(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

/**
 * The note for a range of candles: an entry, an exit, or an idea.
 *
 * Attaching it to a real trade is optional and the list is only offered when
 * there are trades to offer — an empty picker on a system with no fills is a
 * question with no answer.
 */
function MarkForm(props: {
  symbol: string
  timeframe: string
  series: string
  drawingId: string
  start: number
  end: number
  onClose: () => void
}) {
  const [kind, setKind] = useState<JournalMark['kind']>('idea')
  const [note, setNote] = useState('')
  const [entryId, setEntryId] = useState('')
  const [entries, setEntries] = useState<Record<string, unknown>[]>([])
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.journalEntries(50)
      .then((body) => { if (!cancelled) setEntries(body.available ? body.entries : []) })
      // No journal yet is the ordinary state before the first fill, and it
      // must not stop someone journalling an idea.
      .catch(() => { if (!cancelled) setEntries([]) })
    return () => { cancelled = true }
  }, [])

  const mine = entries.filter((e) => String(e.symbol ?? '') === props.symbol)

  async function save() {
    setSaving(true)
    setErr(null)
    try {
      const body = await api.journalMark({
        kind, symbol: props.symbol, timeframe: props.timeframe,
        start: Math.round(props.start), end: Math.round(props.end),
        note, series: props.series, drawing_id: props.drawingId,
        entry_id: entryId,
      })
      setSaved(body.mark.id)
      setTimeout(props.onClose, 900)
    } catch (e) {
      setErr(e instanceof TransportError ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="flex flex-col gap-2"
      style={{
        position: 'absolute', zIndex: 20, top: 34, right: 8, width: 268,
        padding: 8, background: 'var(--surface)', border: '1px solid var(--hairline)',
        borderRadius: 3, boxShadow: '0 6px 24px rgba(0,0,0,0.35)',
      }}
      onKeyDown={(e) => { if (e.key === 'Escape') props.onClose() }}
    >
      <div className="flex items-baseline gap-2">
        <span style={{ fontWeight: 600 }}>journal this range</span>
        <span style={{ flex: 1 }} />
        <button className="btn-ghost" onClick={props.onClose} aria-label="close">✕</button>
      </div>
      <span className="label">
        {props.symbol} {props.timeframe} · {stamp(props.start)} → {stamp(props.end)}
      </span>

      <div className="flex items-center gap-1">
        {MARK_KINDS.map((k) => (
          <button
            key={k} className="btn-ghost" data-selected={k === kind}
            style={{ color: k === kind ? 'var(--ink)' : undefined }}
            onClick={() => setKind(k)}
          >
            {k}
          </button>
        ))}
      </div>

      <textarea
        className="field" rows={3} autoFocus
        placeholder="what you saw, and what you did about it"
        value={note} onChange={(e) => setNote(e.target.value)}
      />

      {mine.length > 0 && (
        <select className="field" value={entryId} onChange={(e) => setEntryId(e.target.value)}>
          <option value="">not tied to a trade</option>
          {mine.map((e) => (
            <option key={String(e.id)} value={String(e.id)}>
              {String(e.direction ?? '')} {String(e.entry_ts ?? '').slice(0, 16)} · {String(e.setup ?? '')}
            </option>
          ))}
        </select>
      )}

      {err && <Caveats items={[err]} />}
      <div className="flex items-center gap-2">
        <button className="btn" disabled={saving || saved !== null} onClick={save}>
          {saved ? 'saved' : saving ? 'saving…' : 'save to journal'}
        </button>
        {saved && <span className="label">{saved}</span>}
      </div>
    </div>
  )
}
