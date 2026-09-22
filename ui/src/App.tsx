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
// **The nine main categories are nine workspaces.** Each is a Dockview dock
// with its own persisted arrangement, seeded once from `SEEDS` and the
// operator's from then on. Any module opens into any of them, by short code,
// as many times as they want — see `60-UI/Workspaces.md`.
//
// `home` is the exception and has no dock: it is the command line, and it
// stays empty (Operating Model §3).

import { useCallback, useEffect, useState } from 'react'
import { CapabilityProvider } from '@/api/capabilities'
import { PanelBoundary } from '@/components/PanelBoundary'
import { SystemHealthBar } from '@/components/SystemHealth'
import type { VoiceReply } from '@/components/TapToSpeak'
import { selectBusy, useGenesis } from '@/store/useGenesis'
import { makeTransport } from '@/transport/live'
import { speak, stopSpeaking } from '@/lib/speak'
import { CommandBar } from '@/shell/CommandBar'
import { PALETTE_EVENT } from '@/shell/catalogue'
import { revealPanel } from '@/workspace/dock'
import { TopBar } from '@/shell/TopBar'
import { DEFAULT_PAGE, PAGES, type PageId } from '@/shell/pages'
import { Workspace } from '@/workspace/Workspace'
import { WorkspaceProvider, useWorkspace } from '@/workspace/context'
import { clearSpace } from '@/workspace/dock'

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
  // Called for its side effect, not its value: the clock is what runs `prune()`
  // on the event store. `SafetyFloor` used to consume the `now` it returns.
  useClock()
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
  const [commandOpen, setCommandOpen] = useState(false)
  // A line another surface asked ⌘K to open with — `MAP` handing over a command.
  const [paletteQuery, setPaletteQuery] = useState('')
  const [reply, setReply] = useState<VoiceReply | null>(null)
  // Why the reply was not spoken, when it was not. Held beside the text rather
  // than swallowed: silence with no explanation is indistinguishable from
  // Genesis not having heard you.
  const [unspoken, setUnspoken] = useState<string | null>(null)

  /**
   * Show a reply, and say it.
   *
   * Speech is fired and not awaited — the text must appear immediately, and
   * the audio arrives a beat later. A failure to synthesise annotates the
   * reply; it never suppresses it.
   */
  const onReply = useCallback((next: VoiceReply) => {
    setReply(next)
    setUnspoken(null)

    // Genesis putting a panel on screen, through the same dock API a person
    // uses (Operating Model §3). This is the one sanctioned way something
    // appears unasked-for: the human asked, and this is the answer arriving in
    // the form the answer has. A command that returns no `data` opens nothing,
    // which is why the canvas is the only case here and adding a second one
    // takes a deliberate edit — this is now the second and third.
    //
    // `note that ...`, `open note X`, `search notes ...` — the command wrote or
    // found a note, and the answer is that note on screen. Same door as the
    // panel uses: `select` then `revealPanel`, no private channel.
    const notePath = next.data?.note_path
    if (notePath) {
      setPage('journal')
      select({ notePath })
      revealPanel('notebook', { title: 'Notebook' })
    }

    // A screen from ⌘K or voice: the answer is the SCR table.
    if (next.data?.screen) {
      setPage('research')
      revealPanel('screener', { title: 'Screener' })
    }

    const canvasId = next.data?.canvas_id
    if (canvasId) {
      setPage('research')
      // A second research command should update the canvas you are looking at,
      // not stack another one beside it — and "the canvas you are looking at"
      // includes one you opened yourself with `CA`, which a private id would
      // have missed. `revealPanel` matches on component, not on who opened it.
      revealPanel('research-canvas', { title: 'Canvas' })
    }

    if (next.spoken?.trim()) {
      void speak(next.spoken).then((attempt) => {
        if (!attempt.ok && attempt.reason) setUnspoken(attempt.reason)
      })
    }
  }, [select])

  useEffect(() => {
    const onPalette = (e: Event) => {
      setPaletteQuery((e as CustomEvent<string>).detail)
      setCommandOpen(true)
    }
    window.addEventListener(PALETTE_EVENT, onPalette)
    return () => window.removeEventListener(PALETTE_EVENT, onPalette)
  }, [])

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

  const goToPage = useCallback((next: PageId) => {
    setPage(next)
    if (window.location.hash.slice(1) !== next) window.location.hash = next
  }, [])

  // Back/forward, and a hash typed by hand.
  useEffect(() => {
    const onHash = () => {
      const next = pageFromHash()
      if (next) setPage(next)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // ⌘K, and ⌘1…⌘9 for the pages. Registered on the window rather than a
  // container so they work regardless of what has focus.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const meta = event.metaKey || event.ctrlKey
      if (meta && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteQuery('')
        setCommandOpen((open) => !open)
        return
      }
      if (meta && /^[0-9]$/.test(event.key)) {
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
        onCommand={() => { setPaletteQuery(''); setCommandOpen(true) }}
        onClearSpace={clearSpace}
        http={HTTP}
        onReply={onReply}
      />

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
          {unspoken && (
            <span
              className="label"
              style={{ color: 'var(--state-blocked)', textTransform: 'none', letterSpacing: 0 }}
              title={unspoken}
            >
              not spoken — {unspoken}
            </span>
          )}
          <button
            className="btn-ghost"
            style={{ marginLeft: 'auto' }}
            onClick={() => { stopSpeaking(); setReply(null); setUnspoken(null) }}
          >
            dismiss
          </button>
        </div>
      )}

      {/* ---- the status widget ----

           Daemon connection, the six organ health states, the render tier and
           the kill switch, in one row. The approval-mode strip that used to sit
           above it is gone from the chrome: it showed an em dash in four of five
           cells because there is no broker and no position in this phase, and
           Operating Model §3 says nothing is on screen that was not asked for.
           The full readout — approval mode, heat, daily-loss headroom, open
           positions, feed — lives in Settings → Approval, rendered by the same
           `SafetyFloor` component so the two cannot drift.

           **This must come back to the chrome before Phase 7.** Heat and
           headroom become live numbers the moment there is a position, and a
           number that matters behind a click is a number nobody reads.

           Its own boundary, and the reason is not hypothetical: a missing
           snapshot field once reached `money()`, threw, and React unmounted the
           entire tree because one string was undefined. */}
      <div className="hairline-b" style={{ flexShrink: 0, height: 26 }}>
        <PanelBoundary name="status">
          <SystemHealthBar />
        </PanelBoundary>
      </div>

      {/* ---- the workspace: everything that may fail on its own ----

           On `home` there is no dock, by design. The command line *is* the
           page: Operating Model §3's "the blank canvas must be
           self-describing" is the whole of what stands between an empty screen
           and a dead end. Every other category is a workspace with its own
           persisted arrangement, into which any module can be spawned. */}
      <div style={{ flex: 1, minHeight: 0 }}>
        {page === 'home' ? (
          <PanelBoundary name="home">
            <CommandBar
              open
              page={page}
              variant="inline"
              onClose={() => {}}
              onPage={goToPage}
              onSymbol={(symbolId, timeframe) => select({ symbolId, timeframe })}
              onCommandResult={onReply}
            />
          </PanelBoundary>
        ) : (
          <Workspace page={page} />
        )}
      </div>

      <CommandBar
        open={commandOpen}
        page={page}
        initialQuery={paletteQuery}
        onClose={() => { setCommandOpen(false); setPaletteQuery('') }}
        onPage={goToPage}
        onSymbol={(symbolId, timeframe) => select({ symbolId, timeframe })}
        onCommandResult={onReply}
      />
    </div>
  )
}
