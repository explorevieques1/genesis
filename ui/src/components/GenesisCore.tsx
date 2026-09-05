// Spec: Genesis Markdown/60-UI/Genesis Core.md
//
// The animated presence. Five states, one-to-one with the Voice UX state machine
// — the same source of truth as the tray icon, three renderings, one machine.
//
// This is the `ambient` / `reduced` rendering: **no live WebGL context.** The note
// specifies three.js + R3F for the `hero` tier and Rive for the corner sigil; both
// are deliberate follow-ups, and the acceptance criterion that matters most is
// satisfied here already — every state is identifiable in a still frame, in
// greyscale, by shape and value rather than by hue.
//
// Three prohibitions from the note, all structural in this component:
//
//   1. Never the sole indicator of `halted`. The plain-DOM safety floor paints
//      that independently, and this component cannot suppress it.
//   2. **Never a control.** `pointerEvents: none` on the root — a large glowing
//      target in the centre of the screen must not be able to act.
//   3. Never a number. It shows mode, not P&L, not heat, not headroom.

import { memo, useEffect, useRef } from 'react'
import type { CoreState } from '@/types/events'
import { amplitude } from '@/lib/envelope'

interface Props {
  state: CoreState
  size?: number
}

/** Uniform sets per state — the note's model, lerped between. */
const UNIFORMS: Record<CoreState, {
  rotation: number      // rad/s of the orbital shells
  amplitude: number     // curl-noise displacement
  density: number       // particle count multiplier
  shell: number         // outer shell radius, fraction of size
  hue: [string, string] // cool shell → warm crest
  glow: number
}> = {
  idle:      { rotation: 0.10, amplitude: 0.30, density: 0.65, shell: 0.92, hue: ['#2b6fd6', '#4f9dff'], glow: 0.5 },
  listening: { rotation: 0.18, amplitude: 0.16, density: 0.95, shell: 0.74, hue: ['#3d8bff', '#9fd8ff'], glow: 0.8 },
  working:   { rotation: 0.52, amplitude: 0.62, density: 1.00, shell: 0.88, hue: ['#3d8bff', '#ffb765'], glow: 1.0 },
  speaking:  { rotation: 0.26, amplitude: 0.44, density: 0.90, shell: 0.84, hue: ['#4f9dff', '#c7e9ff'], glow: 0.9 },
  // `alert` snaps rather than eases, and the orbit freezes. A frozen orbit reads
  // as *wrong* instantly, and it survives a monochrome screenshot.
  alert:     { rotation: 0.00, amplitude: 0.05, density: 1.00, shell: 0.62, hue: ['#b3364a', '#ff6b57'], glow: 1.2 },
}

const POINTS = 620

/** Fibonacci sphere — even coverage without clustering at the poles. */
function fibonacciSphere(n: number) {
  const pts: [number, number, number][] = []
  const phi = Math.PI * (3 - Math.sqrt(5))
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2
    const r = Math.sqrt(Math.max(0, 1 - y * y))
    const th = phi * i
    pts.push([Math.cos(th) * r, y, Math.sin(th) * r])
  }
  return pts
}

const SPHERE = fibonacciSphere(POINTS)

/** Cheap curl-ish noise. Not the GPU sim the note specifies — the same silhouette. */
function displace(x: number, y: number, z: number, t: number): number {
  return (
    Math.sin(x * 2.6 + t * 0.9) *
    Math.cos(y * 2.1 - t * 0.7) *
    Math.sin(z * 2.9 + t * 0.5)
  )
}

