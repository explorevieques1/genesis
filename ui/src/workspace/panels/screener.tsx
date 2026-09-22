// Spec: Genesis Markdown/60-UI/Screener.md
//
// `SCR` — the S&P 500 screen you are building, big enough to work in. The chat
// is where you talk about it; this is where you look at it and push it around.
//
// One screen, many doors. Chat, ⌘K, voice and this panel all run through
// `POST /v1/command`; the daemon saves whichever ran last and pings
// `screen.updated`, and this re-reads `/v1/screener`. So a refinement typed in
// Ask Genesis lands here, and a criterion removed here is what the next chat
// turn refines.
//
// Hand edits (remove a criterion, sort a column, edit the scan) are `scr …`
// commands — no model (Operating Model §1). Plain-English refinements and the
// agent's suggested choices go into the Ask Genesis conversation, so the
// dialogue stays in one thread. Every number is the daemon's.

import { useCallback, useEffect, useState } from 'react'
import { api, type ScreenerBody, type ScreenPayload } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Loading } from '@/components/States'
import { useGenesis } from '@/store/useGenesis'
import { revealPanel } from '@/workspace/dock'
import { symbolLink, useWorkspace } from '@/workspace/context'
import { askGenesis } from './ask'

const fmt = (v: string | number | null | undefined) =>
  v === null || v === undefined ? '—' : typeof v === 'number' ? (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)) : v

const TEXT_COLS = new Set(['symbol', 'name', 'sector'])

