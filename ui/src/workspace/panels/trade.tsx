// Spec: Genesis Markdown/20-Agents/Execution/Agent — Order Manager.md · 60-UI/Dashboard.md §Order ticket
//
// TRD — the order ticket, the position, and the working orders, for the symbol
// the chart is on.
//
// The only place a person places an order, and it goes through the pre-trade
// risk engine exactly like anything else would (Safety Invariants #1). Two
// ways through, and both spend an approval:
//
//   confirm  (default)   BUY → the gate's answer → a confirm bar naming the
//                        contract and size → placed.
//   one click            the mode `auto-within-limits`, switched on here with
//                        an arm-then-fire toggle. BUY places — unless the gate
//                        demotes the order to confirm, which it says.
//
// Nothing on this panel computes risk. Worst case, resizes and rejections come
// from the server with the check that bound; the ticket shows them verbatim.

import { useEffect, useMemo, useState } from 'react'
import {
  api, TransportError,
  type ExecOrder, type ExecPosition, type ExecState, type OrderTicket, type ProposeResult,
} from '@/api/client'
import { useExecState } from '@/api/useExecState'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { Chip, Metric, PanelBody, Section, Table } from '@/components/Primitives'
import { useWorkspace } from '@/workspace/context'

const BUY = 'var(--verdict-pass)'
const SELL = 'var(--verdict-blocked)'

type Pending = { result: ProposeResult; ticket: OrderTicket; expires: number }

function message(err: unknown): string {
  return err instanceof TransportError ? err.message : String((err as Error)?.message ?? err)
}

function useTicking(active: boolean) {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setTick((n) => n + 1), 500)
    return () => clearInterval(id)
  }, [active])
}

export function TradePanel() {
  const { symbolId } = useWorkspace()
  const { read, reload } = useExecState()

  if (read.status === 'loading') return <Loading rows={6} label="order path" />
  if (read.status === 'off') return <Absent reason={read.reason} onRetry={reload} />
  if (read.status === 'error') return <Absent reason={read.reason} onRetry={reload} />
  return <Desk state={read.state} symbolId={symbolId} />
}

