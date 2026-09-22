// Spec: Genesis Markdown/60-UI/Company Description.md
//
// `CO` — one issuer on one page: header quote, what it does, a thumbnail chart,
// the EPS grid, holders, news, and a stats rail. Read from the local company
// store; nothing here fetches a profile. "Look up" goes through the same
// `/v1/command` door as typing `NTAP profile` — the parity rule, both ways.

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, type CompanyDescription, type HistoryWindow, type PriceHistoryBody } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { openPanel } from '@/workspace/dock'
import { symbolLink, useWorkspace } from '@/workspace/context'

const UP = 'var(--verdict-pass)'
const DOWN = 'var(--verdict-blocked)'
const ACCENT = 'var(--state-degraded)'
const LINE = 'var(--judgement)'

// -- formatting (display only; arithmetic happened in `describe`) -----------

const n = (v: string | number | null | undefined) =>
  v === null || v === undefined || v === '' ? null : Number(v)

function big(v: string | number | null | undefined, prefix = ''): string {
  const x = n(v)
  if (x === null || !Number.isFinite(x)) return '—'
  for (const [cut, s] of [[1e12, 'T'], [1e9, 'B'], [1e6, 'M'], [1e3, 'K']] as const) {
    if (Math.abs(x) >= cut) return `${prefix}${(x / cut).toFixed(cut === 1e3 ? 0 : 2).replace(/\.00$/, '')}${s}`
  }
  return `${prefix}${x.toLocaleString()}`
}
const fixed = (v: string | null | undefined, places = 2, suffix = '') => {
  const x = n(v)
  return x === null ? '—' : `${x.toFixed(places)}${suffix}`
}
const int = (v: string | null | undefined) => {
  const x = n(v)
  return x === null ? '—' : Math.round(x).toLocaleString()
}
function age(iso: string): string {
  const ms = Date.now() - Date.parse(iso)
  if (!Number.isFinite(ms)) return ''
  const m = ms / 60000
  return m < 60 ? `${Math.max(1, Math.round(m))}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`
}

// -- panel ------------------------------------------------------------------

export function CompanyProfilePanel() {
  const { ticker: selected, select } = useWorkspace()
  const [draft, setDraft] = useState(selected ?? '')
  const ticker = (selected ?? '').toUpperCase()
  const known = useRead(() => api.companies(), [])
  const page = useRead(() => api.companyDescription(ticker || '—'), [ticker])
  const [looking, setLooking] = useState<string | null>(null)

  useEffect(() => setDraft(selected ?? ''), [selected])

  const lookUp = async () => {
    setLooking('looking up…')
    try {
      const r = await api.command(`${ticker} profile`)
      setLooking(r.ok ? null : r.spoken)
      page.reload()
      known.reload()
    } catch (e) {
      setLooking(e instanceof Error ? e.message : String(e))
    }
  }

  // A linked click (screener, watchlist, TV) lands on a ticker the store may
  // not hold yet. Look it up once, through the same `X profile` command the
  // button runs, so the page loads instead of asking for a second click. Once
  // per ticker: a lookup that fails leaves the button and its reason.
  const tried = useRef(new Set<string>())
  useEffect(() => {
    if (!ticker || page.state.status !== 'absent' || tried.current.has(ticker)) return
    tried.current.add(ticker)
    void lookUp()
  }, [ticker, page.state.status]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col h-full min-h-0">
      <form
        className="flex items-center gap-2 hairline-b"
        style={{ padding: '4px 8px', flexShrink: 0 }}
        onSubmit={(e) => { e.preventDefault(); if (draft.trim()) select(symbolLink(draft)) }}
      >
        <span className="label">DESCRIPTION</span>
        <input
          className="field"
          placeholder="ticker"
          value={draft}
          onChange={(e) => setDraft(e.target.value.toUpperCase())}
          style={{ width: 88 }}
          aria-label="Ticker"
        />
        {known.state.status === 'ready' && (
          <div className="flex gap-1 scroll-x" style={{ flex: 1 }}>
            {known.state.data.symbols.map((s) => (
              <button type="button" key={s} className="btn-ghost" data-active={s === ticker} onClick={() => select(symbolLink(s))}>
                {s}
              </button>
            ))}
          </div>
        )}
        {ticker && page.state.status === 'ready' && (
          <button type="button" className="btn-ghost" onClick={lookUp} title="Refetch through the company command">
            refresh
          </button>
        )}
      </form>

      {!ticker ? (
        <Empty hint="Type a ticker, or pick one already in the company store.">pick a company</Empty>
      ) : page.state.status === 'loading' || looking === 'looking up…' ? (
        <Loading rows={6} label={looking === 'looking up…' ? `looking up ${ticker}` : ticker} />
      ) : page.state.status !== 'ready' ? (
        <div className="flex flex-col gap-2" style={{ padding: 8 }}>
          <Absent reason={page.state.reason} onRetry={page.reload} />
          <button className="btn-ghost" onClick={lookUp} disabled={looking === 'looking up…'} style={{ alignSelf: 'flex-start' }}>
            look up {ticker} (same as typing “{ticker} profile”)
          </button>
          {looking && <span className="label">{looking}</span>}
        </div>
      ) : (
        <div className="scroll-y" style={{ flex: 1, minHeight: 0 }}>
          <Description d={page.state.data} />
        </div>
      )}
    </div>
  )
}

