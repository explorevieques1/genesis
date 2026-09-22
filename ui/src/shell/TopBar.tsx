// Spec: Genesis Markdown/60-UI/Dashboard.md · 60-UI/UI Stack.md §6
//
// The banner. One row, and the discipline is what is *not* in it.
//
// Left to right, and the order is the argument:
//
//   1. The sigil and the word GENESIS — identity, and the Core's state, which
//      is the one animated thing in the chrome.
//   2. The command line, immediately beside it. It is the primary input to the
//      whole system (Operating Model §4), so it sits at the start of the bar
//      rather than floating between the nav and a row of status dots.
//   3. The main categories. Text, not icons: nine workspaces with real names
//      beat nine glyphs you have to hover to identify.
//   4. Then nothing until the right edge: voice, clear space, theme.
//
// **The status readouts are not here.** Daemon connection, the six organ health
// states, the render tier and the kill switch all live in the status widget one
// row below — one place to look for "is the system alive", instead of a dot in
// the banner, a strip under it and a bar under that.
//
// **A page whose capability is absent is dimmed, not hidden.** Hiding it would
// make the system look smaller than it is; dimming it says "this exists and is
// not built", which is the true statement and the one that matches the vault.

import { useCapabilities } from '@/api/capabilities'
import { CoreSigil } from '@/components/GenesisCore'
import { TapToSpeak, type VoiceReply } from '@/components/TapToSpeak'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useGenesis } from '@/store/useGenesis'
import { PAGES, type PageId } from './pages'

interface Props {
  page: PageId
  onPage: (page: PageId) => void
  onCommand: () => void
  onClearSpace: () => void
  http: string
  onReply: (reply: VoiceReply) => void
}

export function TopBar({
  page, onPage, onCommand, onClearSpace, http, onReply,
}: Props) {
  const coreState = useGenesis((s) => s.coreState)
  const { state } = useCapabilities()
  const capabilities = state.status === 'ready' ? state.data.capabilities : null

  return (
    <div
      className="flex items-center hairline-b"
      // 36px and a single baseline. The bar used to be 40 to fit the kill
      // switch's two lines; the kill switch now lives in the status widget, so
      // everything left in here is one line tall and centres on one axis.
      style={{ flexShrink: 0, height: 36, background: 'var(--bg-deep)', gap: 'var(--s-2)' }}
    >
      {/* identity */}
      <div className="flex items-center gap-2" style={{ padding: '0 11px', flexShrink: 0 }}>
        <CoreSigil state={coreState} size={17} />
        <span
          style={{
            fontSize: 'var(--fs-sm)', fontWeight: 700,
            letterSpacing: '0.24em', color: 'var(--ink)',
          }}
        >
          GENESIS
        </span>
      </div>

      {/* ---- the command line ----
        *
        * Reads as a field, not a toolbar icon: it reaches every page, panel,
        * series, agent and tool by name, and it is the door the parity rule
        * requires a person to be able to use for anything Genesis can do.
        *
        * It is still a button: focus belongs to the real input inside the
        * palette, and two focusable text fields for one search is how you get
        * a keystroke typed into the wrong one. */}
      <button
        className="flex items-center gap-2"
        onClick={onCommand}
        title="Search pages, panels, symbols, agents and every tool by name — or type a command"
        style={{
          flex: '0 0 clamp(160px, 20vw, 280px)',
          height: 24, padding: '0 var(--s-3)',
          background: 'var(--bg-inset)',
          border: '1px solid var(--hairline)',
          borderRadius: 'var(--r-sm)',
          color: 'var(--ink-faint)',
          fontSize: 'var(--fs-sm)',
        }}
      >
        <span aria-hidden style={{ color: 'var(--ink-dim)' }}>⌕</span>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          Search…
        </span>
        <span style={{ flex: 1 }} />
        <kbd
          className="num"
          style={{
            fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)',
            border: '1px solid var(--hairline-bright)', borderRadius: 3,
            padding: '0 var(--s-2)', flexShrink: 0,
          }}
        >
          ⌘K
        </kbd>
      </button>

      {/* pages */}
      {/* The pages never compress. Below ~1500px the workspace switcher and the
          nav were overlapping — "SETTINGS" printed on top of "FORENSICS" — so
          the nav is pinned and the switcher is the thing that gives. Navigation
          is the more important of the two. */}
      <nav className="flex items-stretch self-stretch" style={{ flexShrink: 0 }}>
        {PAGES.map((def) => {
          const capability = def.requires && capabilities ? capabilities[def.requires] : null
          const absent = capability ? !capability.built : false
          const active = page === def.id
          return (
            <button
              key={def.id}
              onClick={() => onPage(def.id)}
              title={absent ? `${def.hint} — not built: ${capability?.detail}` : def.hint}
              style={{
                padding: '0 12px',
                fontSize: 'var(--fs-tiny)',
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
                color: active ? 'var(--ink)' : absent ? 'var(--ink-ghost)' : 'var(--ink-faint)',
                // The active marker is a rule under the label, not a filled
                // pill: it reads at a glance and adds no weight to the bar.
                boxShadow: active ? 'inset 0 -2px 0 var(--core)' : 'none',
                transition: 'color 120ms ease, box-shadow 160ms cubic-bezier(0.2,0.8,0.2,1)',
                whiteSpace: 'nowrap',
              }}
            >
              {def.label}
            </button>
          )
        })}
      </nav>

      <span style={{ flex: 1, minWidth: 8 }} />

      <TapToSpeak http={http} onReply={onReply} />

      {/* clear space — Home has no dock to clear */}
      {page !== 'home' && (
        <button
          className="btn-ghost"
          title="Close every panel in this workspace. Spawn what you want back by code — ⌘K, then CH, EV, BM…"
          onClick={onClearSpace}
          style={{ flexShrink: 0, color: 'var(--ink-ghost)' }}
        >
          clear space
        </button>
      )}

      <ThemeToggle />
    </div>
  )
}
