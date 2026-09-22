// Spec: Genesis Markdown/60-UI/UI Stack.md §6 · Genesis Markdown/50-Risk/Safety Invariants.md
//
// **The safety floor sits below all four render tiers.**
//
// Position, portfolio heat, daily-loss headroom, approval mode and the kill
// switch render in plain DOM, from the last value received, with no dependency
// on WebGL, canvas, or the socket being alive. They are the first thing painted
// and the last thing to fail.
//
// Everything in this file is therefore deliberately boring: no canvas, no
// transitions that could stall, no derived numbers. It imports nothing from the
// graph layer, and it must stay that way — a compile-time dependency on React
// Flow here would make the floor fail with the surface it exists to outlive.
//
// Two rules it enforces:
//   - Stale looks stale. A heat number from a dead socket is *dangerous* if it
//     reads as confident, so past the threshold it is struck through and labelled.
//   - No UI-side risk logic. Not a preview, not a "likely to be rejected" hint.
//     The verdict comes from the Pre-Trade Risk Engine or it is not shown.
//
// **Collapsed by default — 2026-09-06.**
//
// Five cells, ~60px of permanent chrome, showing an em dash in four of them,
// because there is no broker, no position and no reconciliation in this phase.
// Operating Model §3 says nothing is on screen that was not asked for, and a
// row of placeholders is the purest form of that: it teaches the operator to
// ignore the strip, which is precisely the wrong habit for the one component
// that must be believed in Phase 7.
//
// So the default is `strip`: a single line carrying approval mode and feed
// state, expanding to the full grid on click. Every §6 property is intact --
// still plain DOM, still first painted, still no dependency on WebGL, canvas
// or the socket, still its own error boundary. What changed is how much room
// it takes when it has nothing to report.
//
// **This must return to the full grid before Phase 7.** Heat and daily-loss
// headroom become live numbers the moment there is a position, and a number
// that matters behind a click is a number nobody reads. The expansion is a
// concession to an empty system, not a design for a loaded one.

import { memo, useState } from 'react'
import { useGenesis, isStale } from '@/store/useGenesis'
import { gaugeFraction, money, pct, ago } from '@/lib/format'
import type { ApprovalMode } from '@/types/events'

const MODE_COPY: Record<ApprovalMode, { label: string; color: string; note: string }> = {
  observe: { label: 'OBSERVE', color: 'var(--state-observe)', note: 'No orders proposed' },
  confirm: { label: 'CONFIRM', color: 'var(--state-paper)', note: 'Every order needs your word' },
  // Dashboard §Design principles: live mode is unmistakable — a different colour
  // scheme, not a small badge. The token swap in tokens.css does the rest.
  live:    { label: 'LIVE',    color: 'var(--state-live)',   note: 'Real capital at risk' },
}

/**
 * The collapsed strip: one line, in the shell chrome.
 *
 * `defaultOpen` exists for the Settings panel, which renders the same
 * component expanded — one implementation, two placements, so the numbers
 * cannot drift between the summary and the detail.
 */
