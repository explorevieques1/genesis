// Spec: Genesis Markdown/50-Risk/Kill Switch.md · Genesis Markdown/60-UI/Dashboard.md §Kill switch
//
// Persistent, always visible, never behind a menu.
//
// Biological Design §Where the analogy breaks: Genesis has no intrinsic
// self-preservation drive, so homeostasis is entirely bolted on. The kill switch
// must be **external, and outside the agent's own control** — a separate process
// that works when everything else is broken.
//
// Two consequences that are visible in this file:
//
//   1. It does not go through the task bus and it does not go through the
//      WebSocket. Direct HTTP to the kill-switch process. If the daemon is wedged
//      this still fires, which is the entire point of it being a separate process.
//   2. The real hotkey lives in the Tauri Rust host, not here — it must fire when
//      the WebView is white-screened, which a renderer-side accelerator does not
//      survive. The keyboard binding below is a convenience for the browser
//      build, and the UI says so rather than implying a guarantee it cannot make.
//
// Dashboard §No modal blocking: the market does not wait for a dialog, so the
// confirm step is an inline arm-then-fire, not a modal.

import { memo, useCallback, useEffect, useState } from 'react'
import { useGenesis } from '@/store/useGenesis'

// The kill switch process `genesis serve` starts (execution.killswitch_port).
// Override with VITE_GENESIS_KILL; an empty value still means "not configured".
const KILL_URL = (import.meta.env.VITE_GENESIS_KILL as string | undefined) ?? 'http://127.0.0.1:8766'

type Phase = 'idle' | 'armed' | 'firing' | 'sent' | 'failed'

export const KillSwitch = memo(function KillSwitch({ compact = false }: { compact?: boolean } = {}) {
  const halted = useGenesis((s) => s.safety.halted)
  const trigger = useGenesis((s) => s.safety.haltTrigger)
  const [phase, setPhase] = useState<Phase>('idle')
  const [detail, setDetail] = useState<string | null>(null)

  const fire = useCallback(async () => {
    setPhase('firing')
    if (!KILL_URL) {
      // No process configured. Say exactly that — never render a success state
      // for an action that had nowhere to go (Biological Design §3).
      setPhase('failed')
      setDetail('No kill-switch endpoint configured (VITE_GENESIS_KILL). Nothing was sent.')
      return
    }
    try {
      const res = await fetch(`${KILL_URL}/halt`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        // Idempotency key: firing twice must halt once (UI Stack §7).
        body: JSON.stringify({ reason: 'operator', idempotency_key: crypto.randomUUID() }),
      })
      if (!res.ok) throw new Error(String(res.status))
      // Even on a 2xx this says *sent*, not *halted*. `halted` is painted only
      // when a `halt.engaged` event confirms it — the acknowledgement, not the call.
      setPhase('sent')
      setDetail('Halt sent. Awaiting halt.engaged confirmation.')
    } catch (err) {
      setPhase('failed')
      setDetail(`Halt request failed: ${String(err)}. Use the hardware path.`)
    }
  }, [])

  // Auto-disarm: an armed switch left armed is a fat-finger waiting to happen.
  useEffect(() => {
    if (phase !== 'armed') return
    const t = setTimeout(() => setPhase('idle'), 6000)
    return () => clearTimeout(t)
  }, [phase])

  if (halted) {
    return (
      <div
        className={compact ? 'flex items-center gap-2 px-3' : 'flex flex-col justify-center px-3'}
        style={{ background: 'var(--state-down)', color: '#fff', minWidth: compact ? undefined : 190 }}
        title={compact ? `system halted — ${trigger ?? 'trigger unknown'}` : undefined}
      >
        {!compact && <div className="label" style={{ color: 'rgba(255,255,255,0.8)' }}>system</div>}
        <div
          className="num"
          style={{ fontSize: compact ? 'var(--fs-sm)' : 'var(--fs-lg)', fontWeight: 700, letterSpacing: '0.08em' }}
        >
          HALTED
        </div>
        {!compact && <div style={{ fontSize: 'var(--fs-micro)' }}>{trigger ?? 'trigger unknown'}</div>}
      </div>
    )
  }

  return (
    // `overflow: hidden` plus a non-wrapping note: in a fixed-height top bar,
    // a note that wraps to two lines makes this block taller than the bar and
    // `justify-center` then clips the BUTTON — the one control that must never
    // be unavailable. The note may be truncated; the control may not.
    <div
      className={compact ? 'flex items-center gap-2 px-3' : 'flex flex-col justify-center px-3'}
      style={{
        background: 'var(--bg-panel)', minWidth: compact ? undefined : 208,
        overflow: 'hidden', flexShrink: 0,
      }}
    >
      <div className="flex items-center gap-2">
        <button
          onClick={() => (phase === 'armed' ? fire() : setPhase('armed'))}
          title={
            phase === 'armed'
              ? 'Confirm: cancel all, flatten if configured, mode → halt'
              : 'Kill switch — separate process, direct HTTP. Click to arm.'
          }
          style={{
            border: `1px solid ${phase === 'armed' ? 'var(--verdict-blocked)' : 'var(--hairline-bright)'}`,
            background: phase === 'armed' ? 'var(--verdict-blocked)' : 'transparent',
            color: phase === 'armed' ? '#fff' : 'var(--verdict-blocked)',
            padding: compact ? '0 9px' : '3px 12px',
            borderRadius: 'var(--r-sm)',
            fontSize: 'var(--fs-sm)',
            fontWeight: 700,
            letterSpacing: '0.1em',
          }}
        >
          {phase === 'armed' ? 'CONFIRM HALT' : phase === 'firing' ? 'SENDING…' : 'KILL'}
        </button>
        {phase === 'armed' && (
          <button
            onClick={() => setPhase('idle')}
            style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)' }}
          >
            cancel
          </button>
        )}
      </div>
      {!compact && (
      <div
        style={{
          fontSize: 'var(--fs-micro)',
          color: phase === 'failed' ? 'var(--state-down)' : 'var(--ink-faint)',
          marginTop: 1,
          maxWidth: 220,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          lineHeight: 1.2,
        }}
        title={detail ?? 'Separate process — works when the daemon does not'}
      >
        {detail ?? 'separate process'}
      </div>
      )}
      {compact && detail && (
        <span
          className="label"
          title={detail}
          style={{
            color: phase === 'failed' ? 'var(--state-down)' : 'var(--ink-faint)',
            maxWidth: 200, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            textTransform: 'none', letterSpacing: 0,
          }}
        >
          {detail}
        </span>
      )}
    </div>
  )
})
