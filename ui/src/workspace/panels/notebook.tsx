// Spec: Genesis Markdown/60-UI/Notebook.md
//
// `NOT` — Obsidian, inside Genesis.
//
// A vault of markdown files with a folder tree down the side, `[[wikilinks]]`
// in the body, and a note that does not exist yet created by clicking the link
// to it. That last one is not a nicety: it is the authoring loop. You write the
// link you wish existed, then click it into being.
//
// **There is no database behind this panel.** A vault is a directory; the tree
// is one level of `os.walk` per request and the note is a file. Which means the
// notes the research family writes into `memory.vault_path` are simply *here*,
// with no import step, and an edit made in Obsidian appears on the next read.
// It also means every read is cheap and nothing needs cache invalidation.
//
// The renderer is deliberately small — headings, lists, quotes, code, bold,
// inline code and links. It builds React elements, never HTML, so a note
// containing a `<script>` tag is text and cannot be anything else. A markdown
// library would be a dependency for the ninety percent of syntax nobody puts in
// a trading note.
//
// ponytail: tables, images, embeds-rendered-inline and callouts are not
// rendered — an embed shows as a link chip. Add a markdown library if a note
// ever needs a table; the seam is `render()` and nothing else changes.

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import {
  api, TransportError,
  type NotebookEntry, type NotebookLink, type VaultRef,
} from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { useWorkspace } from '@/workspace/context'
import { revealPanel } from '@/workspace/dock'

// ---------------------------------------------------------------------------
// the panel
// ---------------------------------------------------------------------------

