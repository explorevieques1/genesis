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
// Everything here is real. The series come from the bar store, the tools from
// the MCP catalogue, the agents from the discovered fleet — there are no
// placeholder entries and no "coming soon" rows.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '@/api/client'
import { useRead } from '@/api/useRead'
import { PAGES, type PageId } from './pages'
import { stagger } from '@/lib/motion'

type Kind = 'page' | 'series' | 'tool' | 'agent' | 'command'

interface Item {
  kind: Kind
  id: string
  label: string
  hint: string
  run: () => void
}

const KIND_COLOUR: Record<Kind, string> = {
  page: 'var(--core)',
  series: 'var(--family-charting)',
  tool: 'var(--family-research)',
  agent: 'var(--family-journal)',
  command: 'var(--core-flare)',
}

interface Props {
  open: boolean
  onClose: () => void
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
  }) => void
}

export function CommandBar({ open, onClose, onPage, onSymbol, onCommandResult }: Props) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const [running, setRunning] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  // Loaded only while the palette is open. A closed palette costs nothing,
  // which is the same rule the idle clock follows.
  const symbols = useRead(() => api.symbols(), [open])
  const tools = useRead(() => api.mcpTools(), [open])
  const agents = useRead(() => api.agents(), [open])

  useEffect(() => {
    if (open) {
      setQuery('')
      setCursor(0)
      // Focus after paint, or the field is not in the document yet.
      requestAnimationFrame(() => input.current?.focus())
    }
  }, [open])

  const items = useMemo<Item[]>(() => {
    const out: Item[] = PAGES.map((page) => ({
      kind: 'page' as const,
      id: `page:${page.id}`,
      label: page.label,
      hint: page.hint,
      run: () => { onPage(page.id); onClose() },
    }))

    if (symbols.state.status === 'ready') {
      for (const row of symbols.state.data.symbols) {
        out.push({
          kind: 'series',
          id: `series:${row.symbol_id}:${row.timeframe}`,
          label: `${row.symbol} ${row.timeframe}`,
          hint: `${row.bars} bars · ${row.coverage[0]?.source ?? 'unknown source'}`,
          run: () => { onSymbol(row.symbol_id, row.timeframe); onPage('charting'); onClose() },
        })
      }
    }
    if (agents.state.status === 'ready') {
      for (const agent of agents.state.data.agents) {
        out.push({
          kind: 'agent',
          id: `agent:${agent.id}`,
          label: agent.name ?? agent.id,
          hint: `${agent.family} · ${agent.reflex ? 'reflex (tier none)' : `tier ${agent.model_tier}`}`,
          run: () => { onPage('fleet'); onClose() },
        })
      }
    }
    if (tools.state.status === 'ready') {
      for (const tool of tools.state.data.tools) {
        out.push({
          kind: 'tool',
          id: `tool:${tool.id}`,
          label: tool.id,
          hint: `${tool.capability}${tool.mutating ? ' · mutates' : ''}`,
          run: () => { onPage('settings'); onClose() },
        })
      }
    }
    return out
  }, [symbols.state, tools.state, agents.state, onPage, onSymbol, onClose])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return items.filter((i) => i.kind === 'page')
    const scored = items
      .map((item) => {
        const label = item.label.toLowerCase()
        // Prefix beats substring beats hint. Crude, and right often enough
        // that a fuzzy matcher would be a dependency buying very little.
        const score = label.startsWith(needle) ? 0
          : label.includes(needle) ? 1
            : item.hint.toLowerCase().includes(needle) ? 2
              : -1
        return { item, score }
      })
      .filter((entry) => entry.score >= 0)
      .sort((a, b) => a.score - b.score)
      .slice(0, 40)
      .map((entry) => entry.item)
    return scored
  }, [items, query])

  const runCommand = useCallback(async () => {
    const text = query.trim()
    if (!text) return
    setRunning(true)
    try {
      const result = await api.command(text)
      onCommandResult({
        ok: result.ok, heard: result.heard || text,
        command: result.command, spoken: result.spoken, detail: result.detail,
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
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setCursor((c) => Math.min(c + 1, filtered.length - 1))
      } else if (event.key === 'ArrowUp') {
        event.preventDefault()
        setCursor((c) => Math.max(c - 1, 0))
      } else if (event.key === 'Enter') {
        event.preventDefault()
        // Cmd+Enter sends the text to the command layer instead of opening a
        // result. Separated so "chart AAPL" can either find the series or run
        // the command, and the person chooses which.
        if (event.metaKey || event.ctrlKey || filtered.length === 0) {
          void runCommand()
        } else {
          filtered[cursor]?.run()
        }
      }
    },
    [filtered, cursor, onClose, runCommand],
  )

  if (!open) return null

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
        style={{ width: 'min(620px, 92vw)', maxHeight: '62vh', display: 'flex', flexDirection: 'column' }}
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={input}
          value={query}
          onChange={(e) => { setQuery(e.target.value); setCursor(0) }}
          onKeyDown={onKeyDown}
          placeholder="search, or type a command and press ⌘↵"
          style={{
            background: 'transparent', border: 0, outline: 'none',
            padding: '10px 12px', fontSize: 'var(--fs-base)', color: 'var(--ink)',
            borderBottom: '1px solid var(--hairline)',
          }}
        />

        <div className="scroll-y" style={{ flex: 1 }}>
          {filtered.length === 0 ? (
            <div style={{ padding: '10px 12px', fontSize: 'var(--fs-tiny)', color: 'var(--ink-faint)' }}>
              {running
                ? 'running…'
                : query.trim()
                  ? <>nothing matches. <span style={{ color: 'var(--ink-dim)' }}>⌘↵</span> sends “{query.trim()}” to the command layer — the same path voice uses.</>
                  : 'type to search'}
            </div>
          ) : (
            filtered.map((item, index) => (
              <button
                key={item.id}
                className="row-hit lift flex items-center gap-2 w-full"
                data-selected={index === cursor}
                style={{ ['--i' as string]: stagger(index, 12), padding: '5px 12px', textAlign: 'left' }}
                onMouseEnter={() => setCursor(index)}
                onClick={item.run}
              >
                <span
                  aria-hidden
                  style={{
                    width: 5, height: 5, borderRadius: 1, flexShrink: 0,
                    background: KIND_COLOUR[item.kind],
                  }}
                />
                <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)', flexShrink: 0 }}>
                  {item.label}
                </span>
                <span
                  className="label"
                  style={{
                    color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}
                >
                  {item.hint}
                </span>
                <span style={{ flex: 1 }} />
                <span className="label" style={{ color: 'var(--ink-ghost)' }}>{item.kind}</span>
              </button>
            ))
          )}
        </div>

        <div
          className="label hairline-t"
          style={{ padding: '4px 12px', color: 'var(--ink-ghost)', display: 'flex', gap: 12 }}
        >
          <span>↑↓ move</span>
          <span>↵ open</span>
          <span>⌘↵ run as command</span>
          <span>esc close</span>
        </div>
      </div>
    </div>
  )
}
