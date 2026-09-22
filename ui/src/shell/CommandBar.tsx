// Spec: Genesis Markdown/60-UI/Voice UX.md · 60-UI/Dashboard.md
//
// ⌘K. Pages, series, tools and agents in one list — and the typed path to the
// same command layer voice uses.
//
// The last part is the reason this exists rather than being a nav shortcut.
// `POST /v1/command` is the endpoint `TapToSpeak` posts a transcript to, so
// anything sayable is typeable. That matters for two unglamorous reasons: a
// microphone failure should never be indistinguishable from a broken command,
// and a person on a call still needs to drive the system.
//
// The catalogue itself is built in `catalogue.ts`, shared with `MAP`.
//
// Everything here is real. The series come from the bar store, the tools from
// the MCP catalogue, the agents from the discovered fleet — there are no
// placeholder entries and no "coming soon" rows.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '@/api/client'
import { PAGES, type PageId } from './pages'
import { stagger } from '@/lib/motion'
import { MODULES } from '@/workspace/modules'
import { KIND_COLOUR, useCatalogue, type Kind } from './catalogue'
import { GenesisCore } from '@/components/GenesisCore'
import { useGenesis } from '@/store/useGenesis'

/**
 * The chips under the field. Clickable, and `Tab` / `⇧Tab` cycles them, so the
 * mouse and the keyboard reach the same filters (Operating Model — parity).
 * `config` is everything that changes how Genesis behaves: the settings
 * modules, each model tier, each notebook vault.
 */
type Filter = 'all' | Kind
const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'page', label: 'Pages' },
  { id: 'module', label: 'Modules' },
  { id: 'tool', label: 'Tools' },
  { id: 'agent', label: 'Agents' },
  { id: 'series', label: 'Series' },
  { id: 'command', label: 'Commands' },
  { id: 'config', label: 'Config' },
]

/**
 * Sections under the Modules chip: one per page that is some module's home, in
 * nav order. Derived from `home`, so a new module files itself — there is no
 * second list to keep in step. `home` still only ranks; a section is a view.
 */
type Section = 'all' | PageId
const SECTIONS: { id: Section; label: string }[] = [
  { id: 'all', label: 'All sections' },
  ...PAGES.filter((p) => MODULES.some((m) => m.home === p.id)).map((p) => ({ id: p.id, label: p.label })),
]
const SECTION_LABEL = Object.fromEntries(SECTIONS.map((s) => [s.id, s.label])) as Record<Section, string>

/**
 * Literal commands, shown on the empty canvas and gone on the first keystroke.
 *
 * Operating Model §3: a blank screen with a cursor is a dead end unless typing
 * into it reveals the surface — but the operator has to know a request is even
 * the right *shape* before they can type one. These teach that shape. They hold
 * no data, occupy the input's own space, and disappear the moment there is a
 * query, so nothing unrequested is ever on screen.
 */
const EXAMPLES = [
  'research W.D. Gann and save it to my journal',
  'why is Nvidia down today',
  'chart NVDA daily',
  'what is the market doing',
  'status',
]

/** Recently opened, per viewer. A convenience, never state of record. */
const RECENT_KEY = 'genesis.recent'
const RECENT_MAX = 6

function recall(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    return raw ? (JSON.parse(raw) as string[]).slice(0, RECENT_MAX) : []
  } catch {
    // A private window, cleared site data, or a browser that throws on access.
    // An empty list renders correctly, so there is nothing to report.
    return []
  }
}

function remember(label: string) {
  try {
    const next = [label, ...recall().filter((x) => x !== label)].slice(0, RECENT_MAX)
    localStorage.setItem(RECENT_KEY, JSON.stringify(next))
  } catch { /* see recall() */ }
}

