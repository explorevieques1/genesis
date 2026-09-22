// Spec: Genesis Markdown/20-Agents/Research/Agent — Session Plan.md · 70-Schemas/Idea Schema.md
//
// `TI` — the ideas on the desk, ranked, priced, with the gate's answer beside
// each one.
//
// Three authors, one store: what the trader recorded, what the Idea Synthesizer
// argued for, and what a news brief produced. They are shown and ranked
// together because that is how they are stored — a news idea does not get its
// own board, it competes.
//
// **Every price here was computed, not reasoned.** The brief supplies a
// direction and a reason in words; entry, stop and targets come from
// `research/setup.py` — ATR, the trend read, and the structural levels the
// charting engine found. The card shows which level the stop sits beyond and
// why, because "the stop is below the 50-day" and "the stop is 1.5 ATR away"
// are different claims and nobody should have to guess which they are reading.
//
// **The size is the risk gate's dry run of that exact ticket.** Not a number
// this panel computed. A dry run mints no approval and records nothing.
//
// **Nothing here places an order.** The ticker opens the chart, TradingView and
// the company page; `ticket` opens `TRD`, which is propose → approve → place
// like every other door (Safety Invariants §1).

import { api, type TradeIdeaRow, type WatchRow } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Loading } from '@/components/States'
import { openPanel } from '@/workspace/dock'
import { symbolLink, useWorkspace } from '@/workspace/context'

const AUTHOR_LABEL: Record<string, string> = {
  'news-catalyst': 'news',
  'idea-synthesizer': 'synthesizer',
  human: 'mine',
}
const AUTHOR_COLOR: Record<string, string> = {
  'news-catalyst': 'var(--state-blocked)',
  'idea-synthesizer': 'var(--ink-dim)',
  human: 'var(--verdict-pass)',
}

const num = (v: number | null | undefined, digits = 2) =>
  v == null ? '—' : v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })

export function TradeIdeasPanel() {
  const read = useRead(() => api.tradeIdeas(), [])
  const { select } = useWorkspace()

  // Every branch but `ready` has `data: null`, and a panel that narrows with a
  // cast instead of the discriminant reads `.actionable` off null — which is
  // exactly how this one failed. The union is the check.
  if (read.state.status === 'loading') return <Loading rows={5} />
  if (read.state.status !== 'ready') return <Absent reason={read.state.reason} onRetry={read.reload} />
  const body = read.state.data

  /**
   * One pick, every symbol panel follows — the page's symbol link group.
   * `symbolId` is the canonical id the chart and the ticket key on; `symbolLink`
   * derives what TradingView and the company page want. Nobody guesses the
   * ticker: both come from what the idea was stored with.
   */
  const go = (row: { symbol: string; symbol_id?: string | null }, panel?: 'chart' | 'tradingview' | 'company-profile') => {
    select({ ...symbolLink(row.symbol), ...(row.symbol_id ? { symbolId: row.symbol_id } : {}) })
    if (panel) openPanel(panel, { id: panel })
  }

  return (
    <div className="scroll-y h-full" style={{ padding: 'var(--s-4) var(--s-5)', background: 'var(--bg-void)' }}>
      <div className="flex items-baseline gap-3" style={{ marginBottom: 'var(--s-3)' }}>
        <span className="label" style={{ color: 'var(--ink-dim)' }}>
          {body.actionable} of {body.ideas.length} actionable
        </span>
        <span className="label" style={{ color: 'var(--ink-ghost)' }}>
          prices from the chart · size from the risk gate · nothing here is an order
        </span>
      </div>

      {body.degraded.map((d) => (
        <div key={d} className="label" style={{ color: 'var(--state-blocked)', textTransform: 'none', letterSpacing: 0, marginBottom: 'var(--s-2)' }}>⚠ {d}</div>
      ))}
      {body.desk.map((d) => (
        <div key={d} className="label" style={{ color: 'var(--state-down)', textTransform: 'none', letterSpacing: 0, marginBottom: 'var(--s-2)' }}>⛔ {d}</div>
      ))}

      {body.ideas.length === 0 && (
        <div className="label" style={{ color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0 }}>
          No live ideas on the desk. The weekend news review writes them here, or record one
          yourself — <span className="num">genesis idea add</span>.
        </div>
      )}

      {body.ideas.map((row) => <Idea key={row.idea_id} row={row} go={go} />)}

      {body.watching.length > 0 && (
        <>
          <div className="label" style={{ color: 'var(--ink-dim)', margin: 'var(--s-4) 0 var(--s-2)' }}>
            Watching · no side, nothing to size
          </div>
          {body.watching.map((w) => <Watch key={w.id} row={w} go={go} />)}
        </>
      )}
    </div>
  )
}

type Go = (row: { symbol: string; symbol_id?: string | null }, panel?: 'chart' | 'tradingview' | 'company-profile') => void