export const GenesisCore = memo(function GenesisCore({ state, size = 240 }: Props) {
  const ref = useRef<HTMLCanvasElement | null>(null)
  const stateRef = useRef(state)
  stateRef.current = state

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const reduced =
      window.matchMedia('(prefers-reduced-motion: reduce)').matches ||
      document.documentElement.dataset.tier === 'reduced' ||
      document.documentElement.dataset.tier === 'degraded'

    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = size * dpr
    canvas.height = size * dpr
    ctx.scale(dpr, dpr)

    let raf = 0
    let t = 0
    // Transitions are eased uniform interpolations, not scene swaps — the change
    // must be perceived without being looked at. `alert` is the exception: it snaps.
    const current = { ...UNIFORMS[state] }

    const frame = () => {
      const target = UNIFORMS[stateRef.current]
      const snap = stateRef.current === 'alert'
      const k = snap ? 1 : 0.045
      current.rotation += (target.rotation - current.rotation) * k
      current.amplitude += (target.amplitude - current.amplitude) * k
      current.density += (target.density - current.density) * k
      current.shell += (target.shell - current.shell) * k
      current.glow += (target.glow - current.glow) * k

      const c = size / 2
      const R = (size / 2) * current.shell
      ctx.clearRect(0, 0, size, size)

      // Containment ring. In `alert` it closes into a solid circle — a shape
      // change, so the state reads in greyscale.
      ctx.strokeStyle = target.hue[0]
      ctx.globalAlpha = stateRef.current === 'alert' ? 0.9 : 0.28
      ctx.lineWidth = stateRef.current === 'alert' ? 2 : 1
      ctx.beginPath()
      ctx.arc(c, c, R + 8, 0, Math.PI * 2)
      ctx.stroke()

      if (stateRef.current !== 'alert') {
        // Counter-rotating orbital shells. Their speed is the `working` tell.
        for (let i = 0; i < 3; i++) {
          const dir = i % 2 === 0 ? 1 : -1
          const a = t * current.rotation * dir + (i * Math.PI) / 3
          ctx.globalAlpha = 0.16 + i * 0.05
          ctx.beginPath()
          ctx.ellipse(c, c, R * (0.98 - i * 0.1), R * (0.34 + i * 0.12), a, 0, Math.PI * 2)
          ctx.stroke()
        }
      }

      const count = Math.floor(POINTS * current.density)
      ctx.globalCompositeOperation = 'lighter'
      for (let i = 0; i < count; i++) {
        const [px, py, pz] = SPHERE[i]
        const a = t * current.rotation
        // Rotate about Y so the sphere reads as a volume rather than a disc.
        const rx = px * Math.cos(a) - pz * Math.sin(a)
        const rz = px * Math.sin(a) + pz * Math.cos(a)
        const d = displace(rx, py, rz, t) * current.amplitude
        const rr = 1 + d * 0.34
        const x = c + rx * R * rr
        const y = c + py * R * rr
        // Depth: far points recede, which is what gives the crest its flare.
        const depth = (rz + 1) / 2
        const mag = Math.abs(d)
        ctx.globalAlpha = (0.10 + depth * 0.55) * (0.45 + current.glow * 0.4)
        ctx.fillStyle = mag > 0.55 ? target.hue[1] : target.hue[0]
        const r = 0.5 + depth * 1.4 + (mag > 0.55 ? 0.7 : 0)
        ctx.fillRect(x - r / 2, y - r / 2, r, r)
      }

      // Nucleus. Pulses to the REAL envelope in `speaking` and `listening` --
      // RMS off an AnalyserNode on the TTS output or the microphone (see
      // `lib/envelope.ts`). It used to pulse to `Math.sin(t * 6)`, which looked
      // the same and meant nothing: a Genesis that was silent, mid-sentence or
      // disconnected all animated identically. On a surface that refuses to
      // display numbers it has not vouched for, a fabricated amplitude is the
      // same error as a fabricated equity curve.
      //
      // Silence is 0, so a quiet Genesis is visibly quiet.
      const live = amplitude()
      const pulse =
        stateRef.current === 'speaking' ? 1 + live * 0.55
        : stateRef.current === 'listening' ? 1 + live * 0.30
        : 1
      const g = ctx.createRadialGradient(c, c, 0, c, c, R * 0.42 * pulse)
      g.addColorStop(0, target.hue[1])
      g.addColorStop(1, 'transparent')
      ctx.globalAlpha = 0.30 * current.glow
      ctx.fillStyle = g
      ctx.beginPath()
      ctx.arc(c, c, R * 0.42 * pulse, 0, Math.PI * 2)
      ctx.fill()

      ctx.globalCompositeOperation = 'source-over'
      ctx.globalAlpha = 1

      if (!reduced) {
        t += 1 / 60
        raf = requestAnimationFrame(frame)
      }
    }
    frame()
    return () => cancelAnimationFrame(raf)
  }, [size, state])

  return (
    <div
      style={{ width: size, height: size, pointerEvents: 'none' }}
      // The state is exposed as text to assistive technology and to the tray
      // tooltip — the animation is never the only channel.
      role="img"
      aria-label={`Genesis core: ${state}`}
      title={`Genesis core: ${state}`}
    >
      <canvas ref={ref} style={{ width: size, height: size, display: 'block' }} />
    </div>
  )
})

/**
 * The `reduced` / `degraded` fallback and the corner sigil, as a static SVG in
 * the same five states — no animation frames scheduled at all.
 */
export function CoreSigil({ state, size = 22 }: { state: CoreState; size?: number }) {
  const u = UNIFORMS[state]
  const alert = state === 'alert'
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" role="img" aria-label={`Genesis: ${state}`}>
      <circle cx="12" cy="12" r={alert ? 9 : 10} fill="none" stroke={u.hue[0]}
        strokeWidth={alert ? 2.2 : 1} opacity={alert ? 1 : 0.55} />
      {!alert && (
        <ellipse cx="12" cy="12" rx="10" ry={state === 'listening' ? 3 : 5}
          fill="none" stroke={u.hue[0]} strokeWidth="0.8" opacity="0.45"
          transform={`rotate(${state === 'working' ? 30 : 0} 12 12)`} />
      )}
      <circle cx="12" cy="12" r={state === 'speaking' ? 4.4 : 3} fill={u.hue[1]}
        opacity={state === 'idle' ? 0.5 : 0.95} />
    </svg>
  )
}