function Desk({ state, symbolId }: { state: ExecState; symbolId: string | null }) {
  const [note, setNote] = useState<{ tone: 'good' | 'bad'; text: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  async function act<T>(label: string, fn: () => Promise<T>, done?: (r: T) => string | null) {
    setBusy(label)
    setNote(null)
    try {
      const r = await fn()
      const text = done?.(r)
      if (text) setNote({ tone: 'good', text })
      return r
    } catch (e) {
      setNote({ tone: 'bad', text: message(e) })
      return null
    } finally {
      setBusy(null)
    }
  }

  const live = state.connection.state === 'live'
  const halted = state.halt.engaged
  const position = state.positions.find((p) => p.symbol_id === symbolId) ?? null
  const orders = state.orders.filter((o) => o.symbol_id === symbolId && o.working)

  return (
    <PanelBody>
      <Header state={state} busy={busy} act={act} />

      {(halted || state.reconciliation.matched === false) && (
        <HaltBanner state={state} busy={busy} act={act} />
      )}

      {note && (
        <div className="label" style={{ textTransform: 'none', letterSpacing: 0,
          color: note.tone === 'good' ? 'var(--verdict-pass)' : 'var(--verdict-blocked)' }}>
          {note.text}
        </div>
      )}

      {!symbolId ? (
        <Empty hint="Pick a contract on the chart (CH) or in Live data (LD); this ticket follows it.">
          no symbol selected
        </Empty>
      ) : (
        <>
          <Ticket symbolId={symbolId} state={state} disabled={!live || !!busy} act={act} />
          <PositionBox symbolId={symbolId} position={position} orders={orders} state={state}
            disabled={!live || !!busy} act={act} />
          <Orders orders={orders} disabled={!live || !!busy} act={act} position={position} />
        </>
      )}

      <OtherPositions state={state} symbolId={symbolId} />
      <Quality />
    </PanelBody>
  )
}

type Act = <T>(label: string, fn: () => Promise<T>, done?: (r: T) => string | null) => Promise<T | null>

// -- header: connection, mode, kill switch ----------------------------------

function Header({ state, busy, act }: { state: ExecState; busy: string | null; act: Act }) {
  const [armed, setArmed] = useState(false)
  const conn = state.connection.state
  const oneClick = state.one_click

  return (
    <Section title="order path" dense>
      <div className="flex items-center gap-2 flex-wrap" style={{ fontSize: 'var(--fs-tiny)' }}>
        <Chip tone={conn === 'live' ? 'good' : conn === 'down' ? 'bad' : 'neutral'}
          title={state.connection.detail}>{conn}</Chip>
        {state.account && <Chip tone={state.account.startsWith('D') ? 'spinal' : 'bad'}>{state.account.startsWith('D') ? 'paper' : 'LIVE'} {state.account}</Chip>}
        <Chip tone={state.killswitch.healthy ? 'good' : 'warn'}
          title={`kill switch process on :${state.killswitch.port}`}>
          kill switch {state.killswitch.healthy ? 'up' : 'unreachable'}
        </Chip>
        <Chip tone={state.reconciliation.matched ? 'good' : state.reconciliation.matched === false ? 'bad' : 'neutral'}
          title={state.reconciliation.detail}>
          {state.reconciliation.matched ? 'reconciled' : state.reconciliation.matched === false ? 'mismatch' : 'unreconciled'}
        </Chip>
        {state.daily_pnl !== null && <span className="num" style={{ color: Number(state.daily_pnl) >= 0 ? BUY : SELL }}>
          day {Number(state.daily_pnl) >= 0 ? '+' : ''}{Number(state.daily_pnl).toFixed(2)}
        </span>}
        <span style={{ flex: 1 }} />
        {armed ? (
          <>
            <button className="btn" style={{ borderColor: oneClick ? undefined : 'var(--state-blocked)' }}
              disabled={!!busy}
              onClick={() => { setArmed(false); act('mode', () => api.execMode(oneClick ? 'confirm' : 'auto-within-limits'),
                (r) => `approval mode: ${r.mode}`) }}>
              {oneClick ? 'turn one-click off' : 'turn one-click ON — orders place without a confirm step'}
            </button>
            <button className="btn-ghost" onClick={() => setArmed(false)}>keep</button>
          </>
        ) : (
          <button className="btn-ghost" data-active={oneClick} onClick={() => setArmed(true)}
            title="auto-within-limits: an order that passes every risk check places on the click">
            one-click {oneClick ? 'on' : 'off'}
          </button>
        )}
      </div>
      {state.limits && (
        <div className="label" style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--ink-ghost)', marginTop: 4 }}>
          limits: {state.limits.max_contracts_per_symbol} contracts per symbol · daily loss {state.limits.max_daily_loss_usd} ·
          {' '}{state.limits.symbol_allowlist.join(' ')}
        </div>
      )}
    </Section>
  )
}

function HaltBanner({ state, busy, act }: { state: ExecState; busy: string | null; act: Act }) {
  const [resolution, setResolution] = useState('')
  const mismatch = state.reconciliation.matched === false
  return (
    <div style={{ border: '1px solid var(--verdict-blocked)', borderRadius: 'var(--r-sm)', padding: 8 }}>
      <div style={{ color: 'var(--verdict-blocked)', fontWeight: 600 }}>
        {state.halt.engaged ? `HALTED · ${state.halt.level} · ${state.halt.trigger}` : 'RECONCILIATION MISMATCH'}
      </div>
      <div className="label" style={{ textTransform: 'none', letterSpacing: 0, marginTop: 4 }}>
        {state.halt.detail || state.reconciliation.detail}
      </div>
      <div className="label" style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--ink-faint)', marginTop: 4 }}>
        New orders are refused. Closing orders and protective stops still work.
      </div>
      <div className="flex gap-2 flex-wrap" style={{ marginTop: 6 }}>
        {mismatch && (
          <button className="btn" disabled={!!busy}
            title="record what IBKR holds that Genesis did not place — orders, fills, positions — so the books agree"
            onClick={() => act('adopt', () => api.execAdopt(), (r) => r.summary)}>
            adopt broker state
          </button>
        )}
        {state.halt.engaged && (
          <>
            <input className="field" placeholder="what was resolved" value={resolution}
              onChange={(e) => setResolution(e.target.value)} style={{ flex: 1, minWidth: 140 }} />
            <button className="btn" disabled={!!busy || mismatch}
              title={mismatch ? 'reconciliation must pass first' : 'resume into confirm mode'}
              onClick={() => act('resume', () => api.execResume(resolution), (r) => `resumed · mode ${r.mode}`)}>
              resume trading
            </button>
          </>
        )}
      </div>
    </div>
  )
}

