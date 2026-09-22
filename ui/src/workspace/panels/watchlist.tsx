// Spec: Genesis Markdown/70-Schemas/Watchlist Store.md · 60-UI/Terminal.md
//
// The trader's own symbol lists. Distinct from `SR`/Series next door: that one
// is the inventory of bar series Genesis has *ingested*, and refuses a symbol
// it holds no data for. This one is scaffolding — any ticker, in sections the
// trader arranges, red or green on the day.
//
// So the numbers here are **tier 3** (`Market Data Sources`): a public feed
// with no provenance line and no reconciliation. The panel says so on its face,
// because a person reading a percentage is not reading this comment.
//
// **Settled closes, not a live price.** No realtime feed is wired to Genesis,
// so a row shows the last *completed* daily close against the one before it,
// and the footer names the session. That is the same stance `CH` takes ("closed
// bars only — the right edge is the last bar on disk"), and the reason is the
// same: a delayed last-trade that drifts intraday would disagree with every
// chart on the surface while looking authoritative.
//
// Two third parties here, deliberately not conflated: the closes are Yahoo's,
// the chart a row opens is TradingView's.
//
// Picking a row sets `tvSymbol` on the workspace, which every open TradingView
// panel follows. That is an unnamed, page-wide **link group** — the mechanism
// [[Terminal]] §Symbol linking specifies, minus the naming and the `🔗` chip
// (see [[UI-0 Build Order]] step 4, and `ponytail:` on `pick` below).
//
// It never touches `CH`, which would just show an empty chart for a symbol
// Genesis has no bars for.

import { useEffect, useMemo, useState } from 'react'
import { api, TransportError, type WatchlistBody, type QuoteRow } from '@/api/client'
import { useRead } from '@/api/useRead'
import { useGenesis } from '@/store/useGenesis'
import { Absent, Empty, Loading } from '@/components/States'
import { Chip, Num } from '@/components/Primitives'
import { revealPanel } from '@/workspace/dock'
import { symbolLink, useWorkspace } from '@/workspace/context'
import { stagger } from '@/lib/motion'

/** Members, bucketed by section, unsectioned first. */
function bySection(list: WatchlistBody): [string, WatchlistBody['members']][] {
  const groups = new Map<string, WatchlistBody['members']>()
  for (const m of list.members) {
    const key = m.group || ''
    const bucket = groups.get(key) ?? []
    bucket.push(m)
    groups.set(key, bucket)
  }
  return [...groups.entries()].sort(([a], [b]) => (a === '' ? -1 : b === '' ? 1 : a.localeCompare(b)))
}

