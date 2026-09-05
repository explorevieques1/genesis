// Spec: Genesis Markdown/70-Schemas/Event Schema.md §System health
//
// Six organs, each with a health state that is `unknown` until something says
// otherwise. `unknown` is a real value here and it renders differently from `ok`
// — a health panel that shows green before it has heard from anything is a
// proprioceptive lie (Biological Design §3).

import { memo } from 'react'
import { useGenesis } from '@/store/useGenesis'
import type { HealthState, SystemHealth as Health } from '@/types/fleet'

const COLOR: Record<HealthState, string> = {
  ok: 'var(--verdict-pass)',
  degraded: 'var(--state-degraded)',
  down: 'var(--state-down)',
  unknown: 'var(--ink-ghost)',
}

/** Shape as well as colour, so the row reads in greyscale. */
const GLYPH: Record<HealthState, string> = {
  ok: '━', degraded: '╌', down: '✕', unknown: '?',
}

const ORGANS: { key: keyof Health; label: string; organ: string }[] = [
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

  return (
    <div className="flex items-center gap-[10px] px-3" style={{ background: 'var(--bg-panel)' }}>
      {ORGANS.map((o) => {
        const st = health[o.key]
        return (
          <div key={o.key} className="flex items-center gap-[4px]" title={`${o.label} — ${o.organ} · ${st}`}>
            <span className="num" style={{ color: COLOR[st], fontSize: 'var(--fs-tiny)' }}>{GLYPH[st]}</span>
            <span
              style={{
                fontSize: 'var(--fs-micro)',
                letterSpacing: '0.08em',
                color: st === 'ok' ? 'var(--ink-faint)' : COLOR[st],
                textTransform: 'uppercase',
              }}
            >
              {o.label}
            </span>
          </div>
        )
      })}
      <div
        className="label"
        style={{ marginLeft: 'auto', color: tier === 'degraded' ? 'var(--state-degraded)' : 'var(--ink-ghost)' }}
        title="UI Stack §6 — the render tier. Dropping a tier is logged as ui.tier_changed; a UI that quietly went blind is the failure this exists against."
      >
        tier {tier}
      </div>
    </div>
  )
})