// -- ticket ------------------------------------------------------------------

function Ticket({ symbolId, state, disabled, act }: { symbolId: string; state: ExecState; disabled: boolean; act: Act }) {
  const [qty, setQty] = useState(1)
  const [type, setType] = useState<'market' | 'limit'>('market')
  const [limit, setLimit] = useState('')
  const [stopKind, setStopKind] = useState<'fixed' | 'trail'>('fixed')
  const [stopPts, setStopPts] = useState('20')
  const [targetPts, setTargetPts] = useState('40')
  const [tif, setTif] = useState<'GTC' | 'DAY'>('GTC')
  const [pending, setPending] = useState<Pending | null>(null)
  const [rejected, setRejected] = useState<ProposeResult | null>(null)
  useTicking(!!pending)

  useEffect(() => { setPending(null); setRejected(null) }, [symbolId])

  function ticket(side: 'buy' | 'sell'): OrderTicket {
    return {
      symbol_id: symbolId, side, qty, order_type: type,
      limit_price: type === 'limit' ? limit : null,
      stop: stopKind === 'trail' ? { kind: 'trail', trail: stopPts } : { kind: 'fixed', offset: stopPts },
      target: targetPts.trim() ? { offset: targetPts } : null,
      tif,
    }
  }

  async function send(side: 'buy' | 'sell') {
    setPending(null); setRejected(null)
    const t = ticket(side)
    const r = await act(side, () => state.one_click ? api.execSubmit(t) : api.execPropose(t))
    if (!r) return
    if (!r.ok) { setRejected(r); return }
    if ('placed' in r && r.placed) return
    if (r.approval) setPending({ result: r, ticket: t, expires: Date.parse(r.approval.expires_at) })
  }

  async function confirm() {
    if (!pending?.result.approval) return
    const a = pending.result.approval
    await act('place', () => api.execPlace(a.approval_id, { symbol: a.local_symbol, qty: a.approved_qty }),
      (r) => r.summary)
    setPending(null)
  }

  const left = pending ? Math.max(0, Math.round((pending.expires - Date.now()) / 1000)) : 0
  const expired = !!pending && left === 0

  return (
    <Section title={`ticket · ${symbolId}`} dense>
      <div className="grid" style={{ gridTemplateColumns: 'auto 1fr', gap: '4px 8px', alignItems: 'center', fontSize: 'var(--fs-tiny)' }}>
        <span className="label">qty</span>
        <div className="flex gap-1 items-center">
          <button className="btn-ghost" onClick={() => setQty((q) => Math.max(1, q - 1))}>−</button>
          <input className="field num" type="number" min={1} step={1} value={qty} style={{ width: 52 }}
            onChange={(e) => setQty(Math.max(1, Math.floor(Number(e.target.value) || 1)))} />
          <button className="btn-ghost" onClick={() => setQty((q) => q + 1)}>+</button>
          <span style={{ flex: 1 }} />
          {(['GTC', 'DAY'] as const).map((x) => (
            <button key={x} className="btn-ghost" data-active={tif === x} onClick={() => setTif(x)}>{x}</button>
          ))}
        </div>

        <span className="label">type</span>
        <div className="flex gap-1 items-center">
          {(['market', 'limit'] as const).map((x) => (
            <button key={x} className="btn-ghost" data-active={type === x} onClick={() => setType(x)}>{x}</button>
          ))}
          {type === 'limit' && (
            <input className="field num" placeholder="limit price" value={limit} style={{ width: 96 }}
              onChange={(e) => setLimit(e.target.value)} />
          )}
        </div>

        <span className="label">stop</span>
        <div className="flex gap-1 items-center">
          {(['fixed', 'trail'] as const).map((x) => (
            <button key={x} className="btn-ghost" data-active={stopKind === x} onClick={() => setStopKind(x)}>
              {x === 'fixed' ? 'stop' : 'trailing'}
            </button>
          ))}
          <input className="field num" value={stopPts} style={{ width: 64 }} onChange={(e) => setStopPts(e.target.value)} />
          <span className="label" style={{ textTransform: 'none' }}>pts</span>
        </div>

        <span className="label">target</span>
        <div className="flex gap-1 items-center">
          <input className="field num" value={targetPts} placeholder="none" style={{ width: 64 }}
            onChange={(e) => setTargetPts(e.target.value)} />
          <span className="label" style={{ textTransform: 'none' }}>pts · blank for none</span>
        </div>
      </div>

      <div className="flex gap-2" style={{ marginTop: 8 }}>
        <button className="btn" disabled={disabled} onClick={() => send('buy')}
          style={{ flex: 1, color: BUY, borderColor: BUY, fontWeight: 600, padding: '6px 0' }}>
          {state.one_click ? 'BUY' : 'buy…'} {qty} {type === 'market' ? 'MKT' : 'LMT'}
        </button>
        <button className="btn" disabled={disabled} onClick={() => send('sell')}
          style={{ flex: 1, color: SELL, borderColor: SELL, fontWeight: 600, padding: '6px 0' }}>
          {state.one_click ? 'SELL' : 'sell…'} {qty} {type === 'market' ? 'MKT' : 'LMT'}
        </button>
      </div>

      {pending?.result.approval && (
        <ConfirmBar pending={pending} left={left} expired={expired} disabled={disabled}
          onConfirm={confirm} onCancel={() => setPending(null)} />
      )}
      {rejected && <Rejection result={rejected} onClose={() => setRejected(null)} />}
    </Section>
  )
}

