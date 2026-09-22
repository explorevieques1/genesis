// Spec: Genesis Markdown/70-Schemas/Event Schema.md §System health · 60-UI/UI Stack.md §6
//
// The status widget: one row, and the only place in the chrome that answers
// "is this thing alive".
//
// It carries the daemon connection, the six organ health states, the render
// tier and the kill switch. Those used to be spread across three rows — a dot
// in the banner, a collapsed safety strip, and a bare row of words — which
// meant three places to look and none of them complete.
//
// Two properties it must keep, both from UI Stack §6:
//
//   - Plain DOM, no canvas, no WebGL, no dependency on the socket being alive.
//     It reads the last value received and says how old it is.
//   - `unknown` is a real value and renders differently from `ok`. A health
//     widget that shows green before it has heard from anything is a
//     proprioceptive lie (Biological Design §3).
//
// The kill switch lives here rather than in the banner because this is the
// health row: the control that stops the system belongs beside the readout that
// tells you it needs stopping. It is still persistent, always visible, never
// behind a menu, and still a direct HTTP call to a separate process.

import { memo } from 'react'
import { useGenesis } from '@/store/useGenesis'
import { EconCountdown } from './EconCountdown'
import { KillSwitch } from './KillSwitch'
import { openPanel } from '@/workspace/dock'
import type { HealthState, SystemHealth as Health } from '@/types/fleet'

export const HEALTH_COLOR: Record<HealthState, string> = {
  ok: 'var(--verdict-pass)',
  degraded: 'var(--state-degraded)',
  down: 'var(--state-down)',
  unknown: 'var(--ink-ghost)',
}

/** Shape as well as colour, so the row reads in greyscale. */
export const HEALTH_GLYPH: Record<HealthState, string> = {
  ok: '━', degraded: '╌', down: '✕', unknown: '?',
}

export const ORGANS: { key: keyof Health; label: string; organ: string }[] = [
  { key: 'daemon', label: 'daemon', organ: 'Heartbeat — the loop and scheduler' },
  { key: 'memory', label: 'memory', organ: 'Long-term memory — the five-layer fabric' },
  { key: 'risk', label: 'risk', organ: 'Muscle memory — the deterministic gate' },
  { key: 'voice', label: 'voice', organ: 'The surface, not the spine' },
  { key: 'execution', label: 'execution', organ: 'Hands — behind the strictest guards' },
  { key: 'connectivity', label: 'link', organ: 'Afferent nerves — feeds and MCP sessions' },
]

export const SystemHealthBar = memo(function SystemHealthBar() {
  const health = useGenesis((s) => s.health)
  const tier = useGenesis((s) => s.tier)
  const connection = useGenesis((s) => s.connection)

  // The websocket is not one of the six organs — it is how we hear from all of
  // them — so it leads the row rather than sitting inside it.
  const feed: HealthState =
    connection.status !== 'open' ? 'down' : connection.gap ? 'degraded' : 'ok'
  const feedLabel = connection.kind === 'mock'
    ? 'mock data'
    : connection.status === 'open' && connection.gap ? 'gap' : connection.status

  return (
    <div
      className="flex items-stretch"
      style={{ background: 'var(--bg-panel)', height: '100%' }}
    >
      <Segment
        color={connection.kind === 'mock' ? 'var(--state-mock)' : HEALTH_COLOR[feed]}
        glyph={HEALTH_GLYPH[feed]}
        label={feedLabel}
        title={
          connection.status === 'open'
            ? `connected to the daemon${connection.gap ? ' — with a gap in the event stream' : ''}`
            : `not connected (${connection.status}) — is \`genesis serve\` running?`
        }
        strong
      />

      <span className="hairline-l" style={{ margin: '4px 0' }} />

      {ORGANS.map((o) => (
        <Segment
          key={o.key}
          color={HEALTH_COLOR[health[o.key]]}
          glyph={HEALTH_GLYPH[health[o.key]]}
          label={o.label}
          title={`${o.label} — ${o.organ} · ${health[o.key]}`}
          dim={health[o.key] === 'ok'}
        />
      ))}

      {/* The one non-health thing in the chrome, and it shows nothing at all --
          its own separator included -- until there is a print ahead. */}
      <EconCountdown />

      {/* The row is a summary; HLT is the readout. Parity rule: this opens the
          same module `⌘K → HLT` opens, by the same call. */}
      <button
        style={{ flex: 1, minWidth: 8 }}
        title="Open the status module (HLT) — daemon, organs, models, data sources"
        onClick={() => openPanel('status', { id: 'status', title: 'Status' })}
      />

      <div
        className="flex items-center px-3"
        title="UI Stack §6 — the render tier. Dropping a tier is logged as ui.tier_changed; a UI that quietly went blind is the failure this exists against."
      >
        <span
          className="label"
          style={{ color: tier === 'degraded' ? 'var(--state-degraded)' : 'var(--ink-ghost)' }}
        >
          tier {tier}
        </span>
      </div>

      <span className="hairline-l" style={{ margin: '4px 0' }} />
      <KillSwitch compact />
    </div>
  )
})

function Segment({
  color, glyph, label, title, dim = false, strong = false,
}: {
  color: string
  glyph: string
  label: string
  title: string
  dim?: boolean
  strong?: boolean
}) {
  return (
    <div className="flex items-center gap-[5px] px-[9px]" title={title}>
      <span className="num" style={{ color, fontSize: 'var(--fs-tiny)' }}>{glyph}</span>
      <span
        style={{
          fontSize: 'var(--fs-micro)',
          letterSpacing: '0.08em',
          fontWeight: strong ? 600 : 400,
          color: dim ? 'var(--ink-faint)' : color,
          textTransform: 'uppercase',
          whiteSpace: 'nowrap',
        }}
      >
        {label}
      </span>
    </div>
  )
}