interface Props {
  open: boolean
  /**
   * The category the operator is standing in.
   *
   * Two jobs: modules whose `home` is this page sort first, and anything
   * opened lands in *this* workspace. A module is never confined to its home —
   * that is the whole of what makes a category customisable rather than a
   * fixed screen.
   */
  page: PageId
  /**
   * `overlay` is ⌘K over a working surface. `inline` is the focal element of
   * the empty canvas.
   *
   * One component, two placements — deliberately. The alternative was a second
   * search field that would drift from this one within a week, and then the
   * canvas and the palette would reach different sets of tools.
   */
  variant?: 'overlay' | 'inline'
  onClose: () => void
  /** Opens with this line typed and the Commands filter on — how `MAP` hands over a command. */
  initialQuery?: string
  onPage: (page: PageId) => void
  onSymbol: (symbolId: string, timeframe: string) => void
  /**
   * The daemon's actual answer, not just the text that was sent.
   *
   * `api.command()` already returns `{ ok, heard, command, spoken, detail }` —
   * the same envelope the voice path produces. Discarding it and reporting
   * "sent" meant a typed command was silent where the identical spoken one
   * answered out loud.
   */
  onCommandResult: (reply: {
    ok: boolean; heard: string; command: string
    spoken: string; detail?: string | null
    data?: Record<string, string> | null
  }) => void
}