function ConfirmBar({ pending, left, expired, disabled, onConfirm, onCancel }: {
  pending: Pending; left: number; expired: boolean; disabled: boolean; onConfirm: () => void; onCancel: () => void
}) {
  const a = pending.result.approval!
  const d = pending.result.decision
  const t = pending.ticket
  const colour = t.side === 'buy' ? BUY : SELL
  const stop = t.stop?.kind === 'trail' ? `trail ${t.stop.trail} pts` : `stop ${t.stop?.offset} pts`
  return (
    <div style={{ marginTop: 8, border: `1px solid ${colour}`, borderRadius: 'var(--r-sm)', padding: 8 }}>
      <div style={{ color: colour, fontWeight: 600 }}>
        {t.side.toUpperCase()} {a.approved_qty} {a.local_symbol} {t.order_type === 'market' ? 'MKT' : `LMT ${t.limit_price}`}
      </div>
      <div className="label" style={{ textTransform: 'none', letterSpacing: 0, marginTop: 2 }}>
        {stop}{t.target?.offset ? ` · target ${t.target.offset} pts` : ''} · worst case {a.worst_case_loss ?? '—'}
        {d.decision === 'resize' && ` · resized from ${d.original_qty} by ${d.binding_check}`}
        {' · '}quote {String(pending.result.proposal.arrival_mid ?? '—')} ({String(pending.result.proposal.arrival_source ?? '—')})
      </div>
      <div className="flex gap-2 items-center" style={{ marginTop: 6 }}>
        <button className="btn" disabled={disabled || expired} onClick={onConfirm} style={{ color: colour, borderColor: colour }}>
          {expired ? 'expired — send again' : `confirm ${t.side} ${a.approved_qty} ${a.local_symbol}`}
        </button>
        <button className="btn-ghost" onClick={onCancel}>cancel</button>
        <span className="label num" style={{ marginLeft: 'auto' }}>{left}s</span>
      </div>
    </div>
  )
}

