// Spec: Genesis Markdown/60-UI/UI Stack.md · 60-UI/Dashboard.md
//
// The shell. Paint order is the specification's order, not a layout convenience.
//
//   1. The safety strip and the kill switch — plain DOM, no canvas, no socket
//      dependency. First painted, last to fail (`UI Stack §6`).
//   2. The banner and its navigation.
//   3. The workspace, which may fail without taking 1 or 2 down.
//
// The floor's independence is structural, not a promise: it is a sibling of the
// workspace in the tree and imports nothing from it, so a thrown error inside
// Dockview, React Flow or a charting library cannot unmount it. Each panel is
// additionally wrapped in its own boundary, so the blast radius of a bad series
// is one rectangle.
//
// **What changed from the previous shell.** It was a fixed three-region layout
// with four tabs over one fleet graph. `UI Stack §3` specifies Dockview —
// *"dockable, splittable, floating, serialisable"* — with named presets that
// Voice UX can target, and the build-status table recorded the gap: *"no
// serialisable presets, so Voice UX has nothing to target yet."* That is now
// closed. The eight pages beyond the fleet view are new surface area and are
// noted as such in `60-UI/Workspaces.md`.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { CapabilityProvider } from '@/api/capabilities'
import { PanelBoundary } from '@/components/PanelBoundary'
import { SafetyFloor } from '@/components/SafetyFloor'
import { SystemHealthBar } from '@/components/SystemHealth'
import type { VoiceReply } from '@/components/TapToSpeak'
import { selectBusy, useGenesis } from '@/store/useGenesis'
import { makeTransport } from '@/transport/live'
import { CommandBar } from '@/shell/CommandBar'
import { TopBar } from '@/shell/TopBar'
import { DEFAULT_PAGE, PAGES, type PageId } from '@/shell/pages'
import { Workspace } from '@/workspace/Workspace'
import { WorkspaceProvider, useWorkspace } from '@/workspace/context'
import {
  clearLayout, presetsFor, recallPreset, rememberPreset, type Preset,
} from '@/workspace/presets'

/** Where the local server lives. Loopback only — see `genesis serve`. */
const HTTP = (import.meta.env.VITE_GENESIS_HTTP as string | undefined)
  ?? 'http://127.0.0.1:8765'

