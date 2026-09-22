// Spec: Genesis Markdown/60-UI/Terminal.md §The three surfaces
//
// What can I type? Every module short code and every command the deterministic
// table knows, in one panel — so the command line is discoverable without
// having to already know what to search for.
//
// It is a module like any other (`HLP`), spawnable into any workspace. The
// Home canvas stays empty (Operating Model §3); this is the thing you open
// when you want the map.
//
// Both halves are read from the running system, not hand-kept: module codes
// come from `MODULES`, commands from `GET /v1/commands` — the same table the
// daemon matches against, so this cannot drift from what actually works.

import { api } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Loading } from '@/components/States'
import { MODULES } from '@/workspace/modules'
import { PAGE_BY_ID, type PageId } from '@/shell/pages'
import { openPanel } from '@/workspace/dock'

const CATEGORY_ORDER: PageId[] = [
  'home', 'overview', 'charting', 'trade', 'research', 'backtest',
  'journal', 'automation', 'fleet', 'settings',
]

export function HelpPanel() {
  const commands = useRead(() => api.commandList(), [])

  return (
    <div className="scroll-y h-full" style={{ padding: 'var(--s-5) var(--s-6)', background: 'var(--bg-void)' }}>
      <div style={{ maxWidth: 720 }}>
        <p style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink-dim)', marginBottom: 'var(--s-5)' }}>
          Type a <strong>code</strong> into the command line (<span className="num">⌘K</span>, or the Home field) to open
          that module here. Type a <strong>sentence</strong> and it runs as a command — the same path voice uses.
        </p>

        <Heading>Modules</Heading>
        {CATEGORY_ORDER.map((page) => {
          const items = MODULES.filter((m) => m.home === page)
          if (items.length === 0) return null
          return (
            <div key={page} style={{ marginBottom: 'var(--s-4)' }}>
              <div className="label" style={{ marginBottom: 'var(--s-1)' }}>
                {PAGE_BY_ID[page]?.label ?? page}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '0 var(--s-3)', alignItems: 'baseline' }}>
                {items.map((m) => (
                  <Row
                    key={m.id}
                    code={m.code}
                    title={m.title}
                    hint={m.hint}
                    aliases={m.aliases}
                    onOpen={() => openPanel(m.id, { title: m.title })}
                  />
                ))}
              </div>
            </div>
          )
        })}

        <Heading>Commands</Heading>
        {commands.state.status === 'loading' && <Loading rows={4} />}
        {commands.state.status === 'error' && (
          <div className="label" style={{ color: 'var(--ink-faint)' }}>{commands.state.reason}</div>
        )}
        {commands.state.status === 'ready' && (
          <div className="flex flex-col" style={{ gap: 'var(--s-1)' }}>
            {commands.state.data.commands.map((c) => (
              <div key={c.name} className="flex items-baseline gap-3">
                <span className="num" style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)' }}>“{c.help}”</span>
                <span className="label" style={{ color: 'var(--ink-faint)' }}>{c.name}</span>
              </div>
            ))}
            <div className="label" style={{ marginTop: 'var(--s-2)', color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}>
              Anything the table does not match is handed to the analyst — ask a real question and it answers.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Heading({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="label hairline-b"
      style={{ margin: 'var(--s-5) 0 var(--s-3)', paddingBottom: 'var(--s-1)', color: 'var(--ink-dim)' }}
    >
      {children}
    </div>
  )
}

function Row({
  code, title, hint, aliases, onOpen,
}: { code: string; title: string; hint: string; aliases?: string[]; onOpen: () => void }) {
  return (
    <>
      <button
        className="num lift"
        title="open it here"
        onClick={onOpen}
        style={{
          fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)',
          border: '1px solid var(--hairline-bright)', borderRadius: 3,
          padding: '0 var(--s-2)', minWidth: 26, textAlign: 'center',
        }}
      >
        {code}
      </button>
      <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink-dim)', paddingBottom: 'var(--s-1)' }}>
        <span style={{ color: 'var(--ink)' }}>{title}</span>
        <span className="label" style={{ marginLeft: 'var(--s-2)', color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0 }}>
          {hint}
        </span>
        {aliases && aliases.length > 0 && (
          <span className="label" style={{ marginLeft: 'var(--s-2)', color: 'var(--ink-ghost)' }}>
            · also {aliases.join(', ')}
          </span>
        )}
      </div>
    </>
  )
}