export const SafetyFloor = memo(function SafetyFloor({
  now, variant = 'strip', defaultOpen = false,
}: {
  now: number
  variant?: 'strip' | 'full'
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const safety = useGenesis((s) => s.safety)
  const connection = useGenesis((s) => s.connection)
  const stale = isStale(safety.asOf, now)
  const mode = MODE_COPY[safety.approvalMode]
  const feedOk = connection.status === 'open' && !connection.gap

  if (variant === 'strip' && !open) {
    return (
      <button
        className="flex items-center gap-3 w-full row-hit"
        style={{ background: 'var(--bg-panel)', padding: 'var(--s-2) var(--s-4)', textAlign: 'left' }}
        onClick={() => setOpen(true)}
        title="Approval mode, portfolio heat, daily-loss headroom, open positions and feed state"
      >
        <span className="label" style={{ flexShrink: 0 }}>approval</span>
        <span
          className="num"
          style={{ fontSize: 'var(--fs-sm)', fontWeight: 700, color: mode.color, letterSpacing: '0.06em' }}
        >
          {mode.label}
        </span>
        <span className="label" style={{ letterSpacing: 0, textTransform: 'none' }}>{mode.note}</span>

        <span style={{ flex: 1 }} />

        {/* Halted is never collapsed away. It is the one thing on this strip
            that changes what the system will do next. */}
        {safety.halted && (
          <span
            className="num"
            style={{ fontSize: 'var(--fs-sm)', fontWeight: 700, color: 'var(--state-down)' }}
          >
            HALTED
          </span>
        )}
        <span
          aria-hidden
          style={{
            width: 6, height: 6, borderRadius: 999, flexShrink: 0,
            background: feedOk ? 'var(--verdict-pass)' : 'var(--state-down)',
          }}
        />
        <span className="label" style={{ flexShrink: 0 }}>
          {connection.kind === 'mock' ? 'mock data' : connection.status}
        </span>
        <span className="label" style={{ flexShrink: 0, color: 'var(--ink-ghost)' }}>risk ▾</span>
      </button>
    )
  }

  return (
    <div className="flex flex-col" style={{ background: 'var(--hairline)', gap: 1 }}>
      {variant === 'strip' && (
        <button
          className="flex items-center gap-2 w-full row-hit"
          style={{ background: 'var(--bg-panel)', padding: 'var(--s-1) var(--s-4)', textAlign: 'left' }}
          onClick={() => setOpen(false)}
        >
          <span className="label">risk ▴ collapse</span>
        </button>
      )}
      <div className="flex items-stretch" style={{ gap: 1, background: 'var(--hairline)' }}>
      <Cell label="approval mode" width={132}>
        <div className="flex items-baseline gap-[6px]">
          <span
            className="num"
            style={{ fontSize: 'var(--fs-lg)', fontWeight: 700, color: mode.color, letterSpacing: '0.04em' }}
          >
            {mode.label}
          </span>
        </div>
        <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)' }}>{mode.note}</div>
      </Cell>

      <Gauge
        label="portfolio heat"
        value={safety.portfolioHeat}
        limit={safety.heatLimit}
        stale={stale}
        format={pct}
      />

      <Gauge
        label="daily loss headroom"
        value={safety.dailyLossHeadroom}
        limit={null}
        stale={stale}
        format={(v) => money(v, { prefix: '$' })}
        invert
      />

      <Cell label="open positions" width={104}>
        <span className={`num ${stale ? 'stale' : ''}`} style={{ fontSize: 'var(--fs-lg)', fontWeight: 600 }}>
          {safety.openPositions}
        </span>
        <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)' }}>
          {/* `asOf: 0` is "never confirmed", not "1970". Formatting an elapsed
              time from an epoch-zero timestamp produced "as of 496842h ago",
              which is worse than useless -- it reads as a real, catastrophic
              staleness rather than as the absence of a reconciliation. */}
          {safety.asOf === 0
            ? 'never reconciled'
            : stale ? `as of ${ago(now - safety.asOf)}` : 'live risk'}
        </div>
      </Cell>

      <Cell label="feed" width={128}>
        <div className="flex items-center gap-[5px]">
          <span
            style={{
              width: 6, height: 6, borderRadius: 999,
              background: connection.status === 'open' && !connection.gap
                ? 'var(--verdict-pass)' : 'var(--state-down)',
            }}
          />
          <span
            className="num"
            style={{
              fontSize: 'var(--fs-sm)',
              // A mock feed that looks live is the one thing this surface must
              // never do. It is labelled here, in the safety floor, not in a corner.
              color: connection.kind === 'mock' ? 'var(--state-mock)' : 'var(--ink)',
            }}
          >
            {connection.kind === 'mock' ? 'MOCK DATA' : connection.status.toUpperCase()}
          </span>
        </div>
        <div style={{ fontSize: 'var(--fs-micro)', color: connection.gap ? 'var(--state-degraded)' : 'var(--ink-faint)' }}>
          {connection.gap ? 'gap — replay incomplete' : connection.lastEventAt
            ? `event ${ago(now - connection.lastEventAt)}` : 'no events yet'}
        </div>
      </Cell>
      </div>
    </div>
  )
})

function Cell({ label, width, children }: { label: string; width?: number; children: React.ReactNode }) {
  return (
    <div style={{ background: 'var(--bg-panel)', padding: 'var(--s-3) var(--s-4)', minWidth: width, flexShrink: 0 }}>
      <div className="label">{label}</div>
      {children}
    </div>
  )
}

function Gauge({
  label, value, limit, stale, format, invert = false,
}: {
  label: string
  value: string
  limit: string | null
  stale: boolean
  format: (v: string) => string
  invert?: boolean
}) {
  const frac = limit ? gaugeFraction(value, limit) : 0
  const hot = !invert && frac > 0.8
  return (
    <div
      className={stale ? 'stale-box' : ''}
      style={{ background: 'var(--bg-panel)', padding: 'var(--s-3) var(--s-4)', minWidth: 168, flexShrink: 0 }}
    >
      <div className="label">{label}</div>
      <div className="flex items-baseline gap-[6px]">
        <span
          className={`num ${stale ? 'stale' : ''}`}
          style={{
            fontSize: 'var(--fs-lg)', fontWeight: 600,
            color: stale ? undefined : hot ? 'var(--verdict-blocked)' : 'var(--ink)',
          }}
        >
          {format(value)}
        </span>
        {limit && (
          <span className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)' }}>
            / {format(limit)}
          </span>
        )}
      </div>
      {limit && (
        <div style={{ height: 2, background: 'var(--bg-inset)', marginTop: 3 }}>
          <div
            style={{
              height: '100%',
              width: `${frac * 100}%`,
              background: stale ? 'var(--state-stale)' : hot ? 'var(--verdict-blocked)' : 'var(--state-working)',
            }}
          />
        </div>
      )}
      {stale && (
        <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--state-stale)' }}>STALE — not confirmed</div>
      )}
    </div>
  )
}
