// Spec: Genesis Markdown/50-Risk/Safety Invariants.md #1 · Genesis Markdown/50-Risk/Pre-Trade Risk Engine.md
//
// The execution path, rendered as the three legs it actually has:
//
//     propose_order  →  approval  →  place_approved
//
// **There is no `place_order`.** Not hidden, not disabled, not behind a
// permission — absent. This component models the path as a three-leg type
// (`ExecutionLeg`), so a fourth leg cannot be rendered without changing the type,
// and a shortcut between leg one and leg three is not expressible.
//
// Three further rules from the notes, each visible here:
//
//   - The risk engine fails closed. A rejection for uncertain input, missing data
//     or an exception is a rejection like any other, and it is shown as one.
//   - The verdict comes from the engine or it is not shown (UI Stack §9). There is
//     no client-side preview and no "likely to be rejected" hint.
//   - Placement is claimed only on the broker's own acknowledgement, and a fill
//     only on an observed fill. A call that returned is not evidence that the
//     order exists (Biological Design §3 — proprioception before ambition).

import { memo } from 'react'
import { useGenesis } from '@/store/useGenesis'
import type { ExecutionLeg, OrderFlight } from '@/types/fleet'
import { ago, money } from '@/lib/format'

const LEGS: { id: ExecutionLeg; label: string; who: string }[] = [
  { id: 'propose_order', label: 'propose_order', who: 'any agent — afferent side, no authority' },
  { id: 'approval', label: 'approval', who: 'Pre-Trade Risk Engine · tier none · fails closed' },
  { id: 'place_approved', label: 'place_approved', who: 'Order Manager, with a signed single-use order-bound token' },
]

export const ExecutionPath = memo(function ExecutionPath({ now }: { now: number }) {
  const orders = useGenesis((s) => s.orders)
  const select = useGenesis((s) => s.select)

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="px-3 py-[6px] hairline-b" style={{ flexShrink: 0 }}>
        <div className="label">execution path</div>
        <div className="flex items-center gap-[6px]" style={{ marginTop: 4 }}>
          {LEGS.map((leg, i) => (
            <div key={leg.id} className="flex items-center gap-[6px]">
              {i > 0 && <span style={{ color: 'var(--ink-ghost)' }}>→</span>}
              <span
                className="num"
                title={leg.who}
                style={{
                  fontSize: 'var(--fs-micro)',
                  padding: '1px 6px',
                  borderRadius: 2,
                  border: `1px solid ${i === 1 ? 'var(--spinal)' : 'var(--hairline-bright)'}`,
                  color: i === 1 ? 'var(--spinal)' : 'var(--ink-dim)',
                }}
              >
                {leg.label}
              </span>
            </div>
          ))}
          <span style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)', marginLeft: 6 }}>
            no <span className="num" style={{ textDecoration: 'line-through' }}>place_order</span> exists
          </span>
        </div>
      </div>

      <div className="scroll-y flex-1 min-h-0">
        {orders.length === 0 && (
          <div style={{ padding: 12, fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)' }}>
            No proposals observed. Every order that ever reaches a broker appears here first, as a
            proposal, and passes the gate in view.
          </div>
        )}
        {orders.map((o) => <OrderCard key={o.proposalId} order={o} now={now} onSelect={() => select({ traceId: o.traceId })} />)}
      </div>
    </div>
  )
})

function OrderCard({ order: o, now, onSelect }: { order: OrderFlight; now: number; onSelect: () => void }) {
  const rejected = o.verdict === 'rejected'
  const legIndex = LEGS.findIndex((l) => l.id === o.leg)

  return (
    <div
      className="anim-rise hairline-b"
      style={{ padding: '7px 12px', borderLeft: `2px solid ${rejected ? 'var(--verdict-blocked)' : o.confirmed === 'filled' ? 'var(--verdict-pass)' : 'var(--verdict-pending)'}` }}
    >
      <div className="flex items-baseline gap-2">
        <span className="num" style={{ fontSize: 'var(--fs-sm)', fontWeight: 600 }}>{o.symbol}</span>
        <span
          className="num"
          style={{ fontSize: 'var(--fs-micro)', color: o.side === 'buy' ? 'var(--verdict-pass)' : 'var(--state-degraded)' }}
        >
          {o.side.toUpperCase()} {o.qty}
        </span>
        <span className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)' }}>
          @ {o.limitPrice ? money(o.limitPrice) : 'mkt'}
        </span>
        <button onClick={onSelect} className="ml-auto num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)' }}>
          {o.traceId} · {ago(now - o.at)}
        </button>
      </div>

      <div className="flex items-center gap-1" style={{ margin: '5px 0' }}>
        {LEGS.map((leg, i) => {
          const reached = i <= legIndex
          const blocked = rejected && i >= 1
          return (
            <div key={leg.id} className="flex-1" title={leg.who}>
              <div
                style={{
                  height: 3,
                  background: blocked && i === 1 ? 'var(--verdict-blocked)'
                    : blocked ? 'var(--bg-inset)'
                    : reached ? 'var(--verdict-pass)' : 'var(--bg-inset)',
                }}
              />
              <div
                className="num"
                style={{
                  fontSize: 'var(--fs-micro)', marginTop: 2,
                  color: blocked && i === 1 ? 'var(--verdict-blocked)'
                    : reached ? 'var(--ink-dim)' : 'var(--ink-ghost)',
                }}
              >
                {leg.label}
              </div>
            </div>
          )
        })}
      </div>

      {o.checks.length > 0 && (
        <div style={{ marginTop: 4 }}>
          <div className="label">binding check — the engine's own output</div>
          {o.checks.map((c) => (
            <div key={c.rule} className="flex items-baseline gap-2" style={{ fontSize: 'var(--fs-micro)' }}>
              <span style={{ color: c.verdict === 'pass' ? 'var(--verdict-pass)' : 'var(--verdict-blocked)', width: 12 }}>
                {c.verdict === 'pass' ? '✓' : '✕'}
              </span>
              <span className="num" style={{ color: 'var(--ink-faint)', width: 168 }}>{c.rule}</span>
              <span className="num" style={{ color: c.verdict === 'pass' ? 'var(--ink-dim)' : 'var(--verdict-blocked)' }}>
                {c.value} / {c.limit}
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3" style={{ marginTop: 5, fontSize: 'var(--fs-micro)' }}>
        <Confirmation order={o} />
        {o.approvalId && (
          <span className="num" style={{ color: 'var(--ink-ghost)' }}>
            token: single-use, bound to {o.proposalId}
          </span>
        )}
      </div>
    </div>
  )
}

/**
 * The proprioception line. The distinction between "we asked" and "we know" is
 * the whole point: drift between believed and actual state is the failure that
 * loses money quietly.
 */
function Confirmation({ order: o }: { order: OrderFlight }) {
  if (o.verdict === 'rejected') {
    return <span style={{ color: 'var(--verdict-blocked)' }}>REJECTED — no order was created</span>
  }
  if (o.confirmed === 'filled' && o.fill) {
    return (
      <span style={{ color: 'var(--verdict-pass)' }}>
        FILL OBSERVED — {o.fill.qty} @ {money(o.fill.price)}
      </span>
    )
  }
  if (o.confirmed === 'placed') {
    return <span style={{ color: 'var(--verdict-pending)' }}>BROKER ACKNOWLEDGED — no fill observed yet</span>
  }
  if (o.verdict === 'approved') {
    return <span style={{ color: 'var(--verdict-pending)' }}>APPROVED — not yet placed</span>
  }
  return <span style={{ color: 'var(--ink-ghost)' }}>AWAITING VERDICT — the gate has not answered</span>
}