function Description({ d }: { d: CompanyDescription }) {
  const { select } = useWorkspace()
  const change = n(d.change)
  const tone = change === null ? 'var(--ink-dim)' : change >= 0 ? UP : DOWN
  const sign = change !== null && change >= 0 ? '+' : ''

  return (
    <div className="flex" style={{ flexWrap: 'wrap', fontSize: 'var(--fs-sm)', color: 'var(--ink)' }}>
      {/* main column */}
      <div style={{ flex: '1 1 460px', minWidth: 0 }}>
        <header className="flex gap-3 hairline-b" style={{ padding: 10, flexWrap: 'wrap' }}>
          <div
            aria-hidden
            style={{
              width: 56, height: 56, borderRadius: 'var(--r-sm)', background: 'var(--ink)', color: 'var(--bg-panel)',
              display: 'grid', placeItems: 'center', fontWeight: 700, fontSize: 22, flexShrink: 0,
            }}
          >
            {(d.name ?? d.symbol).slice(0, 1)}
          </div>
          <div style={{ flex: '1 1 160px', minWidth: 0 }}>
            <div className="flex items-center gap-2">
              <span style={{ fontSize: 'var(--fs-xl)', fontWeight: 600 }}>{d.name ?? d.symbol}</span>
              {d.quote_type && <span className="label hairline" style={{ padding: '0 4px', borderRadius: 'var(--r-sm)' }}>{d.quote_type === 'EQUITY' ? 'EQ' : d.quote_type}</span>}
            </div>
            <div className="label" style={{ color: 'var(--ink-dim)' }}>
              {[d.symbol, d.sector, d.industry].filter(Boolean).join(' · ')}
            </div>
            {d.website && (
              <a href={d.website} target="_blank" rel="noreferrer" style={{ color: ACCENT, fontSize: 'var(--fs-tiny)' }}>
                {d.website.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')}
              </a>
            )}
          </div>
          <div className="num" style={{ textAlign: 'right' }}>
            <div>
              <span style={{ fontSize: 'var(--fs-xl)', fontWeight: 600 }}>{d.price ? `$${fixed(d.price)}` : '—'}</span>{' '}
              <span style={{ color: tone }}>
                {sign}{fixed(d.change)} ({sign}{fixed(d.change_pct, 2, '%')})
              </span>
            </div>
            <div className="label" style={{ color: 'var(--ink-dim)' }}>
              Vol {int(d.volume)}{d.quote_date ? ` · At ${d.quote_date}` : ''}
            </div>
          </div>
        </header>

        {d.summary && (
          <p className="hairline-b" style={{ margin: 0, padding: '8px 10px', lineHeight: 1.5 }}>
            {firstSentences(d.summary, 2)}
          </p>
        )}

        <div className="flex hairline-b" style={{ flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 240px', padding: 8, minWidth: 0 }}>
            <MiniChart symbol={d.symbol} />
          </div>
          <div style={{ flex: '1 1 240px', padding: 8, minWidth: 0 }}>
            <EpsGrid eps={d.eps} currency={d.currency} />
          </div>
        </div>

        <Relations />
        <News items={d.news} />
        <Holders rows={d.holders} />

        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 6, padding: 10 }}>
          <Fn code="TV" label="TradingView" onClick={() => { select({ tvSymbol: d.symbol }); openPanel('tradingview', { title: 'TradingView' }) }} />
          <Fn code="NW" label="News" onClick={() => openPanel('news', { title: 'News' })} />
          <Fn code="CR" label="Candle ranges" onClick={() => openPanel('candle-ranges', { title: 'Candle Ranges' })} />
          <Fn code="AI" label="Ask Genesis" onClick={() => openPanel('ask-genesis', { title: 'Ask Genesis' })} />
        </div>
        <div className="label" style={{ padding: '0 10px 10px', color: 'var(--ink-faint)' }}>
          {d._sources.join(', ')} · tier 3{d._market_as_of ? ` · market data as of ${new Date(d._market_as_of).toLocaleString()}` : ''}
          {d._missing.length ? ` · missing: ${d._missing.join(', ')}` : ''}
        </div>
      </div>

      {/* stats rail */}
      <aside style={{ flex: '0 1 220px', minWidth: 200, borderLeft: '1px solid var(--hairline)', padding: '6px 10px' }}>
        <Stats s={d.stats} />
      </aside>
    </div>
  )
}

function firstSentences(text: string, count: number): string {
  const parts = text.match(/[^.!?]+[.!?]+(\s|$)/g)
  return parts ? parts.slice(0, count).join('').trim() : text
}

// -- stats rail -------------------------------------------------------------

function Stats({ s }: { s: Record<string, string | null> }) {
  const groups: [string, string][][] = [
    [['CEO', s.ceo ?? '—'], ['HQ', s.hq ?? '—'], ['Employees', int(s.employees)], ['Sector', s.sector ?? '—'], ['Sub-sector', s.industry ?? '—']],
    [['Price', s.price ? `$${fixed(s.price)}` : '—'], ['Shares Out', big(s.shares_outstanding)], ['Market Cap', big(s.market_cap, '$')], ['Currency', s.currency ?? '—'], ['Float', big(s.float_shares)], ['EV', big(s.enterprise_value)]],
    [['Insiders', fixed(s.held_insiders_pct, 1, '%')], ['Institutions', fixed(s.held_institutions_pct, 0, '%')]],
    [['P/Sales', fixed(s.price_to_sales, 1, 'x')], ['P/Book', fixed(s.price_to_book, 1, 'x')], ['EV/EBITDA', fixed(s.ev_to_ebitda, 1, 'x')], ['EV/R', fixed(s.ev_to_revenue, 1, 'x')], ['Trl P/E', fixed(s.pe_trailing, 1, 'x')], ['Fwd P/E', fixed(s.pe_forward, 1, 'x')]],
    [['Trl Yld', fixed(s.yield_trailing_pct, 2, '%')], ['Fwd Yld', fixed(s.yield_forward_pct, 2, '%')], ['5Y Avg Yld', fixed(s.yield_5y_pct, 2, '%')], ['Payout R', fixed(s.payout_ratio_pct, 2, '%')], ['Ex Div Date', s.ex_dividend_date ?? '—'], ['Div Date', s.dividend_date ?? '—']],
    [['Beta', fixed(s.beta)], ['Short', big(s.shares_short)], ['Short R', fixed(s.short_ratio)]],
  ]
  return (
    <>
      {groups.map((rows, i) => (
        <dl key={i} className={i < groups.length - 1 ? 'hairline-b' : ''} style={{ margin: 0, padding: '6px 0' }}>
          {rows.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-3" style={{ lineHeight: 1.6 }}>
              <dt style={{ color: 'var(--ink-dim)', flexShrink: 0 }}>{k}</dt>
              <dd className="num" style={{ margin: 0, textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={v}>{v}</dd>
            </div>
          ))}
        </dl>
      ))}
    </>
  )
}

// -- chart --------------------------------------------------------------------

const WINDOWS: HistoryWindow[] = ['1D', 'YTD', '1Y', '5Y']

function MiniChart({ symbol }: { symbol: string }) {
  const [win, setWin] = useState<HistoryWindow>('1Y')
  const history = useRead(() => api.priceHistory(symbol, win), [symbol, win])
  return (
    <div>
      <div className="flex items-center gap-1" style={{ marginBottom: 4 }}>
        <span style={{ color: 'var(--ink-dim)', marginRight: 6 }}>Chart</span>
        {WINDOWS.map((w) => (
          <button key={w} className="btn-ghost" data-active={w === win} onClick={() => setWin(w)}>{w}</button>
        ))}
      </div>
      {history.state.status === 'loading' ? <Loading rows={3} />
        : history.state.status !== 'ready' ? <Absent reason={history.state.reason} onRetry={history.reload} />
          : <Spark body={history.state.data} />}
    </div>
  )
}

function Spark({ body }: { body: PriceHistoryBody }) {
  const W = 300, H = 110, VOL = 18
  const pts = body.points
  const geo = useMemo(() => {
    if (pts.length < 2) return null
    const closes = pts.map((p) => p.close)
    const lo = Math.min(...closes), hi = Math.max(...closes)
    const span = hi - lo || 1
    const maxVol = Math.max(...pts.map((p) => p.volume)) || 1
    const x = (i: number) => (i / (pts.length - 1)) * W
    const y = (c: number) => 4 + (1 - (c - lo) / span) * (H - VOL - 8)
    const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.close).toFixed(1)}`).join('')
    return { lo, hi, x, y, line, area: `${line}L${W},${H - VOL}L0,${H - VOL}Z`, maxVol }
  }, [pts])
  if (!geo) return <Empty>not enough history</Empty>

  const last = pts[pts.length - 1].close
  const intraday = body.window === '1D'
  const ticks = [0, 1, 2, 3].map((k) => Math.round((k / 3) * (pts.length - 1)))
  const label = (t: number) => new Date(t * 1000).toLocaleString(undefined,
    intraday ? { hour: 'numeric', minute: '2-digit' } : body.window === '5Y' ? { year: 'numeric' } : { month: 'short' })

  return (
    <div className="flex gap-1">
      <div style={{ flex: 1, minWidth: 0 }}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 120, display: 'block' }} role="img"
          aria-label={`${body.symbol} ${body.window} closes, last ${last}`}>
          <path d={geo.area} fill={LINE} opacity={0.18} />
          <path d={geo.line} fill="none" stroke={LINE} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          {pts.map((p, i) => (
            <rect key={i} x={geo.x(i)} y={H - (p.volume / geo.maxVol) * VOL} width={Math.max(W / pts.length - 0.3, 0.4)}
              height={(p.volume / geo.maxVol) * VOL} fill="var(--ink-faint)" />
          ))}
        </svg>
        <div className="flex justify-between label" style={{ color: 'var(--ink-dim)' }}>
          {ticks.map((i) => <span key={i}>{label(pts[i].time)}</span>)}
        </div>
      </div>
      <div className="num flex flex-col justify-between" style={{ height: 120, fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)' }}>
        <span style={{ background: LINE, color: 'var(--bg-panel)', padding: '0 4px', borderRadius: 'var(--r-sm)' }}>{last.toFixed(2)}</span>
        <span>{geo.hi.toFixed(0)}</span>
        <span>{geo.lo.toFixed(0)}</span>
      </div>
    </div>
  )
}

// -- EPS ----------------------------------------------------------------------

function EpsGrid({ eps, currency }: { eps: CompanyDescription['eps']; currency: string | null }) {
  const head = <div style={{ color: 'var(--ink-dim)', marginBottom: 4 }}>EPS (GAAP actual · consensus est) ({currency ?? '—'})</div>
  if (!eps) return <>{head}<Empty hint="Needs quarterly statements and a fiscal year end in the profile.">no EPS history</Empty></>
  const cell = (c: { value: string; actual: boolean } | null, key: number) => (
    <td key={key} className="num" style={{ textAlign: 'right', padding: '1px 6px', color: c?.actual ? UP : 'var(--ink)' }}
      title={c ? (c.actual ? 'reported, diluted GAAP' : 'analyst consensus mean') : undefined}>
      {c ? Number(c.value).toFixed(2) : ''}
    </td>
  )
  return (
    <div>
      {head}
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr><th />{eps.years.map((y) => <th key={y} className="num" style={{ textAlign: 'right', padding: '1px 6px', fontWeight: 400, color: 'var(--ink-dim)' }}>{y}</th>)}</tr>
        </thead>
        <tbody>
          {eps.quarters.map((q) => (
            <tr key={q.quarter}><td style={{ color: 'var(--ink-dim)' }}>Q{q.quarter} {q.month}</td>{q.cells.map(cell)}</tr>
          ))}
          <tr style={{ borderTop: '1px solid var(--hairline)' }}>
            <td style={{ color: 'var(--ink-dim)' }}>Annual</td>{eps.annual.map(cell)}
          </tr>
        </tbody>
      </table>
    </div>
  )
}

// -- sections -------------------------------------------------------------------

function SectionHead({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-center justify-between" style={{ color: 'var(--ink-dim)', marginBottom: 4 }}>
      <span>{children}</span>{action}
    </div>
  )
}

function Fn({ code, label, onClick }: { code: string; label: string; onClick: () => void }) {
  return (
    <button className="flex items-center gap-2 btn-ghost" onClick={onClick} style={{ justifyContent: 'flex-start' }}>
      <span style={{ color: ACCENT, border: `1px solid ${ACCENT}`, borderRadius: 'var(--r-sm)', padding: '0 4px', fontSize: 'var(--fs-tiny)' }}>{code}</span>
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
    </button>
  )
}

/** Customers, suppliers, competitors, partners: no free supply-chain source.
 *  The headings stay so the page reads like the layout; the cells say why they are empty. */
function Relations() {
  return (
    <div className="hairline-b" style={{ padding: '8px 10px' }}>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 8, color: 'var(--ink-dim)' }}>
        {['Customers', 'Suppliers', 'Competitors', 'Partners'].map((h) => <span key={h}>{h}</span>)}
      </div>
      <div className="label" style={{ color: 'var(--ink-faint)', marginTop: 4 }}>
        no free source for supply-chain relationships — not shown rather than guessed
      </div>
    </div>
  )
}

function News({ items }: { items: CompanyDescription['news'] }) {
  return (
    <div className="hairline-b" style={{ padding: '8px 10px' }}>
      <SectionHead action={<Fn code="N" label="" onClick={() => openPanel('news', { title: 'News' })} />}>Latest News</SectionHead>
      {items.length === 0 ? <span className="label">no headlines cached</span> : (
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', columnGap: 16 }}>
          {items.map((a) => (
            <a key={a.link || a.title} href={a.link || undefined} target="_blank" rel="noreferrer"
              className="flex gap-3" style={{ color: 'var(--ink)', lineHeight: 1.7, minWidth: 0, textDecoration: 'none' }} title={`${a.publisher} · ${a.title}`}>
              <span className="num" style={{ color: 'var(--ink-dim)', width: 26, flexShrink: 0 }}>{age(a.published)}</span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.title}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

function Holders({ rows }: { rows: CompanyDescription['holders'] }) {
  const [all, setAll] = useState(false)
  const shown = rows.slice(0, all ? 20 : 10)
  return (
    <div className="hairline-b" style={{ padding: '8px 10px' }}>
      <SectionHead>Top Holders — $Value (Shares)</SectionHead>
      {rows.length === 0 ? <span className="label">no institutional holders cached</span> : (
        <>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', columnGap: 16 }}>
            {shown.map((h) => (
              <div key={h.holder} className="flex justify-between gap-2" style={{ lineHeight: 1.7, minWidth: 0 }} title={`${h.holder} · reported ${h.reported?.slice(0, 10) ?? '—'}`}>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.holder}</span>
                <span className="num" style={{ flexShrink: 0 }}>
                  {big(h.value)} <span style={{ color: 'var(--ink-dim)' }}>({big(h.shares)})</span>
                </span>
              </div>
            ))}
          </div>
          {rows.length > 10 && (
            <button className="btn-ghost" onClick={() => setAll(!all)} style={{ marginTop: 4 }}>
              {all ? 'Show top 10' : `Show top ${Math.min(rows.length, 20)}`}
            </button>
          )}
        </>
      )}
    </div>
  )
}
