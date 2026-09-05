// Spec: Genesis Markdown/60-UI/Dashboard.md · 60-UI/UI Stack.md §6
//
// The banner. One row, and the discipline is what is *not* in it.
//
// A trading platform's top bar is where every team puts their feature, and the
// result is forty pixels of icons nobody can name. This one carries five things
// and each earns its place:
//
//   1. The sigil and the word GENESIS — identity, and the Core's state, which
//      is the one animated thing in the chrome.
//   2. The pages. Text, not icons: eight destinations with real names beat
//      eight glyphs you have to hover to identify.
//   3. Search. One field, ⌘K, which is where every professional tool put it.
//   4. The workspace switcher — small, and only when the page has more than one.
//   5. Voice, and the kill switch.
//
// Nothing else. No notification bell, no avatar, no logo lockup, no breadcrumb.
// The numbers live one row below, in the safety strip, where `UI Stack §6`
// requires them to render in plain DOM independent of everything above.
//
// **A page whose capability is absent is dimmed, not hidden.** Hiding it would
// make the system look smaller than it is; dimming it says "this exists and is
// not built", which is the true statement and the one that matches the vault.

import { useCapabilities } from '@/api/capabilities'
import { CoreSigil } from '@/components/GenesisCore'
import { KillSwitch } from '@/components/KillSwitch'
import { TapToSpeak, type VoiceReply } from '@/components/TapToSpeak'
import { useGenesis } from '@/store/useGenesis'
import { PAGES, type PageId } from './pages'
import { presetsFor, type Preset } from '@/workspace/presets'

interface Props {
  page: PageId
  onPage: (page: PageId) => void
  preset: Preset | null
  onPreset: (preset: Preset) => void
  onCommand: () => void
  onResetWorkspace: () => void
  http: string
  onReply: (reply: VoiceReply) => void
}

export function TopBar({
  page, onPage, preset, onPreset, onCommand, onResetWorkspace, http, onReply,
}: Props) {
  const coreState = useGenesis((s) => s.coreState)
  const connection = useGenesis((s) => s.connection)
  const { state } = useCapabilities()
  const capabilities = state.status === 'ready' ? state.data.capabilities : null
  const presets = presetsFor(page)

  return (
    <div
      className="flex items-stretch hairline-b"
      // 40px, not 34: the kill switch is two lines (the control and the note
      // saying it is a separate process), and `Dashboard` requires it
      // "persistent, always visible, never behind a menu". Clipping it to fit a
      // thinner bar would be trading the one control that must always work for
      // six pixels of chrome.
      style={{ flexShrink: 0, height: 40, background: 'var(--bg-deep)' }}
    >
      {/* identity */}
      <div
        className="flex items-center gap-2 hairline-r"
        style={{ padding: '0 11px', flexShrink: 0 }}
      >
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

      {/* pages */}
      {/* The pages never compress. Below ~1500px the workspace switcher and the
          nav were overlapping — "SETTINGS" printed on top of "FORENSICS" — so
          the nav is pinned and the switcher is the thing that gives. Navigation
          is the more important of the two. */}
      <nav className="flex items-stretch" style={{ flexShrink: 0 }}>
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

      {/* workspace — only when there is a choice to make */}
      {presets.length > 1 && preset && (
        <div
          className="flex items-center gap-1 scroll-x"
          style={{ padding: '0 8px', minWidth: 0 }}
        >
          <span
            className="label"
            style={{ color: 'var(--ink-ghost)', flexShrink: 0 }}
          >
            workspace
          </span>
          {presets.map((option) => (
            <button
              key={option.id}
              className="btn-ghost"
              title={option.hint}
              data-active={preset.id === option.id}
              onClick={() => onPreset(option)}
              style={{
                flexShrink: 0, whiteSpace: 'nowrap',
                color: preset.id === option.id ? 'var(--ink)' : undefined,
                borderColor: preset.id === option.id ? 'var(--hairline-bright)' : undefined,
                background: preset.id === option.id ? 'var(--bg-raised)' : undefined,
              }}
            >
              {option.label}
            </button>
          ))}
          <button
            className="btn-ghost"
            title="Discard your arrangement and return this workspace to its default layout"
            onClick={onResetWorkspace}
            style={{ color: 'var(--ink-ghost)' }}
          >
            reset
          </button>
        </div>
      )}

      {/* search */}
      <button
        className="flex items-center gap-2 hairline-l"
        onClick={onCommand}
        title="Search symbols, pages, tools and agents"
        style={{
          padding: '0 11px', color: 'var(--ink-faint)',
          fontSize: 'var(--fs-tiny)', flexShrink: 0,
        }}
      >
        <span aria-hidden style={{ opacity: 0.7 }}>⌕</span>
        <span>search</span>
        <kbd
          className="num"
          style={{
            fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)',
            border: '1px solid var(--hairline)', borderRadius: 3,
            padding: '0 3px',
          }}
        >
          ⌘K
        </kbd>
      </button>

      {/* connection — a dot, because it is binary and constant */}
      <div
        className="flex items-center hairline-l"
        style={{ padding: '0 9px', flexShrink: 0 }}
        title={
          connection.status === 'open'
            ? `connected to the daemon${connection.gap ? ' — with a gap in the event stream' : ''}`
            : `not connected (${connection.status}) — is \`genesis serve\` running?`
        }
      >
        <span
          style={{
            width: 6, height: 6, borderRadius: '50%',
            background:
              connection.status === 'open'
                ? connection.gap ? 'var(--state-blocked)' : 'var(--verdict-pass)'
                : 'var(--state-down)',
          }}
        />
      </div>

      <TapToSpeak http={http} onReply={onReply} />
      <KillSwitch />
    </div>
  )
}
