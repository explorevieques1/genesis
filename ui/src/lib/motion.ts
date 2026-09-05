// Spec: Genesis Markdown/60-UI/UI Stack.md §6 Degradation · 60-UI/Genesis Core.md
//
// One motion vocabulary, and a single switch that turns all of it off.
//
// Two constraints from the notes shape this, and they pull in the same
// direction:
//
//   - The degradation ladder (`hero → ambient → reduced → degraded`) is
//     automatic and one-way under fault. At `reduced` and below, motion is
//     *removed* — but information is not. So every animation here must be
//     decoration over a layout that is already correct when it never runs.
//     Nothing may animate into existence; things animate *having arrived*.
//   - `prefers-reduced-motion` is not a suggestion. `Genesis Core`'s acceptance
//     criteria require "no animation frames scheduled" — not a shorter
//     animation, none.
//
// Both resolve to `--motion-scale`, set to 0 by the tier attribute or the media
// query in `tokens.css`. Durations here are multiplied by it, so a single CSS
// variable disables every transition in the app without a JS branch at any
// call site.
//
// The other rule, from `Genesis Core`: state must be **distinguishable by shape
// and value, not by hue alone**. Motion is allowed to make a change pleasant to
// watch; it is never allowed to be the only thing that communicates it.

/**
 * Durations, in milliseconds, before the motion scale is applied.
 *
 * The scale is small on purpose. This is mission control: a transition long
 * enough to notice is long enough to be in the way when a number changed and
 * you needed to read it.
 */
export const DURATION = {
  /** Hover, focus ring, a value ticking. Below the threshold of attention. */
  instant: 90,
  /** A row selecting, a panel's contents swapping. */
  quick: 160,
  /** A view transition, a graph re-layout settling. */
  settle: 280,
  /** The camera easing to a focused node. Long enough to follow. */
  travel: 460,
} as const

/**
 * Easing curves.
 *
 * `standard` decelerates — things arrive and stop, which reads as physical.
 * `emphasis` overshoots very slightly; reserved for a selection, because the
 * Handshake-style focus transition needs the graph to feel like it *settled*
 * rather than teleported. `exit` accelerates away: leaving should not command
 * attention on the way out.
 */
export const EASE = {
  standard: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
  emphasis: 'cubic-bezier(0.34, 1.32, 0.52, 1)',
  exit: 'cubic-bezier(0.4, 0, 1, 1)',
  linear: 'linear',
} as const

/** The live motion scale: 1 normally, 0 at `reduced`/`degraded`/reduced-motion. */
export function motionScale(): number {
  if (typeof window === 'undefined') return 1
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--motion-scale')
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) ? value : 1
}

/** A duration in ms, scaled. Returns 0 when motion is off. */
export function ms(duration: number): number {
  return Math.round(duration * motionScale())
}

/**
 * A `transition` shorthand for inline styles.
 *
 *     style={{ transition: transition('opacity', 'transform') }}
 *
 * Never `transition: all`. Animating `all` means animating properties nobody
 * chose — including layout ones, which is how a "smooth" UI becomes a janky
 * one on a machine with 8 GB of RAM and no discrete GPU.
 */
export function transition(
  ...properties: string[]
): string {
  return properties.map((p) => `${p} ${DURATION.quick}ms ${EASE.standard}`).join(', ')
}

export function transitionWith(
  duration: number,
  ease: string = EASE.standard,
  ...properties: string[]
): string {
  return properties.map((p) => `${p} ${duration}ms ${ease}`).join(', ')
}

/**
 * Stagger delay for item `index` of a revealing list.
 *
 * Capped, and the cap is the whole point: an uncapped stagger means the 60th
 * row of a table appears two seconds after the first, and the operator is
 * waiting for data that is already in the browser. `max` bounds the total
 * reveal to something under a third of a second regardless of list length.
 */
export function stagger(index: number, step = 22, max = 260): number {
  return Math.min(index * step, max)
}

/**
 * Interpolate `from → to` with an ease. For hand-driven animations —
 * the graph camera, the core's amplitude envelope — where CSS cannot help.
 */
export function lerp(from: number, to: number, t: number): number {
  return from + (to - from) * t
}

/** Smoothstep. Gentler than `lerp` at both ends, and cheap. */
export function ease(t: number): number {
  const clamped = t < 0 ? 0 : t > 1 ? 1 : t
  return clamped * clamped * (3 - 2 * clamped)
}

/**
 * A frame-rate-independent approach toward a target.
 *
 * Used by anything that chases a moving value — the core's radius following
 * the speech envelope, the graph camera following a selection. `rate` is the
 * fraction closed per 16 ms frame; scaling by `dt` keeps the motion identical
 * whether the loop is running at 60 fps or the 10 fps the busy clock uses.
 */
export function approach(current: number, target: number, rate: number, dt: number): number {
  const factor = 1 - Math.pow(1 - rate, dt / 16.667)
  return current + (target - current) * factor
}