export function CommandBar({
  open, page, variant = 'overlay', onClose, initialQuery = '', onPage, onSymbol, onCommandResult,
}: Props) {
  const inline = variant === 'inline'
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const [running, setRunning] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')
  const [section, setSection] = useState<Section>('all')
  const input = useRef<HTMLInputElement>(null)
  // The ambient presence — "at the centre of the idle screen" (Genesis Core
  // §What it is for). Home is the idle screen. Read unconditionally; only the
  // `inline` placement renders it.
  const coreState = useGenesis((s) => s.coreState)

  const onCommand = useCallback((text: string) => {
    setQuery(text)
    setFilter('command')
    requestAnimationFrame(() => input.current?.focus())
  }, [])

  // Loaded only while the palette is open. A closed palette costs nothing,
  // which is the same rule the idle clock follows.
  const { items } = useCatalogue(open, { page, onPage, onSymbol, onClose, onCommand })

  useEffect(() => {
    if (open) {
      setQuery(initialQuery)
      setCursor(0)
      setFilter(initialQuery ? 'command' : 'all')
      // The page you are working on, when it has modules of its own.
      setSection(SECTIONS.some((s) => s.id === page) ? page : 'all')
      // Focus after paint, or the field is not in the document yet.
      requestAnimationFrame(() => input.current?.focus())
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps -- reset on open only, not on navigation

  const counts = useMemo(() => {
    const c: Partial<Record<Filter, number>> = { all: items.length }
    for (const i of items) c[i.kind] = (c[i.kind] ?? 0) + 1
    return c
  }, [items])

  /**
   * Active search, and the rule that makes the two paths legible.
   *
   * **A match is an open. A miss is a command.** Typing `DH` lights up
   * Coverage and `↵` spawns it here, deterministically, with no model and no
   * round trip. Typing `why is Nvidia down today` matches nothing, the field
   * says so, and `↵` sends it to the command layer — the same endpoint voice
   * posts to. The operator feels the distinction as "did the list light up",
   * which needs no explaining and no mode switch.
   *
   * Scoring is ordinal and crude, and right often enough that a fuzzy matcher
   * would be a dependency buying very little:
   *
   *   0  exact short code — `CH` is the chart, always, first
   *   1  a module in this category whose name or code starts with the query
   *   2  anything else starting with the query
   *   3  a substring hit
   *   4  the description
   */
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    let pool = filter === 'all' ? items : items.filter((i) => i.kind === filter)
    if (filter === 'module') {
      pool = section === 'all'
        // Grouped by section in nav order, so the headers in the list run once each.
        ? [...pool].sort((a, b) => SECTIONS.findIndex((s) => s.id === a.home) - SECTIONS.findIndex((s) => s.id === b.home))
        : pool.filter((i) => i.home === section)
    }
    // Empty query: pages under All, otherwise the whole filtered kind — a chip
    // is a request to see that list.
    if (!needle) return filter === 'all' ? pool.filter((i) => i.kind === 'page') : pool.slice(0, 200)
    return pool
      .map((item) => {
        const exactCode = item.code?.toLowerCase() === needle
        const prefix = item.tokens.some((t) => t.startsWith(needle))
        const contains = item.tokens.some((t) => t.includes(needle))
        const score = exactCode ? 0
          : prefix ? (item.local ? 1 : 2)
            : contains ? 3
              : item.hint.toLowerCase().includes(needle) ? 4
                : -1
        return { item, score }
      })
      .filter((entry) => entry.score >= 0)
      .sort((a, b) => a.score - b.score)
      .slice(0, 40)
      .map((entry) => entry.item)
  }, [items, query, filter, section])

  const cycleFilter = useCallback((step: number) => {
    setFilter((f) => {
      const i = FILTERS.findIndex((x) => x.id === f)
      return FILTERS[(i + step + FILTERS.length) % FILTERS.length].id
    })
    setCursor(0)
  }, [])

  const cycleSection = useCallback((step: number) => {
    setSection((s) => {
      const i = SECTIONS.findIndex((x) => x.id === s)
      return SECTIONS[(i + step + SECTIONS.length) % SECTIONS.length].id
    })
    setCursor(0)
  }, [])

  const runCommand = useCallback(async () => {
    const text = query.trim()
    if (!text) return
    setRunning(true)
    try {
      const result = await api.command(text)
      onCommandResult({
        ok: result.ok, heard: result.heard || text,
        command: result.command, spoken: result.spoken, detail: result.detail,
        // Carried through, not read here: what a command's data *means* is the
        // shell's business, and a palette that knew about canvases would have
        // to learn about every future command too.
        data: (result.data ?? null) as Record<string, string> | null,
      })
      onClose()
    } catch {
      // The shell's reply strip reports failures; the palette just stops.
    } finally {
      setRunning(false)
    }
  }, [query, onCommandResult, onClose])

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key === 'Escape') { onClose(); return }
      if (event.key === 'Tab') {
        event.preventDefault()
        cycleFilter(event.shiftKey ? -1 : 1)
      } else if (filter === 'module' && event.altKey && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
        // The section chips' keyboard door — plain arrows stay with the caret.
        event.preventDefault()
        cycleSection(event.key === 'ArrowLeft' ? -1 : 1)
      } else if (event.key === 'ArrowDown') {
        event.preventDefault()
        setCursor((c) => Math.min(c + 1, filtered.length - 1))
      } else if (event.key === 'ArrowUp') {
        event.preventDefault()
        setCursor((c) => Math.max(c - 1, 0))
      } else if (event.key === 'Enter') {
        event.preventDefault()
        if (filtered[cursor]) remember(filtered[cursor].label)
        // Cmd+Enter sends the text to the command layer instead of opening a
        // result. Separated so "chart AAPL" can either find the series or run
        // the command, and the person chooses which.
        // Under Commands, a typed line that is not just a listed example is
        // meant to be sent — `↵` sends it rather than refilling the field.
        const sendTyped = filter === 'command' && query.trim() !== '' && filtered[cursor]?.label !== query.trim()
        if (event.metaKey || event.ctrlKey || filtered.length === 0 || sendTyped) {
          void runCommand()
        } else {
          filtered[cursor]?.run()
        }
      }
    },
    [filtered, cursor, onClose, runCommand, cycleFilter, cycleSection, filter, query],
  )

  const chipStyle = (active: boolean): React.CSSProperties => ({
    textTransform: 'none', letterSpacing: 0, fontSize: 'var(--fs-tiny)',
    padding: '1px var(--s-3)', borderRadius: 999,
    border: `1px solid ${active ? 'var(--core)' : 'var(--hairline)'}`,
    color: active ? 'var(--ink)' : 'var(--ink-faint)',
    background: active ? 'color-mix(in oklab, var(--core) 16%, transparent)' : 'transparent',
  })

  const sectionCounts = useMemo(() => {
    const c: Partial<Record<Section, number>> = { all: MODULES.length }
    for (const m of MODULES) c[m.home] = (c[m.home] ?? 0) + 1
    return c
  }, [])

  const sectionChips = filter === 'module' && (
    <div
      className="flex items-center hairline-b"
      style={{ gap: 'var(--s-1)', padding: 'var(--s-2) var(--s-4)', flexWrap: 'wrap' }}
    >
      {SECTIONS.map((s) => (
        <button
          key={s.id}
          className="btn-ghost"
          aria-pressed={s.id === section}
          onMouseDown={(e) => e.preventDefault() /* keep focus in the field */}
          onClick={() => { setSection(s.id); setCursor(0) }}
          style={chipStyle(s.id === section)}
        >
          {s.label}
          <span className="num" style={{ marginLeft: 6, color: 'var(--ink-ghost)' }}>{sectionCounts[s.id] ?? 0}</span>
        </button>
      ))}
    </div>
  )

  const chips = (
    <div
      className="flex items-center hairline-b"
      style={{ gap: 'var(--s-1)', padding: 'var(--s-2) var(--s-4)', flexWrap: 'wrap' }}
    >
      {FILTERS.map((f) => {
        const active = f.id === filter
        return (
          <button
            key={f.id}
            className="btn-ghost"
            aria-pressed={active}
            onMouseDown={(e) => e.preventDefault() /* keep focus in the field */}
            onClick={() => { setFilter(f.id); setCursor(0) }}
            style={chipStyle(active)}
          >
            {f.id !== 'all' && (
              <span aria-hidden style={{
                display: 'inline-block', width: 5, height: 5, borderRadius: 1, marginRight: 6,
                verticalAlign: 'middle', background: KIND_COLOUR[f.id],
              }} />
            )}
            {f.label}
            <span className="num" style={{ marginLeft: 6, color: 'var(--ink-ghost)' }}>{counts[f.id] ?? 0}</span>
          </button>
        )
      })}
    </div>
  )


  // The list itself, shared by both variants. Extracted when the canvas grew an
  // inline command line: two copies of this would be two search behaviours, and
  // the whole point of one component is that the canvas and ⌘K reach the same
  // catalogue.
  const results = filtered.length === 0 ? (
    <div style={{ padding: 'var(--s-4) var(--s-5)', fontSize: 'var(--fs-tiny)', color: 'var(--ink-faint)' }}>
      {running
        ? 'running…'
        : query.trim()
          ? <>nothing matches{filter !== 'all' ? ` in ${filter}` : ''}. <span style={{ color: 'var(--ink-dim)' }}>↵</span> sends “{query.trim()}” to the command layer — the same path voice uses.</>
          : 'type to search'}
    </div>
  ) : (
    filtered.map((item, index) => (
      <div key={item.id}>
      {/* Headers only while browsing: a query re-sorts by score, which breaks the grouping. */}
      {filter === 'module' && section === 'all' && !query.trim() && item.home !== filtered[index - 1]?.home && (
        <div className="label" style={{ padding: 'var(--s-3) var(--s-5) var(--s-1)', color: 'var(--ink-ghost)' }}>
          {SECTION_LABEL[item.home ?? 'all'] ?? item.home}
        </div>
      )}
      <button
        className="row-hit lift flex items-center gap-2 w-full"
        data-selected={index === cursor}
        style={{ ['--i' as string]: stagger(index, 12), padding: 'var(--s-3) var(--s-5)', textAlign: 'left' }}
        onMouseEnter={() => setCursor(index)}
        onClick={() => { remember(item.label); item.run() }}
      >
        <span
          aria-hidden
          style={{
            width: 5, height: 5, borderRadius: 1, flexShrink: 0,
            background: KIND_COLOUR[item.kind],
          }}
        />
        {item.code && (
          <span
            className="num"
            title="short code — type this"
            style={{
              fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)',
              border: '1px solid var(--hairline-bright)', borderRadius: 3,
              padding: '0 var(--s-2)', flexShrink: 0, minWidth: 24,
              textAlign: 'center',
            }}
          >
            {item.code}
          </span>
        )}
        <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)', flexShrink: 0 }}>
          {item.label}
        </span>
        <span
          className="label"
          style={{
            color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}
        >
          {item.hint}
        </span>
        <span style={{ flex: 1 }} />
        <span className="label" style={{ color: 'var(--ink-faint)' }}>{item.kind}</span>
      </button>
      </div>
    ))
  )

  if (!open && !inline) return null

  const field = (
    <input
      ref={input}
      value={query}
      onChange={(e) => { setQuery(e.target.value); setCursor(0) }}
      onKeyDown={onKeyDown}
      placeholder={inline
        ? 'Ask Genesis, or type a module code…'
        : 'a module code opens it here — anything else runs as a command'}
      style={{
        background: 'transparent', border: 0, outline: 'none',
        padding: inline ? 'var(--s-5) var(--s-6)' : 'var(--s-4) var(--s-5)',
        fontSize: inline ? 'var(--fs-lg)' : 'var(--fs-base)',
        color: 'var(--ink)',
      }}
    />
  )

  // ---- inline: the focal element of the empty canvas --------------------
  //
  // The results list replaces the starter content the moment there is a query,
  // so the screen is never showing both. Nothing here holds data: examples are
  // literals, recents are labels this viewer already chose.
  if (inline) {
    const recents = recall()
    return (
      <div className="flex flex-col items-center justify-center h-full" style={{ padding: '0 var(--s-6)' }}>
        <div style={{ width: 'min(640px, 100%)', display: 'flex', flexDirection: 'column' }}>
          <div style={{ alignSelf: 'center', marginBottom: 'var(--s-8)' }}>
            <GenesisCore state={coreState} size={220} />
          </div>
          <div
            className="panel"
            style={{ display: 'flex', flexDirection: 'column', boxShadow: 'var(--shadow-lg)' }}
          >
            {field}
            {chips}
            {sectionChips}
            {(query.trim() || filter !== 'all') && (
              <div className="scroll-y" style={{ maxHeight: '42vh' }}>{results}</div>
            )}
          </div>

          {!query.trim() && filter === 'all' && (
            <div className="flex flex-col" style={{ marginTop: 'var(--s-6)', gap: 'var(--s-5)' }}>
              <div className="flex flex-col" style={{ gap: 'var(--s-1)' }}>
                {EXAMPLES.map((text, i) => (
                  <button
                    key={text}
                    className="row-hit lift"
                    style={{
                      ['--i' as string]: stagger(i, 24), textAlign: 'left',
                      padding: 'var(--s-2) var(--s-4)',
                      fontSize: 'var(--fs-sm)', color: 'var(--ink-faint)',
                    }}
                    onClick={() => { setQuery(text); requestAnimationFrame(() => input.current?.focus()) }}
                  >
                    {text}
                  </button>
                ))}
              </div>

              {recents.length > 0 && (
                <div className="flex items-center gap-2" style={{ flexWrap: 'wrap', padding: '0 var(--s-4)' }}>
                  <span className="label" style={{ flexShrink: 0 }}>recent</span>
                  {recents.map((label) => (
                    <button
                      key={label}
                      className="btn-ghost"
                      style={{ textTransform: 'none', letterSpacing: 0, fontSize: 'var(--fs-tiny)' }}
                      onClick={() => { setQuery(label); requestAnimationFrame(() => input.current?.focus()) }}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}

              <div className="label" style={{ padding: '0 var(--s-4)', color: 'var(--ink-ghost)' }}>
                ↵ open · ⌘↵ run as command · tab filter · ⌘K from anywhere · CH, EV, BM…
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ---- overlay: ⌘K over a working surface -------------------------------
  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 60,
        background: 'color-mix(in oklab, var(--bg-void) 72%, transparent)',
        display: 'flex', justifyContent: 'center', alignItems: 'flex-start',
        paddingTop: '13vh',
      }}
      onClick={onClose}
    >
      <div
        className="panel anim-rise"
        style={{
          width: 'min(620px, 92vw)', maxHeight: '62vh',
          display: 'flex', flexDirection: 'column',
          // The highest thing on the surface, and until now it floated with a
          // 1px hairline and nothing else — painted on rather than above.
          boxShadow: 'var(--shadow-xl)',
          borderColor: 'var(--hairline-bright)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {field}
        {chips}
        {sectionChips}

        <div className="scroll-y" style={{ flex: 1 }}>{results}</div>

        <div
          className="label hairline-t"
          style={{ padding: 'var(--s-2) var(--s-5)', color: 'var(--ink-ghost)', display: 'flex', gap: 'var(--s-5)' }}
        >
          <span>↑↓ move</span>
          <span>⇥ filter</span>
          {filter === 'module' && <span>⌥←→ section</span>}
          <span>↵ open</span>
          <span>⌘↵ run as command</span>
          <span>esc close</span>
        </div>
      </div>
    </div>
  )
}
