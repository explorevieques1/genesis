// Spec: Genesis Markdown/60-UI/Terminal.md
//
// A door into the live dock, for the things that are not the dock.
//
// The command line has to be able to say "open this module" without being a
// child of Dockview — it is rendered by the shell, beside the workspace rather
// than inside it. Threading an `openPanel` callback down through App, TopBar
// and CommandBar would be four files of prop plumbing for one function, so the
// live `DockviewApi` is registered here when the dock mounts and read when
// something wants to open something.
//
// **This holds no state a refresh must not lose.** The api reference is live
// wiring, not data; the layout itself is Dockview's, serialised to
// localStorage by `Workspace.tsx`. If this module is empty — the dock has not
// mounted yet — opening is a no-op that returns `false`, and the caller says
// so rather than silently doing nothing.

import type { DockviewApi } from 'dockview'
import type { PanelId } from './modules'

let dock: DockviewApi | null = null
let seq = 0

/**
 * One pending open, held while there is no dock to open into.
 *
 * Typing `AI` on Home — which has no dock — should still open Ask Genesis. The
 * caller navigates to a page that *does* have a dock and the open is replayed
 * the moment that dock registers. One slot, not a queue: a second request
 * before the dock mounts replaces the first, which is what "I changed my mind"
 * should do.
 */
let pending: { component: PanelId; options: OpenOptions } | null = null

export function setDockApi(api: DockviewApi | null) {
  dock = api
  if (api && pending) {
    const { component, options } = pending
    pending = null
    // After the current tick: `Workspace.onReady` registers the api and *then*
    // seeds the dock with `api.clear()`. Replaying synchronously here would add
    // the panel just for `build()` to wipe it a line later.
    setTimeout(() => openPanel(component, options), 0)
  }
}

export interface OpenOptions {
  /**
   * A stable identity, when the caller wants focus-or-add instead of another
   * instance. Omit it and every open is a new panel.
   */
  id?: string
  title?: string
  /** Reaches the panel component as `props.params`. */
  params?: Record<string, unknown>
}

/**
 * Open a panel in the dock.
 *
 * **A module may be open many times in one workspace, and usually should be.**
 * Two charts side by side is the ordinary case, not an edge one: comparing
 * NVDA against the index is two `CH`s, and reading a run against last week's is
 * two `EQ`s. So the default is a fresh instance every time, keyed by a counter
 * — the same discipline a terminal multiplexer uses, and the reason this feels
 * like a workspace rather than a set of screens with one slot each.
 *
 * Pass `id` when a second copy would be wrong or confusing: a tool panel is
 * `tool:<tool id>`, so typing a tool's name twice takes you back to the form
 * you already filled in rather than handing you an empty one beside it.
 */
export function openPanel(component: PanelId, options: OpenOptions = {}): boolean {
  if (!dock) {
    // No dock here (Home). Remember it; `setDockApi` replays it once the
    // caller navigates somewhere with a workspace.
    pending = { component, options }
    return false
  }
  if (options.id) {
    const existing = dock.getPanel(options.id)
    if (existing) {
      existing.api.setActive()
      return true
    }
  }
  dock.addPanel({
    id: options.id ?? `${component}#${++seq}`,
    component,
    title: options.title ?? component,
    params: options.params,
  })
  return true
}

/** Is there a dock to open into? The command line disables its actions if not. */
export function dockReady(): boolean {
  return dock !== null
}

/**
 * Bring *a* panel of this type to the front, opening one only if none exists.
 *
 * Distinct from `openPanel`, and the distinction is the whole point. `openPanel`
 * answers *"give me a panel"* — a fresh instance every time, which is right when
 * you asked for a chart and want another chart. This answers *"make sure one is
 * on screen"*, which is what a **driver** panel wants: a watchlist setting a
 * symbol needs a chart visible, not a new chart per click.
 *
 * The bug this exists to kill: keying on a private id (`watchlist-tv`) finds
 * only panels *this* caller opened. A TradingView panel the operator opened by
 * hand is `tradingview#1`, so the lookup missed and every click stacked another
 * one. Identity here is the **component**, not who opened it — a panel is a
 * panel regardless of which door it came through, which is the same parity
 * argument `Operating Model` §2 makes about Genesis and the human.
 *
 * Returns true when a panel of that type is now on screen.
 */
export function revealPanel(component: PanelId, options: OpenOptions = {}): boolean {
  if (!dock) {
    pending = { component, options }
    return false
  }
  // `panels` is dock order, so this is the first one laid out rather than the
  // most recently touched. Stable is what matters: clicking ten symbols must
  // drive the same chart every time, not wander between two open ones.
  const existing = dock.panels.find((p) => p.view.contentComponent === component)
  if (existing) {
    existing.api.setActive()
    return true
  }
  return openPanel(component, options)
}

/**
 * Close everything in the current workspace.
 *
 * "Clear space", in the top bar. Not a reset to a default arrangement — an
 * empty one, which is the thing a person actually wants when a category has
 * accumulated fourteen panels they no longer need. The empty layout persists
 * like any other; the way back is to spawn what you want by code, which is
 * cheaper than remembering which preset was called what.
 */
export function clearSpace(): boolean {
  if (!dock) return false
  dock.clear()
  return true
}