/** The matches table. Shared with the chat bubble, which shows the first few rows. */
export function ScreenTable({ screen, max, onSort }: {
  screen: ScreenPayload
  max?: number
  onSort?: (field: string) => void
}) {
  const { select } = useWorkspace()
  const cols = screen.columns ?? []
  const rows = (screen.matches ?? []).slice(0, max)
  const sort = screen.scan?.sort
  if (rows.length === 0) return null
  return (
    <table style={{ borderCollapse: 'collapse', fontSize: 'var(--fs-tiny)', width: '100%' }}>
      <thead>
        <tr style={{ position: 'sticky', top: 0, background: 'var(--bg-panel)', zIndex: 1 }}>
          {['symbol', 'name', 'sector', ...cols].map((c) => {
            const sortable = onSort && !TEXT_COLS.has(c)
            const arrow = sort?.field === c ? (sort.direction === 'asc' ? ' ↑' : ' ↓') : ''
            return (
              <th key={c} scope="col"
                style={{ textAlign: TEXT_COLS.has(c) ? 'left' : 'right', padding: '4px 8px', color: 'var(--ink-faint)', fontWeight: 500, whiteSpace: 'nowrap', borderBottom: '1px solid var(--hairline)' }}>
                {sortable
                  ? <button type="button" className="btn-ghost" style={{ padding: 0, textTransform: 'none', letterSpacing: 0 }} title={`sort by ${c}`} onClick={() => onSort(c)}>{c}{arrow}</button>
                  : <>{c}{arrow}</>}
              </th>
            )
          })}
        </tr>
      </thead>
      <tbody>
        {rows.map((m) => (
          <tr key={String(m.symbol)} className="row-hit" style={{ cursor: 'pointer' }} title="open in Company and TradingView"
            onClick={() => {
              select(symbolLink(String(m.symbol)))
              revealPanel('company-profile', { title: 'Company' })
              revealPanel('tradingview', { title: 'TradingView' })
            }}>
            <td style={{ padding: '3px 8px', color: 'var(--ink)' }}>{m.symbol}</td>
            <td className="truncate" style={{ padding: '3px 8px', maxWidth: 200, color: 'var(--ink-dim)' }}>{m.name}</td>
            <td style={{ padding: '3px 8px', color: 'var(--ink-faint)', whiteSpace: 'nowrap' }}>{m.sector ?? '—'}</td>
            {cols.map((c) => <td key={c} className="num" style={{ padding: '3px 8px', textAlign: 'right' }}>{fmt(m[c])}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function ScreenerPanel() {
  const { state, reload } = useRead(() => api.screener(), [])
  // Keep the last good body through a reload, so a chat refinement updates the
  // table in place instead of flashing a skeleton.
  const [body, setBody] = useState<ScreenerBody | null>(null)
  const [draft, setDraft] = useState('')
  const [refine, setRefine] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { if (state.status === 'ready') setBody(state.data) }, [state])
  const expression = body?.current?.expression ?? ''
  useEffect(() => setDraft(expression), [expression])

  // Any door that ran a scan pings the bus; re-read on it.
  useEffect(() => useGenesis.subscribe((s, prev) => {
    const e = s.events[0] as { event: string } | undefined
    if (e && e !== prev.events[0] && e.event === 'screen.updated') reload()
  }), [reload])

  const run = useCallback(async (text: string, label: string) => {
    setBusy(label)
    setError(null)
    try {
      const r = await api.command(text)
      if (!r.ok) setError(r.spoken)
      reload()
    } catch {
      setError('The daemon did not answer.')
    } finally {
      setBusy(null)
    }
  }, [reload])

  const screen = body?.current ?? null
  const terms = screen?.terms ?? []
  const criteriaCount = screen?.scan?.criteria.length ?? 0
  const tail = terms.slice(criteriaCount)

  const removeTerm = (i: number) =>
    // No criteria left is the whole index, not the `scr` help text.
    run(`scr ${[...terms.slice(0, i), ...terms.slice(i + 1)].join(' ') || 'sort:-market_cap_b'}`, 'removing')
  const sortBy = (field: string) => {
    const current = screen?.scan?.sort
    const flip = current?.field === field && current.direction === 'desc'
    const rest = tail.filter((t) => !t.startsWith('sort:'))
    run(`scr ${[...terms.slice(0, criteriaCount), `sort:${flip ? '' : '-'}${field}`, ...rest].join(' ')}`, 'sorting')
  }

  if (!body) {
    return state.status === 'loading' ? <Loading rows={6} label="screener" />
      : <Absent reason={state.reason ?? 'no data'} onRetry={reload} />
  }

  const snap = body.snapshot
  return (
    <div className="flex flex-col h-full min-h-0" style={{ fontSize: 'var(--fs-sm)' }}>
      {/* -- header ----------------------------------------------------------- */}
      <div className="flex items-center gap-2 hairline-b" style={{ padding: '4px 8px', flexWrap: 'wrap', flexShrink: 0 }}>
        <span style={{ color: 'var(--ink)' }}>
          {screen?.count !== undefined ? `${screen.count} of ${screen.universe} match` : 'S&P 500'}
        </span>
        {screen?.via && <span className="label" style={{ color: 'var(--ink-faint)' }}>{screen.via === 'model' ? 'interpreted' : 'typed'}</span>}
        <span style={{ flex: 1 }} />
        <span className="label" style={{ color: snap.stale ? 'var(--state-down)' : 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}
          title={snap.failed.length ? `not fetched: ${snap.failed.join(', ')}` : undefined}>
          {snap.as_of ? `${snap.rows} companies · yfinance tier 3 · ${snap.as_of}${snap.stale ? ' · stale' : ''}` : 'no snapshot yet'}
        </span>
        <button type="button" className="btn-ghost" disabled={busy !== null} onClick={() => run('scr refresh', 'refreshing data')}>
          {busy === 'refreshing data' ? 'refreshing…' : 'refresh data'}
        </button>
      </div>

      {!snap.as_of ? (
        <Absent reason="No S&P 500 snapshot yet. Refresh data builds it (about 20 seconds)." onRetry={() => run('scr refresh', 'refreshing data')} />
      ) : !screen ? (
        <div className="flex flex-col" style={{ padding: 'var(--s-5)', gap: 'var(--s-3)', maxWidth: 560, color: 'var(--ink-dim)' }}>
          <div>No screen yet. Describe what you want in Ask Genesis, or type a scan below.</div>
          <button type="button" className="row-hit" style={{ textAlign: 'left', padding: 'var(--s-2) var(--s-3)', color: 'var(--ink-faint)' }}
            onClick={() => askGenesis('find profitable tech companies growing revenue over 15%', { refinement: false })}>
            find profitable tech companies growing revenue over 15%
          </button>
        </div>
      ) : (
        <div className="flex flex-col min-h-0" style={{ flex: 1 }}>
          {/* -- what was asked, how it was read -------------------------------- */}
          <div className="flex flex-col hairline-b" style={{ padding: '6px 8px', gap: 6, flexShrink: 0 }}>
            {screen.asked && (
              <div style={{ color: 'var(--ink-faint)', fontSize: 'var(--fs-tiny)' }}>
                asked: <span style={{ color: 'var(--ink-dim)' }}>{screen.asked}</span>
              </div>
            )}
            {screen.understood && <div style={{ color: 'var(--ink)' }}>{screen.understood}</div>}

            <div className="flex" style={{ gap: 4, flexWrap: 'wrap' }}>
              {terms.slice(0, criteriaCount).map((t, i) => {
                const reading = screen.readings.find((r) => r.as && t.startsWith(r.as.split(/\s/)[0]))
                return (
                  <span key={t} className="flex items-center" title={reading ? `“${reading.phrase}” — ${reading.why ?? ''}` : undefined}
                    style={{ gap: 4, fontSize: 'var(--fs-tiny)', padding: '1px 2px 1px 6px', border: '1px solid var(--hairline)', borderRadius: 'var(--r-sm)', color: 'var(--ink)' }}>
                    {reading && <span style={{ color: 'var(--ink-faint)' }}>“{reading.phrase}”</span>}
                    <span className="num">{t}</span>
                    <button type="button" className="btn-ghost" style={{ padding: '0 4px' }} aria-label={`remove ${t}`}
                      disabled={busy !== null} onClick={() => removeTerm(i)}>✕</button>
                  </span>
                )
              })}
              {criteriaCount === 0 && <span style={{ color: 'var(--ink-faint)', fontSize: 'var(--fs-tiny)' }}>no criteria</span>}
            </div>

            {screen.unsupported.map((u, i) => (
              <div key={i} style={{ fontSize: 'var(--fs-tiny)', color: 'var(--state-down)' }}>not expressible: {u.phrase} — {u.why}</div>
            ))}
            {screen.missing && Object.keys(screen.missing).length > 0 && (
              <div style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-faint)' }}>
                excluded for missing data: {Object.entries(screen.missing).map(([f, n]) => `${n} without ${f}`).join(', ')}
              </div>
            )}

            {screen.question && (
              <div className="flex items-center" style={{ gap: 6, flexWrap: 'wrap' }}>
                <span style={{ color: 'var(--core-hot)', fontSize: 'var(--fs-tiny)' }}>{screen.question}</span>
                {screen.choices.map((c) => (
                  <button key={c} type="button" className="btn-ghost"
                    style={{ fontSize: 'var(--fs-tiny)', padding: '1px 6px', border: '1px solid var(--hairline)', borderRadius: 'var(--r-sm)', textTransform: 'none', letterSpacing: 0 }}
                    title="send to Ask Genesis" onClick={() => askGenesis(c)}>{c}</button>
                ))}
              </div>
            )}
          </div>

          {/* -- matches ---------------------------------------------------------- */}
          <div className="scroll-y" style={{ flex: 1, minHeight: 0, overflowX: 'auto', opacity: busy ? 0.6 : 1 }}>
            {(screen.matches ?? []).length === 0
              ? <div style={{ padding: 'var(--s-5)', color: 'var(--ink-faint)' }}>Nothing matches. Remove a criterion or loosen one in chat.</div>
              : <ScreenTable screen={screen} onSort={busy ? undefined : sortBy} />}
            {screen.count !== undefined && (screen.matches ?? []).length < screen.count && (
              <div className="label" style={{ padding: '4px 8px', color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0 }}>
                showing {(screen.matches ?? []).length} of {screen.count} — add top:{screen.count} to see all
              </div>
            )}
          </div>
        </div>
      )}

      {/* -- two inputs: talk to the agent, or type the scan ------------------------ */}
      {snap.as_of && (
        <div className="flex flex-col hairline-t" style={{ padding: '6px 8px', gap: 4, flexShrink: 0, background: 'var(--bg-panel)' }}>
          {error && <div style={{ fontSize: 'var(--fs-tiny)', color: 'var(--state-down)' }}>{error}</div>}
          <form className="flex" style={{ gap: 4 }}
            onSubmit={(e) => { e.preventDefault(); if (refine.trim()) { askGenesis(refine.trim(), { refinement: !!screen }); setRefine('') } }}>
            <input value={refine} onChange={(e) => setRefine(e.target.value)} aria-label="refine in Ask Genesis"
              placeholder={screen ? 'Refine in plain English — “only ones paying a dividend”' : 'Describe the companies you want'}
              style={{ flex: 1, background: 'var(--bg-inset)', border: '1px solid var(--hairline)', borderRadius: 'var(--r-sm)', padding: '4px 8px', color: 'var(--ink)', fontSize: 'var(--fs-sm)' }} />
            <button type="submit" className="btn-ghost">ask</button>
          </form>
          <form className="flex" style={{ gap: 4 }}
            onSubmit={(e) => { e.preventDefault(); void run(`scr ${draft}`, 'running') }}>
            <span className="label num" style={{ alignSelf: 'center', color: 'var(--ink-faint)' }}>scr</span>
            <input value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="scan expression" spellCheck={false}
              placeholder="pe_forward<15 revenue_growth>10 sector=Technology sort:-roe"
              title={body.fields.map((f) => `${f.name} (${f.unit}) — ${f.meaning}`).join('\n')}
              className="num"
              style={{ flex: 1, background: 'var(--bg-inset)', border: '1px solid var(--hairline)', borderRadius: 'var(--r-sm)', padding: '4px 8px', color: 'var(--ink)', fontSize: 'var(--fs-tiny)' }} />
            <button type="submit" className="btn-ghost" disabled={busy !== null || !draft.trim()}>{busy === 'running' ? 'running…' : 'run'}</button>
          </form>
        </div>
      )}
    </div>
  )
}
