// Spec: Genesis Markdown/60-UI/UI Stack.md §9 · 10-Architecture/Biological Design.md §3
//
// The four things a panel can say when it has no chart to draw.
//
// Most UIs have one of these — a grey box reading "No data". That single state
// is a lie by compression, because it collapses four different facts a person
// needs to tell apart:
//
//   <Loading/>   the answer is coming
//   <Empty/>     the store exists, was queried, and holds nothing
//   <Absent/>    the store does not exist on this machine
//   <Unbuilt/>   the *code* does not exist; here is the note that specifies it
//
// The difference between `Empty` and `Unbuilt` is the difference between "you
// have not traded yet" and "there is no journal". Both render as an empty
// panel in a normal dashboard, and only one of them means the number beside it
// is meaningless.

import type { ReactNode } from 'react'
import type { CapabilityRecord } from '@/api/client'

function Frame({ children, tone = 'quiet' }: { children: ReactNode; tone?: 'quiet' | 'warn' }) {
  return (
    <div
      className="flex flex-col items-center justify-center h-full gap-2 px-6 text-center"
      style={{ color: tone === 'warn' ? 'var(--state-degraded)' : 'var(--ink-faint)' }}
    >
      {children}
    </div>
  )
}

/**
 * A skeleton, not a spinner.
 *
 * A spinner says "something is happening"; a skeleton says "a table of about
 * this size is arriving", which is the more useful claim and stops the layout
 * jumping when it lands. Motion is a single slow pulse, and `--motion-scale`
 * removes it entirely at `reduced` and below.
 */
export function Loading({ rows = 3, label }: { rows?: number; label?: string }) {
  return (
    <div className="flex flex-col gap-2 p-3 w-full" aria-busy="true">
      {label && <div className="label">{label}</div>}
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="skeleton"
          style={{
            height: 12,
            borderRadius: 'var(--r-sm)',
            // A gentle stagger reads as one object arriving rather than as
            // several unrelated ones.
            animationDelay: `${i * 90}ms`,
            width: `${100 - i * 9}%`,
          }}
        />
      ))}
    </div>
  )
}

/** Queried successfully; there is genuinely nothing in it yet. */
export function Empty({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <Frame>
      <div style={{ fontSize: 'var(--fs-sm)' }}>{children}</div>
      {hint && (
        <div className="label" style={{ color: 'var(--ink-ghost)', maxWidth: 380, lineHeight: 1.5 }}>
          {hint}
        </div>
      )}
    </Frame>
  )
}

/**
 * The store is not on this machine, or the daemon could not open it.
 *
 * Shows the reason verbatim. A person debugging their own machine needs the
 * exception text, not a friendly paraphrase of it.
 */
export function Absent({ reason, onRetry }: { reason: string; onRetry?: () => void }) {
  return (
    <Frame>
      <div className="label" style={{ letterSpacing: '0.16em' }}>not available</div>
      <div
        className="num"
        style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-faint)', maxWidth: 460, lineHeight: 1.6 }}
      >
        {reason}
      </div>
      {onRetry && (
        <button className="btn-ghost" onClick={onRetry} style={{ marginTop: 4 }}>
          retry
        </button>
      )}
    </Frame>
  )
}

/**
 * The capability itself does not exist yet.
 *
 * Names the vault note. This is what turns an empty page from a dead end into
 * a pointer: *"Backtest engine — specified in `20-Agents/Strategy/Agent —
 * Backtest.md`, no module on disk."* You now know it is not broken, it is
 * unbuilt, and where to read about what it is supposed to do.
 */
export function Unbuilt({ capability }: { capability: CapabilityRecord }) {
  return (
    <Frame tone="warn">
      <div
        className="label"
        style={{ letterSpacing: '0.16em', color: 'var(--state-degraded)' }}
      >
        not built yet
      </div>
      <div style={{ fontSize: 'var(--fs-base)', color: 'var(--ink-dim)' }}>{capability.label}</div>
      <div
        className="num"
        style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-faint)', maxWidth: 460, lineHeight: 1.6 }}
      >
        {capability.detail}
      </div>
      <div
        className="label"
        style={{ color: 'var(--ink-ghost)', marginTop: 6, textTransform: 'none', letterSpacing: '0.04em' }}
      >
        specified in <span className="num">{capability.spec}</span>
      </div>
    </Frame>
  )
}

/**
 * A gate: render `children` only when the capability is built.
 *
 * The ergonomic point is that the *easy* path is the honest one. Writing
 *
 *     <RequiresCapability id="backtest.engine">{() => <Report .../>}</RequiresCapability>
 *
 * is less work than checking the flag by hand, so it is what gets written, and
 * the report becomes structurally unreachable when the engine is missing.
 * `children` is a function so the subtree is not even constructed until the
 * capability is confirmed.
 */
export function RequiresCapability({
  capability,
  children,
  loading,
}: {
  capability: CapabilityRecord | null
  children: () => ReactNode
  loading?: ReactNode
}) {
  if (capability === null) return <>{loading ?? <Loading rows={4} />}</>
  if (!capability.built) return <Unbuilt capability={capability} />
  return <>{children()}</>
}