function Ticker({ row, go }: { row: { symbol: string; symbol_id?: string | null }; go: Go }) {
  // The symbol itself is the link — one click puts every symbol panel on it.
  return (
    <span className="flex items-baseline gap-2">
      <button
        type="button"
        onClick={() => go(row, 'chart')}
        title="Chart it here, and point every symbol panel at it"
        style={{ background: 'none', border: 0, padding: 0, cursor: 'pointer',
                 fontSize: 'var(--fs-md)', color: 'var(--ink)', textDecoration: 'underline dotted' }}
      >
        {row.symbol}
      </button>
      <button type="button" onClick={() => go(row, 'tradingview')} className="label" title="Open it on TradingView (tier 3)"
              style={{ background: 'none', border: 0, padding: 0, cursor: 'pointer', color: 'var(--ink-ghost)' }}>TV</button>
      <button type="button" onClick={() => go(row, 'company-profile')} className="label" title="Filings and fundamentals for this issuer"
              style={{ background: 'none', border: 0, padding: 0, cursor: 'pointer', color: 'var(--ink-ghost)' }}>CO</button>
    </span>
  )
}

function Idea({ row, go }: { row: TradeIdeaRow; go: Go }) {
  const s = row.chart_setup
  return (
    <div style={{ borderLeft: `2px solid ${row.blocked ? 'var(--ink-ghost)' : 'var(--verdict-pass)'}`,
                  paddingLeft: 'var(--s-3)', marginBottom: 'var(--s-4)' }}>
      <div className="flex items-baseline gap-2">
        <span className="num" style={{ color: 'var(--ink-faint)' }}>{row.rank}</span>
        <span style={{ color: row.direction === 'long' ? 'var(--verdict-pass)' : 'var(--state-down)' }}>
          {row.direction === 'long' ? '▲' : '▼'}
        </span>
        <Ticker row={row} go={go} />
        <span className="label" style={{ color: AUTHOR_COLOR[row.author] ?? 'var(--ink-faint)' }}>
          {AUTHOR_LABEL[row.author] ?? row.author}
        </span>
        {row.size ? (
          <span className="num" style={{ color: 'var(--verdict-pass)' }}>{row.size} ×</span>
        ) : (
          <span className="label" style={{ color: 'var(--ink-ghost)' }}>unsized</span>
        )}
        {row.binding && <span className="label" style={{ color: 'var(--state-blocked)' }}>bound by {row.binding}</span>}
      </div>

      {/* The setup, computed from bars: this is the part that makes the idea a
          trade rather than an opinion. */}
      {s && (
        <div className="num" style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)', margin: 'var(--s-1) 0' }}>
          entry {num(s.entry_zone[0])}–{num(s.entry_zone[1])} · stop {num(s.stop)} · targets{' '}
          {s.targets.map((t: number) => num(t)).join(' / ')}
          <span style={{ color: 'var(--ink-faint)' }}> · risk {num(s.risk_per_unit)}/unit · {s.rr}R</span>
        </div>
      )}
      {s && (
        <div className="label" style={{ color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0 }}>
          {s.trend} / {s.swing} · ATR {num(s.atr)} · spot {num(s.spot)} · {s.bars} bars from {s.source} (tier {s.tier})
        </div>
      )}
      {s && (
        <div className="label" style={{ color: 'var(--ink-dim)', textTransform: 'none', letterSpacing: 0 }}>
          stop: {s.stop_why}
        </div>
      )}

      <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink-dim)', margin: 'var(--s-1) 0', whiteSpace: 'pre-wrap' }}>
        {row.thesis}
      </div>

      {/* Idea Schema: no invalidation, no idea. Never collapsed. */}
      <div className="label" style={{ color: 'var(--ink)', textTransform: 'none', letterSpacing: 0 }}>
        Wrong if: {row.invalidation}
      </div>

      {(s?.warnings ?? []).map((w: string) => (
        <div key={w} className="label" style={{ color: 'var(--state-blocked)', textTransform: 'none', letterSpacing: 0 }}>⚠ {w}</div>
      ))}
      {row.conflicts.map((c) => (
        <div key={c} className="label" style={{ color: 'var(--state-blocked)', textTransform: 'none', letterSpacing: 0 }}>— {c}</div>
      ))}

      <div className="flex items-baseline gap-3" style={{ marginTop: 'var(--s-1)' }}>
        <button
          type="button"
          onClick={() => { go(row); openPanel('order-ticket', { id: 'order-ticket' }) }}
          disabled={row.blocked}
          className="label"
          title={row.blocked ? 'the gate cannot size this idea — see the reasons above' : 'open the ticket for this contract'}
          style={{ background: 'none', border: 0, padding: 0,
                   cursor: row.blocked ? 'not-allowed' : 'pointer',
                   color: row.blocked ? 'var(--ink-ghost)' : 'var(--ink-dim)' }}
        >
          ticket
        </button>
        {row.brief_title && <span className="label" style={{ color: 'var(--ink-ghost)' }}>from “{row.brief_title}”</span>}
      </div>
    </div>
  )
}

function Watch({ row, go }: { row: WatchRow; go: Go }) {
  return (
    <div style={{ borderLeft: '2px solid var(--ink-ghost)', paddingLeft: 'var(--s-3)', marginBottom: 'var(--s-3)' }}>
      <Ticker row={row} go={go} />
      <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink-dim)' }}>{row.idea}</div>
      {row.rationale && (
        <div className="label" style={{ color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0 }}>{row.rationale}</div>
      )}
    </div>
  )
}