export function NotebookPanel() {
  const { notePath, select } = useWorkspace()
  const vaults = useRead(() => api.vaults(), [])
  // Bumped by every write. The tree and the editor both watch it, which is how
  // creating a note from a link makes it appear in the sidebar without either
  // one knowing the other exists.
  const [version, setVersion] = useState(0)
  const changed = useCallback(() => setVersion((v) => v + 1), [])

  if (vaults.state.status === 'loading') return <Loading rows={4} label="vault" />
  if (vaults.state.status !== 'ready') {
    return <Absent reason={vaults.state.reason} onRetry={vaults.reload} />
  }

  const { vaults: list, active } = vaults.state.data

  return (
    <div className="flex flex-col h-full min-h-0" data-focus-scope="true">
      <div className="flex min-h-0" style={{ flex: 1 }}>
        <Sidebar
          version={version}
          selected={notePath}
          onOpen={(path) => select({ notePath: path })}
          onChange={changed}
          vaults={list}
          active={active}
          onVaultChange={() => { vaults.reload(); changed() }}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          {notePath
            ? <Editor path={notePath} version={version} onChange={changed} />
            : (
              <Empty hint="Pick a note on the left, or make one with +. Links you write as [[this]] become notes when you click them.">
                nothing open
              </Empty>
            )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// vaults
// ---------------------------------------------------------------------------

function VaultBar({ vaults, active, onChange }: {
  vaults: VaultRef[]
  active: string
  onChange: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const current = vaults.find((v) => v.name === active)

  async function act(fn: () => Promise<unknown>) {
    setErr(null)
    try {
      await fn()
      onChange()
    } catch (e) {
      setErr(e instanceof TransportError ? e.message : String(e))
    }
  }

  return (
    <div className="flex flex-col hairline-t" style={{ flexShrink: 0 }}>
      <div className="flex items-center gap-1" style={{ padding: '4px 6px' }}>
        <select
          className="field"
          value={active}
          style={{ flex: 1, minWidth: 0 }}
          onChange={(e) => act(() => api.vaultSelect(e.target.value))}
        >
          {vaults.map((v) => (
            <option key={v.name} value={v.name}>{v.name}{v.exists ? '' : ' (missing)'}</option>
          ))}
        </select>
        <button className="btn-ghost" title="open another vault" onClick={() => setAdding((a) => !a)}>
          +
        </button>
        <span style={{ flex: 1 }} />
        <span className="label" title={current?.path} style={{ color: 'var(--ink-ghost)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {current?.path}
        </span>
      </div>
      {adding && (
        <form
          className="flex items-center gap-1"
          style={{ padding: '0 6px 4px' }}
          onSubmit={(e) => {
            e.preventDefault()
            const form = e.currentTarget as HTMLFormElement
            const name = (form.elements.namedItem('name') as HTMLInputElement).value.trim()
            const path = (form.elements.namedItem('path') as HTMLInputElement).value.trim()
            if (!name || !path) return
            act(() => api.vaultAdd(name, path)).then(() => setAdding(false))
          }}
        >
          <input className="field" name="name" placeholder="name" autoFocus style={{ width: 110 }} />
          <input className="field" name="path" placeholder="~/path/to/vault" spellCheck={false} style={{ flex: 1 }} />
          <button className="btn-ghost" type="submit">open</button>
        </form>
      )}
      {err && <div className="label" style={{ padding: '0 8px 4px', color: 'var(--warn)' }}>{err}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// the tree
// ---------------------------------------------------------------------------

function Sidebar({ version, selected, onOpen, onChange, vaults, active, onVaultChange }: {
  version: number
  selected: string | null
  onOpen: (path: string) => void
  onChange: () => void
  vaults: VaultRef[]
  active: string
  onVaultChange: () => void
}) {
  const [query, setQuery] = useState('')
  const search = useRead(
    () => api.notebookSearch(query),
    // Searching on every keystroke would be a full-vault scan per character.
    [query.trim().length >= 2 ? query.trim() : ''],
  )
  const searching = query.trim().length >= 2

  return (
    <div
      className="flex flex-col min-h-0 hairline-r"
      style={{ width: 220, flexShrink: 0 }}
    >
      <NewRow path="" pad={6} onOpen={onOpen} onChange={onChange} />
      <div className="flex items-center gap-1" style={{ padding: '4px 6px', flexShrink: 0 }}>
        <input
          className="field"
          placeholder="search notes"
          value={query}
          spellCheck={false}
          onChange={(e) => setQuery(e.target.value)}
          style={{ flex: 1, minWidth: 0 }}
        />
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
      {searching ? (
        <div style={{ padding: '0 4px 6px' }}>
          {search.state.status === 'ready' ? (
            search.state.data.results.length ? search.state.data.results.map((r) => (
              <button
                key={r.path}
                className="btn-ghost"
                style={{ display: 'block', width: '100%', textAlign: 'left' }}
                onClick={() => onOpen(r.path)}
                title={r.path}
              >
                <span style={{ display: 'block' }}>{r.name}</span>
                <span className="label" style={{ color: 'var(--ink-ghost)' }}>{r.excerpt}</span>
              </button>
            )) : <div className="label" style={{ padding: 6, color: 'var(--ink-ghost)' }}>no match</div>
          ) : <div className="label" style={{ padding: 6, color: 'var(--ink-ghost)' }}>searching…</div>}
        </div>
      ) : (
        <Folder
          path=""
          depth={0}
          version={version}
          selected={selected}
          onOpen={onOpen}
          onChange={onChange}
        />
      )}
      </div>
      <VaultBar vaults={vaults} active={active} onChange={onVaultChange} />
    </div>
  )
}

function Folder({ path, depth, version, selected, onOpen, onChange }: {
  path: string
  depth: number
  version: number
  selected: string | null
  onOpen: (path: string) => void
  onChange: () => void
}) {
  // One request per open folder, not one per vault. A vault with four thousand
  // notes must not cost four thousand rows to draw six.
  const { state, reload } = useRead(() => api.notebookTree(path), [path, version])
  const [open, setOpen] = useState<Set<string>>(new Set())

  if (state.status === 'loading') return <div className="label" style={{ padding: 6 }}>…</div>
  if (state.status !== 'ready') {
    return depth === 0 ? <Absent reason={state.reason} onRetry={reload} /> : null
  }

  const pad = 6 + depth * 10

  return (
    <div>
      {state.data.entries.map((entry) => (
        <Row
          key={entry.path}
          entry={entry}
          pad={pad}
          selected={selected}
          onChange={onChange}
          expanded={open.has(entry.path)}
          onToggle={() => setOpen((prev) => {
            const next = new Set(prev)
            if (next.has(entry.path)) next.delete(entry.path)
            else next.add(entry.path)
            return next
          })}
          onOpen={onOpen}
        >
          {open.has(entry.path) && (
            <Folder
              path={entry.path} depth={depth + 1} version={version}
              selected={selected} onOpen={onOpen} onChange={onChange}
            />
          )}
        </Row>
      ))}

      {depth > 0 && <NewRow path={path} pad={pad} onOpen={onOpen} onChange={onChange} />}
    </div>
  )
}

// The vault root's copy lives above the search box; nested folders carry their
// own. `onChange` bumps the version every Folder reads on, so the tree redraws
// itself without this knowing which one to tell.
function NewRow({ path, pad, onOpen, onChange }: {
  path: string
  pad: number
  onOpen: (path: string) => void
  onChange: () => void
}) {
  const [creating, setCreating] = useState<'note' | 'folder' | null>(null)

  async function make(name: string, kind: 'note' | 'folder') {
    const target = path ? `${path}/${name}` : name
    try {
      if (kind === 'folder') await api.notebookFolder(target)
      else {
        const note = await api.notebookCreate(`${target}.md`, `# ${name}\n\n`)
        onOpen(note.note.path)
      }
      onChange()
    } catch { /* the reload shows what actually happened */ }
    setCreating(null)
  }

  if (creating) {
    return (
      <input
        className="field"
        autoFocus
        placeholder={creating === 'note' ? 'note name' : 'folder name'}
        style={{ margin: `2px 6px 2px ${pad}px`, width: `calc(100% - ${pad + 12}px)`, flexShrink: 0 }}
        onBlur={() => setCreating(null)}
        onKeyDown={(e) => {
          const value = (e.target as HTMLInputElement).value.trim()
          if (e.key === 'Enter' && value) make(value, creating)
          if (e.key === 'Escape') setCreating(null)
        }}
      />
    )
  }
  return (
    <div className="flex gap-1" style={{ paddingLeft: pad, flexShrink: 0 }}>
      <button className="btn-ghost" title="new note here" onClick={() => setCreating('note')}>+ note</button>
      <button className="btn-ghost" title="new folder here" onClick={() => setCreating('folder')}>+ folder</button>
    </div>
  )
}

function Row({ entry, pad, selected, expanded, onToggle, onOpen, onChange, children }: {
  entry: NotebookEntry
  pad: number
  selected: string | null
  expanded: boolean
  onToggle: () => void
  onOpen: (path: string) => void
  onChange: () => void
  children: ReactNode
}) {
  const { select } = useWorkspace()
  const isFolder = entry.kind === 'folder'
  const active = entry.path === selected
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const [renaming, setRenaming] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const folder = entry.path.includes('/')
    ? entry.path.slice(0, entry.path.lastIndexOf('/') + 1)
    : ''

  async function rename(next: string) {
    setRenaming(false)
    if (!next || next === entry.name) return
    // A note's name is its stem; a folder's and an attachment's is the whole name.
    const to = `${folder}${next}${entry.kind === 'note' ? '.md' : ''}`
    try {
      if (entry.kind === 'note') {
        // Shown before it happens — same rule as the editor's rename.
        const preview = await api.notebookRenamePreview(entry.path, to)
        const count = preview.available ? preview.changes.reduce((n, c) => n + c.count, 0) : 0
        if (count && !window.confirm(
          `Renaming updates ${count} link${count > 1 ? 's' : ''} in ` +
          `${preview.available ? preview.changes.length : 0} note(s). Continue?`,
        )) return
      }
      const moved = await api.notebookRename(entry.path, to, entry.kind === 'note')
      onChange()
      if (selected === entry.path) select({ notePath: moved.path })
    } catch (e) {
      setErr(e instanceof TransportError ? e.message : String(e))
    }
  }

  async function remove() {
    setMenu(null)
    if (!window.confirm(`Delete ${entry.name}?`)) return
    try {
      await api.notebookDelete(entry.path)
      onChange()
      if (selected === entry.path) select({ notePath: null })
    } catch (e) {
      // An in-place message, because the vault refuses a non-empty folder and
      // the operator needs to be told which one and why.
      setErr(e instanceof TransportError ? e.message : String(e))
    }
  }

  return (
    <div>
      {renaming ? (
        <input
          className="field"
          autoFocus
          defaultValue={entry.name}
          spellCheck={false}
          style={{ margin: `2px 6px 2px ${pad}px`, width: `calc(100% - ${pad + 12}px)` }}
          onBlur={() => setRenaming(false)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setRenaming(false)
            if (e.key === 'Enter') void rename((e.target as HTMLInputElement).value.trim())
          }}
        />
      ) : (
        <button
          className="btn-ghost"
          data-selected={active}
          disabled={entry.kind === 'attachment'}
          title={entry.path}
          style={{
            display: 'block', width: '100%', textAlign: 'left', paddingLeft: pad,
            color: active ? 'var(--ink)' : entry.kind === 'attachment' ? 'var(--ink-ghost)' : undefined,
          }}
          onClick={() => (isFolder ? onToggle() : onOpen(entry.path))}
          onContextMenu={(e) => { e.preventDefault(); setErr(null); setMenu({ x: e.clientX, y: e.clientY }) }}
        >
          {isFolder ? (expanded ? '▾ ' : '▸ ') : ''}{entry.name}
        </button>
      )}

      {err && (
        <div className="label" style={{ paddingLeft: pad, color: 'var(--warn)' }}>{err}</div>
      )}

      {menu && (
        <>
          <div
            style={{ position: 'fixed', inset: 0, zIndex: 40 }}
            onClick={() => setMenu(null)}
            onContextMenu={(e) => { e.preventDefault(); setMenu(null) }}
          />
          <div
            className="flex flex-col"
            style={{
              position: 'fixed', left: menu.x, top: menu.y, zIndex: 41,
              minWidth: 120, padding: 2, border: '1px solid var(--hairline)',
              background: 'var(--bg-raised)',
            }}
          >
            <button
              className="btn-ghost"
              style={{ textAlign: 'left' }}
              onClick={() => { setMenu(null); setRenaming(true) }}
            >
              rename
            </button>
            <button className="btn-ghost" style={{ textAlign: 'left' }} onClick={remove}>
              delete
            </button>
          </div>
        </>
      )}

      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// the editor
// ---------------------------------------------------------------------------

function Editor({ path, version, onChange }: {
  path: string
  version: number
  onChange: () => void
}) {
  const { state, reload } = useRead(() => api.notebookNote(path), [path, version])
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [ambiguous, setAmbiguous] = useState<NotebookLink | null>(null)
  const [renaming, setRenaming] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const { select } = useWorkspace()
  const dirty = draft !== null && draft !== saved

  // A new note replaces the draft. Keyed on `path` only: a `version` bump from
  // a write elsewhere must not throw away what is being typed here.
  useEffect(() => { setDraft(null); setSaved(null); setEditing(false); setErr(null) }, [path])

  useEffect(() => {
    if (state.status === 'ready' && draft === null) {
      setDraft(state.data.note.body)
      setSaved(state.data.note.body)
    }
  }, [state, draft])

  const save = useCallback(async (body: string) => {
    try {
      await api.notebookSave(path, body)
      setSaved(body)
      setErr(null)
      onChange()
    } catch (e) {
      setErr(e instanceof TransportError ? e.message : String(e))
    }
  }, [path, onChange])

  // Autosave, debounced. Obsidian saves as you type and so does this: a
  // notebook that can lose a paragraph to a closed panel is one nobody trusts
  // enough to think in. ⌘S is still there for the reflex.
  const pending = useRef<number | null>(null)
  useEffect(() => {
    if (!dirty || draft === null) return
    if (pending.current) window.clearTimeout(pending.current)
    pending.current = window.setTimeout(() => void save(draft), 800)
    return () => { if (pending.current) window.clearTimeout(pending.current) }
  }, [draft, dirty, save])

  const open = useCallback(async (link: NotebookLink, from: string) => {
    if (link.candidates.length > 1) { setAmbiguous(link); return }
    if (link.resolved) { select({ notePath: link.resolved }); return }
    // The authoring loop: an unresolved link becomes a note, in the folder of
    // the note that asked for it — which is what Obsidian does.
    const folder = from.includes('/') ? from.slice(0, from.lastIndexOf('/') + 1) : ''
    try {
      const made = await api.notebookCreate(
        `${folder}${link.target}.md`, `# ${link.target}\n\n`,
      )
      onChange()
      select({ notePath: made.note.path })
    } catch (e) {
      setErr(e instanceof TransportError ? e.message : String(e))
    }
  }, [onChange, select])

  if (state.status === 'loading') return <Loading rows={5} label="note" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  const { note, links, backlinks } = state.data

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 hairline-b" style={{ padding: '3px 8px', flexShrink: 0 }}>
        {renaming ? (
          <input
            className="field" autoFocus defaultValue={note.name} style={{ flex: 1 }}
            onBlur={() => setRenaming(false)}
            onKeyDown={async (e) => {
              if (e.key === 'Escape') setRenaming(false)
              if (e.key !== 'Enter') return
              const next = (e.target as HTMLInputElement).value.trim()
              if (!next || next === note.name) { setRenaming(false); return }
              const folder = path.includes('/') ? path.slice(0, path.lastIndexOf('/') + 1) : ''
              const to = `${folder}${next}.md`
              try {
                // Shown before it happens. A bulk edit of the operator's own
                // prose must never be a surprise.
                const preview = await api.notebookRenamePreview(path, to)
                const count = preview.available ? preview.changes.reduce((n, c) => n + c.count, 0) : 0
                if (count && !window.confirm(
                  `Renaming updates ${count} link${count > 1 ? 's' : ''} in ` +
                  `${preview.available ? preview.changes.length : 0} note(s). Continue?`,
                )) { setRenaming(false); return }
                const moved = await api.notebookRename(path, to)
                onChange()
                select({ notePath: moved.path })
              } catch (e2) {
                setErr(e2 instanceof TransportError ? e2.message : String(e2))
              }
              setRenaming(false)
            }}
          />
        ) : (
          <button className="btn-ghost" style={{ flex: 1, textAlign: 'left' }} title={path} onClick={() => setRenaming(true)}>
            {note.name}
          </button>
        )}
        <span className="label" style={{ color: dirty ? 'var(--warn)' : 'var(--ink-ghost)' }}>
          {dirty ? 'unsaved' : 'saved'}
        </span>
        <button className="btn-ghost" onClick={() => setEditing((e) => !e)}>
          {editing ? 'read' : 'edit'}
        </button>
        <button className="btn-ghost" title="show this note in the graph" onClick={() => {
          select({ notePath: path })
          revealPanel('notebook-graph', { title: 'Nodes' })
        }}>
          graph
        </button>
        <button className="btn-ghost" title="delete this note" onClick={async () => {
          if (!window.confirm(`Delete ${note.name}?`)) return
          try {
            await api.notebookDelete(path)
            onChange()
            select({ notePath: null })
          } catch (e) {
            setErr(e instanceof TransportError ? e.message : String(e))
          }
        }}>
          ×
        </button>
      </div>

      {err && <div className="label" style={{ padding: '3px 8px', color: 'var(--warn)' }}>{err}</div>}

      {ambiguous && (
        <div className="flex items-center gap-2 hairline-b" style={{ padding: '3px 8px', flexWrap: 'wrap' }}>
          <span className="label">[[{ambiguous.target}]] could be:</span>
          {ambiguous.candidates.map((c) => (
            <button key={c} className="btn-ghost" onClick={() => { setAmbiguous(null); select({ notePath: c }) }}>
              {c}
            </button>
          ))}
          <button className="btn-ghost" onClick={() => setAmbiguous(null)}>×</button>
        </div>
      )}

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {editing ? (
          <textarea
            className="field"
            value={draft ?? ''}
            spellCheck={false}
            autoFocus
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => { if (dirty && draft !== null) void save(draft) }}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 's') {
                e.preventDefault()
                if (draft !== null) void save(draft)
              }
            }}
            style={{
              width: '100%', height: '100%', resize: 'none', border: 'none',
              borderRadius: 0, padding: 10, lineHeight: 1.55,
              fontFamily: 'var(--font-mono, monospace)',
            }}
          />
        ) : (
          <div style={{ padding: 10, lineHeight: 1.55 }}>
            {render(saved ?? note.body, links, (link) => void open(link, path))}
          </div>
        )}
      </div>

      <div className="hairline-t" style={{ padding: '4px 8px', flexShrink: 0, maxHeight: 140, overflow: 'auto' }}>
        <span className="label" style={{ color: 'var(--ink-ghost)' }}>
          {backlinks.length} backlink{backlinks.length === 1 ? '' : 's'}
        </span>
        {backlinks.map((b) => (
          <button
            key={b.path}
            className="btn-ghost"
            style={{ display: 'block', width: '100%', textAlign: 'left' }}
            onClick={() => select({ notePath: b.path })}
          >
            <span style={{ display: 'block' }}>{b.name}</span>
            <span className="label" style={{ color: 'var(--ink-ghost)' }}>{b.context}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// rendering
// ---------------------------------------------------------------------------

/** `[[Target#anchor|alias]]`, `**bold**`, `` `code` `` — in one pass. */
const INLINE = /(!?\[\[[^\]]+\]\])|(\*\*[^*]+\*\*)|(`[^`]+`)/g
const LINK = /^(!)?\[\[([^\]|#^]*)([#^][^\]|]*)?(?:\|([^\]]*))?\]\]$/

function inline(
  text: string,
  links: NotebookLink[],
  onOpen: (link: NotebookLink) => void,
  key: string,
): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let i = 0
  for (const match of text.matchAll(INLINE)) {
    const at = match.index ?? 0
    if (at > last) out.push(text.slice(last, at))
    const token = match[0]
    last = at + token.length
    const wiki = LINK.exec(token)
    if (wiki) {
      const target = wiki[2].trim()
      // Matched against the resolutions the daemon computed, never re-resolved
      // here — the browser has no idea what files exist, and a second
      // resolution rule is a second set of bugs.
      const link = links.find((l) => l.target === target) ?? {
        target, anchor: '', alias: '', embed: false, start: 0, end: 0,
        resolved: null, candidates: [],
      }
      const label = (wiki[4] ?? '').trim() || target + (wiki[3] ?? '')
      out.push(
        <button
          key={`${key}-${i++}`}
          className="btn-ghost"
          title={link.resolved ?? `${target} — not created yet. Click to make it.`}
          onClick={() => onOpen(link)}
          style={{
            padding: 0, display: 'inline', color: link.resolved ? 'var(--core)' : 'var(--ink-faint)',
            textDecoration: link.resolved ? 'none' : 'underline dotted',
          }}
        >
          {wiki[1] ? '⧉ ' : ''}{label}
        </button>,
      )
    } else if (token.startsWith('**')) {
      out.push(<strong key={`${key}-${i++}`}>{token.slice(2, -2)}</strong>)
    } else {
      out.push(<code key={`${key}-${i++}`}>{token.slice(1, -1)}</code>)
    }
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

/**
 * Markdown to React elements. Never to HTML.
 *
 * Building elements rather than a string means a note containing `<script>` is
 * text by construction — there is no sanitiser to get wrong, because there is
 * nothing to sanitise.
 */
function render(
  body: string,
  links: NotebookLink[],
  onOpen: (link: NotebookLink) => void,
): ReactNode[] {
  const out: ReactNode[] = []
  const lines = body.split('\n')
  let fence: string[] | null = null

  lines.forEach((line, n) => {
    if (line.trimStart().startsWith('```')) {
      if (fence) {
        out.push(<pre key={n} style={{ overflowX: 'auto', margin: '6px 0' }}><code>{fence.join('\n')}</code></pre>)
        fence = null
      } else fence = []
      return
    }
    if (fence) { fence.push(line); return }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    if (heading) {
      const level = heading[1].length
      out.push(
        <div key={n} style={{
          fontWeight: 600, marginTop: level === 1 ? 0 : 10, marginBottom: 3,
          fontSize: `calc(var(--fs-body) * ${1.35 - level * 0.06})`,
        }}>
          {inline(heading[2], links, onOpen, String(n))}
        </div>,
      )
      return
    }
    const item = /^\s*[-*+]\s+(.*)$/.exec(line)
    if (item) {
      out.push(<div key={n} style={{ paddingLeft: 14, textIndent: -8 }}>· {inline(item[1], links, onOpen, String(n))}</div>)
      return
    }
    const quote = /^\s*>\s?(.*)$/.exec(line)
    if (quote) {
      out.push(
        <div key={n} style={{ paddingLeft: 8, borderLeft: '2px solid var(--ink-ghost)', color: 'var(--ink-faint)' }}>
          {inline(quote[1], links, onOpen, String(n))}
        </div>,
      )
      return
    }
    if (!line.trim()) { out.push(<div key={n} style={{ height: 8 }} />); return }
    out.push(<div key={n}>{inline(line, links, onOpen, String(n))}</div>)
  })

  if (fence) out.push(<pre key="tail"><code>{(fence as string[]).join('\n')}</code></pre>)
  return out
}