export function WatchlistManagerPanel() {
  const { tvSymbol, select } = useWorkspace()
  const { state, reload } = useRead(() => api.watchlists(), [])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [renaming, setRenaming] = useState(false)
  const [draftSymbol, setDraftSymbol] = useState('')
  const [draftGroup, setDraftGroup] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const lists = useMemo(
    () => (state.status === 'ready' ? state.data.watchlists : []),
    [state],
  )
  const active = lists.find((l) => l.id === activeId) ?? lists[0] ?? null

  // A list saved from chat or voice pings the bus; re-read on it.
  useEffect(() => useGenesis.subscribe((s, prev) => {
    const e = s.events[0] as { event: string } | undefined
    if (e && e !== prev.events[0] && e.event === 'watchlist.updated') reload()
  }), [reload])

  // Land on the first list once there is one; never override a choice.
  useEffect(() => {
    if (activeId === null && lists.length > 0) setActiveId(lists[0].id)
  }, [activeId, lists])

  const symbols = useMemo(() => active?.members.map((m) => m.symbol) ?? [], [active])
  const quotes = useRead(() => api.quotes(symbols), [symbols.join(',')])
  const quoteFor = (sym: string): QuoteRow | undefined =>
    quotes.state.status === 'ready' ? quotes.state.data.quotes[sym] : undefined

  /**
   * The session these closes belong to.
   *
   * The latest across the rows rather than the first: a halted or delisted name
   * carries an older close, and letting it name the footer would date the whole
   * list to a day none of the live rows came from.
   */
  const asOf = useMemo(() => {
    if (quotes.state.status !== 'ready') return null
    const dates = Object.values(quotes.state.data.quotes)
      .map((q) => (q && !('error' in q) ? q.as_of : null))
      .filter((d): d is string => Boolean(d))
    return dates.length ? dates.reduce((a, b) => (a > b ? a : b)) : null
  }, [quotes.state])

  /**
   * Run one edit. Returns whether it took — the caller needs to know, because
   * "the ticker was refused" and "the ticker was added" must not both clear the
   * box you have to correct.
   */
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

  function pick(sym: string) {
    // Two separate acts, and only the first one is the link.
    //
    // Setting `tvSymbol` is what drives the chart, and it reaches *every* open
    // TradingView panel through the workspace context — an unnamed, page-wide
    // link group, which is the mechanism [[Terminal]] §Symbol linking describes
    // minus the naming and the chip.
    //
    // `revealPanel` only makes sure a chart is on screen to receive it. It
    // reuses whichever TradingView panel is already open, however it was
    // opened; it does not own one.
    //
    // ponytail: one unnamed page-wide link group — every watchlist drives every
    // TradingView panel on the page. Fine for one of each, wrong the moment you
    // want two watchlists driving two charts independently. Upgrade path is
    // named groups (`A`/`B`/`C` + the 🔗 chip) per [[UI-0 Build Order]] step 4,
    // which is a real feature with a spec, not a tweak to this line.
    select(symbolLink(sym))
    revealPanel('tradingview', { title: 'TradingView' })
  }

  if (state.status === 'loading') return <Loading rows={4} label="watchlists" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  return (
    <div className="flex flex-col h-full min-h-0" data-focus-scope="true">
      {/* list switcher */}
      <div className="flex items-center gap-1 hairline-b" style={{ padding: '4px 6px', flexShrink: 0, flexWrap: 'wrap' }}>
        {lists.map((l) => (
          <button
            key={l.id}
            className="btn-ghost"
            data-selected={l.id === active?.id}
            style={{ color: l.id === active?.id ? 'var(--ink)' : undefined }}
            onClick={() => { setActiveId(l.id); setRenaming(false); setErr(null) }}
          >
            {l.name}
          </button>
        ))}
        <button
          className="btn-ghost"
          title="new list"
          disabled={busy}
          onClick={() => act(async () => {
            const r = await api.watchlistNew('New list')
            const fresh = r.watchlists.find((l) => !lists.some((o) => o.id === l.id))
            if (fresh) setActiveId(fresh.id)
          })}
        >
          +
        </button>
      </div>

      {!active ? (
        <Empty hint="A watchlist is yours — any symbols you like, grouped into sections, with the day's close beside each. Make one with +, then add symbols below.">
          no lists yet
        </Empty>
      ) : (
        <>
          {/* active list header — rename / delete */}
          <div className="flex items-center gap-2 hairline-b" style={{ padding: '3px 8px', flexShrink: 0 }}>
            {renaming ? (
              <input
                className="field"
                autoFocus
                defaultValue={active.name}
                style={{ flex: 1 }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') act(() => api.watchlistRename(active.id, (e.target as HTMLInputElement).value)).then(() => setRenaming(false))
                  if (e.key === 'Escape') setRenaming(false)
                }}
                onBlur={() => setRenaming(false)}
              />
            ) : (
              <button className="btn-ghost" style={{ flex: 1, textAlign: 'left' }} onClick={() => setRenaming(true)} title="rename">
                {active.name}
              </button>
            )}
            <span className="label" style={{ color: 'var(--ink-ghost)' }}>{active.members.length}</span>
            <button
              className="btn-ghost"
              title="delete this list"
              disabled={busy}
              onClick={() => act(async () => {
                await api.watchlistDelete(active.id)
                setActiveId(null)
              })}
            >
              ×
            </button>
          </div>

          {/* add a symbol */}
          <form
            className="flex items-center gap-1 hairline-b"
            style={{ padding: '4px 8px', flexShrink: 0 }}
            onSubmit={(e) => {
              e.preventDefault()
              const sym = draftSymbol.trim()
              if (!sym) return
              // Cleared only on success. A refused ticker is a typo to fix,
              // and blanking the field would make the operator retype it.
              act(() => api.watchlistAdd(active.id, sym, draftGroup.trim()))
                .then((ok) => { if (ok) setDraftSymbol('') })
            }}
          >
            <input
              className="field"
              placeholder="add symbol"
              spellCheck={false}
              value={draftSymbol}
              onChange={(e) => setDraftSymbol(e.target.value)}
              style={{ flex: 1, minWidth: 70 }}
            />
            <input
              className="field"
              placeholder="section"
              spellCheck={false}
              value={draftGroup}
              onChange={(e) => setDraftGroup(e.target.value)}
              style={{ width: 84 }}
            />
            {/* Not decoration, and not optional. A form with two fields that
                block implicit submission and *no* submit button has no implicit
                submission at all — pressing Enter in the symbol box did
                nothing. The button is what makes Enter work, and it is the
                visible affordance besides. */}
            <button
              type="submit"
              className="btn-ghost"
              disabled={busy || !draftSymbol.trim()}
              title="add to this list"
            >
              add
            </button>
          </form>
          {err && (
            <div className="label" style={{ padding: '3px 8px', color: 'var(--verdict-blocked)', textTransform: 'none', letterSpacing: 0 }}>
              {err}
            </div>
          )}

          {/* rows */}
          <div className="flex flex-col min-h-0" style={{ overflowY: 'auto', flex: 1 }}>
            {active.members.length === 0 ? (
              <Empty hint="Type a ticker and press Enter. It is validated but not looked up — a symbol Yahoo has no daily bars for shows “no quote”, nothing breaks.">
                empty list
              </Empty>
            ) : (
              bySection(active).map(([section, members]) => (
                <div key={section || '_'}>
                  {section && (
                    <div className="label" style={{ padding: '4px 8px 2px', color: 'var(--ink-ghost)', letterSpacing: '0.1em' }}>
                      {section}
                    </div>
                  )}
                  {members.map((m, i) => {
                    const q = quoteFor(m.symbol)
                    const selected = tvSymbol === m.symbol
                    return (
                      <div
                        key={m.symbol}
                        className="row-hit lift flex items-baseline gap-2"
                        data-selected={selected}
                        style={{ ['--i' as string]: stagger(i), padding: '4px 8px', borderBottom: '1px solid var(--bg-raised)' }}
                      >
                        <button
                          onClick={() => pick(m.symbol)}
                          style={{ flex: 1, textAlign: 'left', display: 'flex', alignItems: 'baseline', gap: 8 }}
                        >
                          <span style={{ fontSize: 'var(--fs-sm)', fontWeight: 600, letterSpacing: '0.02em' }}>{m.symbol}</span>
                          <span style={{ flex: 1 }} />
                          {q && !('error' in q) ? (
                            <>
                              <span className="num" style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)' }}>
                                {q.close}
                              </span>
                              <Num value={q.change_pct} digits={2} suffix="%" signed tone />
                            </>
                          ) : (
                            <span className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}>
                              {q && 'error' in q ? 'no quote' : '·'}
                            </span>
                          )}
                        </button>
                        <button
                          className="btn-ghost"
                          title="remove"
                          disabled={busy}
                          onClick={() => act(() => api.watchlistRemove(active.id, m.symbol))}
                          style={{ fontSize: 'var(--fs-tiny)' }}
                        >
                          ×
                        </button>
                      </div>
                    )
                  })}
                </div>
              ))
            )}
          </div>

          {/* The tier line — said plainly, not implied.
              Two different third parties, and conflating them would be the
              kind of small lie that costs trust: the numbers in these rows are
              Yahoo's daily closes, the chart they open is TradingView's. */}
          <div className="hairline-t flex items-center gap-2" style={{ padding: '3px 8px', flexShrink: 0 }}>
            <Chip tone="warn" title="Market Data Sources — a public third-party feed. Research and closed-market work only; never a source for sizing, stops or any number Genesis reports as its own.">
              tier 3 · Yahoo closes
            </Chip>
            <span
              className="label"
              style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}
            >
              {asOf ? `close of ${asOf}` : 'settled closes — not a live price'}
            </span>
            <span style={{ flex: 1 }} />
            <button className="btn-ghost" onClick={quotes.reload} title="re-read the closes" style={{ fontSize: 'var(--fs-tiny)' }}>
              refresh
            </button>
          </div>
        </>
      )}
    </div>
  )
}