function Rejection({ result, onClose }: { result: ProposeResult; onClose: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ marginTop: 8, border: '1px solid var(--verdict-blocked)', borderRadius: 'var(--r-sm)', padding: 8 }}>
      <div className="flex items-center gap-2">
        <span style={{ color: 'var(--verdict-blocked)' }}>{result.decision?.spoken_summary ?? result.reason}</span>
        <span style={{ flex: 1 }} />
        {result.decision && <button className="btn-ghost" onClick={() => setOpen((o) => !o)}>{open ? 'hide' : 'checks'}</button>}
        <button className="btn-ghost" onClick={onClose}>✕</button>
      </div>
      {open && result.decision && (
        <div style={{ marginTop: 4 }}>
          {result.decision.checks.map((c) => (
            <div key={c.id} className="label" style={{ textTransform: 'none', letterSpacing: 0,
              color: c.result === 'fail' ? 'var(--verdict-blocked)' : c.result === 'not_built' ? 'var(--ink-ghost)' : 'var(--ink-faint)' }}>
              {c.result === 'pass' ? '✓' : c.result === 'fail' ? '✗' : c.result === 'resize' ? '↓' : '·'} {c.id} {c.detail && `— ${c.detail}`}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// -- position ------------------------------------------------------------------

function PositionBox({ symbolId, position, orders, state, disabled, act }: {
  symbolId: string; position: ExecPosition | null; orders: ExecOrder[]; state: ExecState; disabled: boolean; act: Act
}) {
  const [armed, setArmed] = useState(false)
  const [trail, setTrail] = useState('15')
  const stop = orders.find((o) => o.role === 'stop' && o.ours && (o.type === 'stop' || o.type === 'trail'))

  if (!position) {
    return (
      <Section title="position" dense>
        <div className="flex items-center gap-2">
          <span className="label" style={{ textTransform: 'none' }}>flat</span>
          <span style={{ flex: 1 }} />
          {orders.some((o) => o.role === 'entry') && (
            <button className="btn-ghost" disabled={disabled}
              onClick={() => act('flatten', () => api.execFlatten(symbolId), (r) => r.summary ?? 'done')}>
              cancel working entries
            </button>
          )}
        </div>
      </Section>
    )
  }

  const long = position.qty > 0
  const upl = position.unrealized_pnl
  return (
    <Section title="position" dense actions={
      <Chip tone={position.protected ? 'good' : 'bad'} title={`${position.stop_cover} contract(s) covered by a working stop`}>
        {position.protected ? 'protected' : 'NO STOP'}
      </Chip>
    }>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(96px, 1fr))', gap: 6 }}>
        <Metric label="side" value={long ? 'long' : 'short'} />
        <Metric label="contracts" value={Math.abs(position.qty)} />
        <Metric label="avg price" value={position.avg_price} digits={2} />
        <Metric label="unrealized" value={upl} digits={2} signed tone />
        <Metric label="today" value={position.daily_pnl} digits={2} signed tone />
      </div>

      <div className="flex gap-1 flex-wrap items-center" style={{ marginTop: 6 }}>
        {armed ? (
          <>
            <button className="btn" disabled={disabled} style={{ color: SELL, borderColor: SELL }}
              onClick={() => { setArmed(false); act('flatten', () => api.execFlatten(symbolId), (r) => r.summary ?? 'flatten sent') }}>
              flatten {Math.abs(position.qty)} {position.local_symbol} at market
            </button>
            <button className="btn-ghost" onClick={() => setArmed(false)}>keep</button>
          </>
        ) : (
          <button className="btn" disabled={disabled} onClick={() => setArmed(true)} style={{ color: SELL, borderColor: SELL }}>
            flatten
          </button>
        )}
        {Math.abs(position.qty) > 1 && (
          <button className="btn-ghost" disabled={disabled}
            onClick={() => act('close', () => api.execFlatten(symbolId, 1), (r) => r.summary ?? 'closing 1')}>
            close 1
          </button>
        )}
        {stop && (
          <>
            <button className="btn-ghost" disabled={disabled}
              onClick={() => act('be', () => api.execModify(stop.client_order_id, { breakeven: true }), (r) => r.summary)}>
              stop → breakeven
            </button>
            <input className="field num" value={trail} style={{ width: 52 }} onChange={(e) => setTrail(e.target.value)} />
            <button className="btn-ghost" disabled={disabled}
              title={stop.type === 'trail' ? 'change the trail distance' : 'replace the stop with a trailing stop — the new one is working before the old one is cancelled'}
              onClick={() => act('trail', () => api.execModify(stop.client_order_id, { trail_amount: trail }), (r) => r.summary)}>
              {stop.type === 'trail' ? 'set trail' : 'trail'} pts
            </button>
          </>
        )}
      </div>
      {!state.killswitch.healthy && (
        <div className="label" style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--state-blocked)', marginTop: 4 }}>
          the kill switch process is not answering — one-click orders are demoted to confirm until it is
        </div>
      )}
    </Section>
  )
}

// -- working orders ------------------------------------------------------------

function Orders({ orders, disabled, act, position }: { orders: ExecOrder[]; disabled: boolean; act: Act; position: ExecPosition | null }) {
  const [edit, setEdit] = useState<{ ref: string; value: string } | null>(null)

  function price(o: ExecOrder): string {
    if (o.type === 'trail') return `trail ${o.trail}${o.stop ? ` @ ${o.stop}` : ''}`
    if (o.type === 'stop') return String(o.stop ?? '—')
    if (o.type === 'limit') return String(o.limit ?? '—')
    return 'MKT'
  }

  function save(o: ExecOrder) {
    if (!edit) return
    const changes = o.role === 'stop'
      ? (o.type === 'trail' ? { trail_amount: edit.value } : { stop_price: edit.value })
      : { limit_price: edit.value }
    act('modify', () => api.execModify(o.client_order_id, changes), (r) => r.summary)
    setEdit(null)
  }

  return (
    <Section title="working orders" dense>
      <Table
        rows={orders}
        keyOf={(o) => o.client_order_id}
        empty={<Empty>no working orders on this contract</Empty>}
        columns={[
          { key: 'role', header: 'role', render: (o) => <Chip tone={o.role === 'stop' ? 'bad' : o.role === 'target' ? 'good' : 'neutral'}>{o.role}</Chip> },
          { key: 'side', header: 'side', render: (o) => <span style={{ color: o.side === 'buy' ? BUY : SELL }}>{o.side}</span> },
          { key: 'qty', header: 'qty', align: 'right', render: (o) => `${o.remaining}` },
          { key: 'type', header: 'type', render: (o) => o.type },
          {
            key: 'price', header: 'price', align: 'right',
            render: (o) => edit?.ref === o.client_order_id ? (
              <span className="flex gap-1">
                <input className="field num" autoFocus value={edit.value} style={{ width: 80 }}
                  onChange={(e) => setEdit({ ref: o.client_order_id, value: e.target.value })}
                  onKeyDown={(e) => { if (e.key === 'Enter') save(o); if (e.key === 'Escape') setEdit(null) }} />
                <button className="btn-ghost" onClick={() => save(o)}>set</button>
              </span>
            ) : (
              <button className="btn-ghost num" disabled={disabled || !o.ours || o.type === 'market'}
                title={o.ours ? 'change the price' : 'placed by another client — IBKR lets only that client change it'}
                onClick={() => setEdit({ ref: o.client_order_id, value: o.type === 'trail' ? String(o.trail ?? '') : price(o) })}>
                {price(o)}
              </button>
            ),
          },
          { key: 'status', header: 'status', render: (o) => <span title={o.error ?? ''}>{o.status}</span> },
          {
            key: 'x', header: '', align: 'right',
            render: (o) => {
              const protective = o.role === 'stop' && !!position
              return (
                <button className="btn-ghost" disabled={disabled || !o.ours || protective}
                  title={protective ? 'a protective stop stays while the position is open — move it or flatten' : 'cancel'}
                  onClick={() => act('cancel', () => api.execCancel(o.client_order_id), (r) => r.summary)}>
                  ✕
                </button>
              )
            },
          },
        ]}
      />
    </Section>
  )
}

function OtherPositions({ state, symbolId }: { state: ExecState; symbolId: string | null }) {
  const { select } = useWorkspace()
  const others = useMemo(() => state.positions.filter((p) => p.symbol_id !== symbolId), [state.positions, symbolId])
  if (!others.length) return null
  return (
    <Section title="other positions" dense>
      <Table
        rows={others}
        keyOf={(p) => String(p.con_id)}
        columns={[
          { key: 's', header: 'contract', render: (p) => (
            <button className="btn-ghost" onClick={() => select({ symbolId: p.symbol_id })}>{p.local_symbol}</button>
          ) },
          { key: 'q', header: 'qty', align: 'right', render: (p) => p.qty },
          { key: 'a', header: 'avg', align: 'right', render: (p) => Number(p.avg_price).toFixed(2) },
          { key: 'u', header: 'unrl', align: 'right', render: (p) => p.unrealized_pnl === null ? '—' : Number(p.unrealized_pnl).toFixed(2) },
          { key: 'p', header: '', render: (p) => <Chip tone={p.protected ? 'good' : 'bad'}>{p.protected ? 'stop' : 'no stop'}</Chip> },
        ]}
      />
    </Section>
  )
}

// -- execution quality ---------------------------------------------------------

const VERDICT_TONE = { good: 'good', normal: 'neutral', poor: 'warn', pathological: 'bad', unmeasured: 'neutral' } as const

function Quality() {
  const { state, reload } = useRead(() => api.execQuality(), [])
  const [open, setOpen] = useState(false)
  if (state.status !== 'ready') return null
  const { aggregate: agg, fills } = state.data
  return (
    <Section title="execution quality · today" dense actions={
      <>
        <button className="btn-ghost" onClick={reload}>refresh</button>
        <button className="btn-ghost" onClick={() => setOpen((o) => !o)}>{open ? 'hide fills' : 'fills'}</button>
      </>
    }>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))', gap: 6 }}>
        <Metric label="fills" value={agg.fills} />
        <Metric label="median slippage" value={agg.median_arrival_slippage_bps} suffix=" bps" />
        <Metric label="limit fill rate" value={agg.limit_fill_rate === null ? null : `${Math.round(agg.limit_fill_rate * 100)}%`} />
        <Metric label="fees / contract" value={agg.fees_per_contract} />
      </div>
      {agg.note && (
        <div className="label" style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--ink-ghost)', marginTop: 4 }}>{agg.note}</div>
      )}
      {open && (
        <Table
          rows={fills}
          keyOf={(f) => f.fill_id}
          empty={<Empty>no fills yet</Empty>}
          columns={[
            { key: 't', header: 'time', render: (f) => new Date(f.ts).toLocaleTimeString() },
            { key: 's', header: 'fill', render: (f) => `${f.side} ${f.qty} @ ${f.fill_price}` },
            { key: 'b', header: 'slip bps', align: 'right', render: (f) => f.arrival_bps ?? '—' },
            { key: 'f', header: 'fees', align: 'right', render: (f) => f.fees },
            { key: 'v', header: 'verdict', render: (f) => <Chip tone={VERDICT_TONE[f.verdict]} title={f.why}>{f.verdict}</Chip> },
          ]}
        />
      )}
    </Section>
  )
}