/** The page named by the URL hash, if it names one. */
function pageFromHash(): PageId | null {
  const id = window.location.hash.replace(/^#/, '')
  return PAGES.some((p) => p.id === id) ? (id as PageId) : null
}

/**
 * One clock for the whole surface, and it stops when nothing is moving.
 *
 * Idle is the common case and it must be nearly free. An earlier version ran a
 * requestAnimationFrame loop at ~20 fps unconditionally — twenty-five React
 * Flow nodes and fifty-four store subscriptions re-rendering twenty times a
 * second to display a fleet doing nothing. That is the entire lag complaint on
 * an 8 GB machine, and it also contradicts what the system is supposed to be:
 * an organism at rest until asked for something.
 *
 * So the loop is gated on `selectBusy`. Nothing in flight means a 1 Hz
 * heartbeat, which is all a staleness check or an "as of" label needs.
 */
function useClock() {
  const tier = useGenesis((s) => s.tier)
  const prune = useGenesis((s) => s.prune)
  const busy = useGenesis(selectBusy)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const slow = tier === 'reduced' || tier === 'degraded' || !busy
    if (slow) {
      const t = setInterval(() => { setNow(Date.now()); prune() }, 1000)
      return () => clearInterval(t)
    }
    let raf = 0
    let last = 0
    let pruneAt = 0
    const tick = (ts: number) => {
      if (ts - last > 100) {
        last = ts
        setNow(Date.now())
        if (ts - pruneAt > 1000) { pruneAt = ts; prune() }
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [tier, prune, busy])

  return now
}

export default function App() {
  return (
    // Capabilities are read once, at the top, and every page reads the answer
    // rather than assuming. This provider is what makes "no dummy data" a
    // structure instead of a convention.
    <CapabilityProvider>
      <WorkspaceProvider>
        <Shell />
      </WorkspaceProvider>
    </CapabilityProvider>
  )
}

function Shell() {
  const now = useClock()
  const attach = useGenesis((s) => s.attach)
  const detach = useGenesis((s) => s.detach)
  const approvalMode = useGenesis((s) => s.safety.approvalMode)
  const halted = useGenesis((s) => s.safety.halted)
  const tier = useGenesis((s) => s.tier)
  const { select } = useWorkspace()

  // The page lives in the URL hash. Not for its own sake — it means a page is
  // linkable, a reload lands where you were, and the browser's back button does
  // the obvious thing. A full router would be a dependency for one string.
  const [page, setPage] = useState<PageId>(() => pageFromHash() ?? DEFAULT_PAGE)
  const [presetId, setPresetId] = useState<string | null>(null)
  const [commandOpen, setCommandOpen] = useState(false)
  const [reply, setReply] = useState<VoiceReply | null>(null)

  useEffect(() => {
    attach(makeTransport())
    return () => detach()
  }, [attach, detach])

  // The token layer keys off these, so `live` and `halted` restyle every panel
  // border and number colour from one place rather than a hundred overrides.
  useEffect(() => {
    document.documentElement.dataset.approval = approvalMode
    document.documentElement.dataset.halted = String(halted)
    document.documentElement.dataset.tier = tier
  }, [approvalMode, halted, tier])

  // The preset in force: the one last chosen on this page, or the page default.
  const preset = useMemo<Preset | null>(() => {
    const available = presetsFor(page)
    if (!available.length) return null
    const wanted = presetId ?? recallPreset(page)
    return available.find((p) => p.id === wanted) ?? available[0]
  }, [page, presetId])

  const goToPage = useCallback((next: PageId) => {
    setPage(next)
    setPresetId(null)
    if (window.location.hash.slice(1) !== next) window.location.hash = next
  }, [])

  // Back/forward, and a hash typed by hand.
  useEffect(() => {
    const onHash = () => {
      const next = pageFromHash()
      if (next) { setPage(next); setPresetId(null) }
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const choosePreset = useCallback((next: Preset) => {
    setPresetId(next.id)
    rememberPreset(next.page, next.id)
  }, [])

  const resetWorkspace = useCallback(() => {
    if (!preset) return
    clearLayout(preset.id)
    // Re-select the same preset to force a rebuild from its declared layout.
    setPresetId(null)
    requestAnimationFrame(() => setPresetId(preset.id))
  }, [preset])

  // ⌘K, and ⌘1…⌘8 for the pages. Registered on the window rather than a
  // container so they work regardless of what has focus.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const meta = event.metaKey || event.ctrlKey
      if (meta && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setCommandOpen((open) => !open)
        return
      }
      if (meta && /^[1-8]$/.test(event.key)) {
        const target = PAGES.find((p) => p.key === event.key)
        if (target) { event.preventDefault(); goToPage(target.id) }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [goToPage])

  return (
    <div className="flex flex-col h-full" style={{ background: 'var(--bg-void)' }}>
      <TopBar
        page={page}
        onPage={goToPage}
        preset={preset}
        onPreset={choosePreset}
        onCommand={() => setCommandOpen(true)}
        onResetWorkspace={resetWorkspace}
        http={HTTP}
        onReply={setReply}
      />

      {/* ---- the safety floor. plain DOM, independent of everything below ----

           Wrapped in its own boundary, and the reason is not hypothetical: a
           missing snapshot field once reached `money()`, threw, and React
           unmounted the entire tree — heat, headroom, approval mode and the
           kill switch, gone, because one string was undefined. `UI Stack §6`
           makes this the first thing painted and the last thing to fail, so
           the floor may degrade to a stub but may never take the shell with
           it. The formatters are now total as well; this is the second line
           of defence, not the only one. */}
      <div className="hairline-b flex" style={{ flexShrink: 0 }}>
        <div className="flex-1 min-w-0 scroll-x">
          <PanelBoundary name="safety-floor">
            <SafetyFloor now={now} />
          </PanelBoundary>
        </div>
      </div>

      {/* ---- the conversation. Only present when there is something to show:
              an idle Genesis says nothing, including visually. ---- */}
      {reply && (
        <div
          className="hairline-b flex items-baseline gap-3 px-3 anim-rise"
          style={{
            flexShrink: 0, minHeight: 24, background: 'var(--bg-panel)',
            borderLeft: `2px solid ${reply.ok ? 'var(--core-hot)' : 'var(--state-down)'}`,
          }}
        >
          {reply.heard && <span className="label" style={{ flexShrink: 0 }}>heard “{reply.heard}”</span>}
          <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)' }}>{reply.spoken}</span>
          {reply.detail && (
            <span className="label" style={{ color: 'var(--ink-faint)' }}>{reply.detail}</span>
          )}
          <button className="btn-ghost" style={{ marginLeft: 'auto' }} onClick={() => setReply(null)}>
            dismiss
          </button>
        </div>
      )}

      <div className="hairline-b" style={{ flexShrink: 0, height: 20 }}>
        <SystemHealthBar />
      </div>

      {/* ---- the workspace: everything that may fail on its own ---- */}
      <div style={{ flex: 1, minHeight: 0 }}>
        {preset ? (
          <Workspace preset={preset} />
        ) : (
          <div className="flex items-center justify-center h-full label" style={{ color: 'var(--ink-ghost)' }}>
            no workspace defined for this page
          </div>
        )}
      </div>

      <CommandBar
        open={commandOpen}
        onClose={() => setCommandOpen(false)}
        onPage={goToPage}
        onSymbol={(symbolId, timeframe) => select({ symbolId, timeframe })}
        onCommandResult={(text) =>
          setReply({
            ok: true, heard: text, command: 'typed',
            spoken: 'sent to the command layer',
          })
        }
      />
    </div>
  )
}
