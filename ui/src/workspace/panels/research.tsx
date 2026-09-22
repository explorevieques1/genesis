// Spec: Genesis Markdown/20-Agents/Research/Research Family.md · 60-UI/Workspaces.md
//
// The research directory: what the agents found, and its receipts.
//
// This is a *directory*, not a feed. Research Family says a subject deepens one
// note rather than scattering four, so the listing shows the current version of
// each subject and the reader offers its history — the same shape the store
// enforces underneath. A list that showed every version would read as
// duplicated work rather than as revision.
//
// Two things are always on screen next to a claim, because a research note
// without them is indistinguishable from the model's own memory:
//
//   - **its sources**, clickable, with a marker on any page that attempted a
//     prompt injection. The page's text was fenced and its instructions were
//     not followed, and saying so is more useful than silently dropping it.
//   - **its age against its half-life**. Research Family downweights rather
//     than deletes, so a stale note is shown, labelled stale, not hidden.

import { useMemo, useState, type ReactNode } from 'react'
import { api } from '@/api/client'
import { useRead } from '@/api/useRead'
import { useCapability } from '@/api/capabilities'
import { Absent, Empty, Loading, RequiresCapability } from '@/components/States'
import { Caveats, Chip, PanelBody, Table } from '@/components/Primitives'
import { useWorkspace } from '@/workspace/context'

const KINDS = ['all', 'topic', 'regime', 'idea', 'symbol', 'finding'] as const

/** Family tokens, so a research note and a research agent are the same colour. */
const KIND_TONE: Record<string, string> = {
  topic: 'var(--family-research)',
  regime: 'var(--family-charting)',
  idea: 'var(--core)',
  symbol: 'var(--family-journal)',
  // Written by the orchestrator's runner, not by a research agent.
  finding: 'var(--family-core)',
}

function ago(iso: string): string {
  const hours = (Date.now() - new Date(iso).getTime()) / 3.6e6
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))}m`
  if (hours < 48) return `${Math.round(hours)}h`
  return `${Math.round(hours / 24)}d`
}

// ---------------------------------------------------------------------------

export function ResearchDirectoryPanel() {
  const capability = useCapability('research.directory')
  return (
    <RequiresCapability capability={capability}>{() => <Directory />}</RequiresCapability>
  )
}

function Directory() {
  const { nodeId, select } = useWorkspace()
  const [kind, setKind] = useState<(typeof KINDS)[number]>('all')
  const [query, setQuery] = useState('')
  // Debounced only by the fact that the query is applied on submit rather than
  // on every keystroke — the search runs FTS over the whole directory, and a
  // request per character is a request per character.
  const [applied, setApplied] = useState('')
  const { state, reload } = useRead(
    () => api.researchNotes({ kind: kind === 'all' ? undefined : kind, q: applied || undefined }),
    [kind, applied],
  )

  const header = (
    <div className="flex items-center gap-2 hairline-b" style={{ padding: '4px 8px', flexShrink: 0 }}>
      <input
        className="field"
        placeholder="search the directory"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') setApplied(query.trim()) }}
        style={{ flex: 1, minWidth: 90 }}
      />
      {KINDS.map((k) => (
        <button
          key={k}
          className="btn-ghost"
          data-selected={k === kind}
          style={{ color: k === kind ? 'var(--ink)' : undefined }}
          onClick={() => setKind(k)}
        >
          {k}
        </button>
      ))}
    </div>
  )

  let body: ReactNode
  if (state.status === 'loading') body = <Loading rows={5} label="research" />
  else if (state.status !== 'ready') body = <Absent reason={state.reason} onRetry={reload} />
  else if (!state.data.notes.length) {
    body = (
      <Empty hint={
        applied || kind !== 'all'
          ? 'Nothing saved matches that. The directory only ever holds what an agent actually wrote.'
          : 'Ask Genesis to research something — “research W.D. Gann’s methods” — and the note it writes lands here, with its sources.'
      }>
        {applied ? 'no matches' : 'nothing researched yet'}
      </Empty>
    )
  } else {
    body = (
      <PanelBody pad={0}>
        <Table
          rows={state.data.notes}
          keyOf={(row) => String(row.id)}
          selectedKey={nodeId ?? undefined}
          onSelect={(row) => select({ nodeId: String(row.id) })}
          columns={[
            {
              key: 'kind', header: '', width: 14,
              render: (row) => (
                <span
                  aria-hidden
                  title={String(row.kind)}
                  style={{
                    display: 'inline-block', width: 5, height: 5, borderRadius: 1,
                    background: KIND_TONE[String(row.kind)] ?? 'var(--ink-faint)',
                  }}
                />
              ),
            },
            {
              key: 'title', header: 'note',
              render: (row) => (
                <span style={{ color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {String(row.title)}
                </span>
              ),
            },
            {
              key: 'by', header: 'agent', width: 108,
              render: (row) => <span className="label">{String(row.created_by)}</span>,
            },
            {
              key: 'state', header: '', width: 82, align: 'right',
              render: (row) => (
                <span className="flex items-center gap-1" style={{ justifyContent: 'flex-end' }}>
                  {row.degraded ? <Chip tone="warn">degraded</Chip> : null}
                  {row.stale ? <Chip tone="neutral">stale</Chip> : null}
                </span>
              ),
            },
            {
              key: 'age', header: 'age', width: 40, align: 'right',
              render: (row) => <span className="num">{ago(String(row.created))}</span>,
            },
          ]}
        />
      </PanelBody>
    )
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {header}
      <div className="scroll-y" style={{ flex: 1, minHeight: 0 }}>{body}</div>
    </div>
  )
}

// ---------------------------------------------------------------------------

export function ResearchNotePanel() {
  const capability = useCapability('research.directory')
  return (
    <RequiresCapability capability={capability}>{() => <Note />}</RequiresCapability>
  )
}

function Note() {
  const { nodeId } = useWorkspace()
  const { state, reload } = useRead(
    () => (nodeId ? api.researchNote(nodeId) : Promise.resolve({ available: false, reason: 'nothing selected' } as never)),
    [nodeId],
  )

  if (!nodeId) {
    return <Empty hint="The directory is to the left. Everything an agent wrote is readable in full, with the pages it read.">no note selected</Empty>
  }
  if (state.status === 'loading') return <Loading rows={6} label="note" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  const note = state.data.note
  const sources = (note.sources ?? []) as Record<string, unknown>[]
  const caveats = (note.caveats ?? []) as string[]

  return (
    <PanelBody>
      <div className="flex items-baseline gap-2" style={{ flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 'var(--fs-lg)', color: 'var(--ink)', margin: 0 }}>
          {String(note.title)}
        </h2>
        <Chip tone="neutral">{String(note.kind)}</Chip>
        {note.degraded ? <Chip tone="warn">degraded</Chip> : null}
        {note.stale ? <Chip tone="neutral">past its half-life</Chip> : null}
      </div>

      <div className="label" style={{ marginTop: 4, color: 'var(--ink-faint)' }}>
        {String(note.created_by)} · {ago(String(note.created))} ago ·
        {' '}confidence {(Number(note.confidence) * 100).toFixed(0)}%
        {' '}· carries {(Number(note.weight) * 100).toFixed(0)}% of that weight today
        {' '}· {String(note.vault_path)}
      </div>

      {note.summary ? (
        <p style={{ marginTop: 12, color: 'var(--ink)' }}>{String(note.summary)}</p>
      ) : null}

      {caveats.length > 0 ? (
        <div style={{ marginTop: 12 }}>
          <Caveats items={caveats} tone={note.degraded ? 'warn' : 'info'} />
        </div>
      ) : null}

      <div style={{ marginTop: 16 }}>
        <Markdown text={String(note.body ?? '')} />
      </div>

      {sources.length > 0 ? (
        <div style={{ marginTop: 20 }}>
          <div className="label hairline-b" style={{ paddingBottom: 4 }}>
            sources · {sources.length}
          </div>
          {sources.map((source, i) => (
            <div key={i} style={{ padding: '6px 0' }}>
              <a
                href={String(source.url)}
                target="_blank"
                rel="noreferrer noopener"
                style={{ color: 'var(--core)', fontSize: 'var(--fs-sm)' }}
              >
                {String(source.title || source.url)}
              </a>
              {Array.isArray(source.flags) && source.flags.length > 0 ? (
                <span style={{ marginLeft: 6 }}>
                  <Chip tone="warn">flagged · nothing it said was acted on</Chip>
                </span>
              ) : null}
              {source.excerpt ? (
                <div className="label" style={{ color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0 }}>
                  {String(source.excerpt)}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </PanelBody>
  )
}

// ---------------------------------------------------------------------------
// A markdown subset, rendered as React elements.
//
// Deliberately not a library and deliberately not `dangerouslySetInnerHTML`.
// The text in a research note was written by a model that had just read pages
// written by strangers, which makes it the single worst string in this app to
// hand to an HTML parser. Elements cannot inject; a sanitiser can be wrong.
//
// Headings, lists, quotes, bold, inline code and links are what the agents
// actually emit. Anything else renders as its own literal text, which is the
// correct failure: visible and harmless.

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|<https?:\/\/[^>]+>)/g

function inline(text: string, keyBase: string): ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((part, i) => {
    const key = `${keyBase}:${i}`
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={key} style={{ color: 'var(--ink)' }}>{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={key} className="num" style={{ color: 'var(--ink)' }}>{part.slice(1, -1)}</code>
    }
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part)
    // Only http(s). A `javascript:` href in agent-written text is exactly the
    // thing this renderer exists to not evaluate.
    if (link && /^https?:\/\//.test(link[2])) {
      return (
        <a key={key} href={link[2]} target="_blank" rel="noreferrer noopener" style={{ color: 'var(--core)' }}>
          {link[1]}
        </a>
      )
    }
    const bare = /^<(https?:\/\/[^>]+)>$/.exec(part)
    if (bare) {
      return (
        <a key={key} href={bare[1]} target="_blank" rel="noreferrer noopener" style={{ color: 'var(--core)' }}>
          {bare[1]}
        </a>
      )
    }
    return <span key={key}>{part}</span>
  })
}

export function Markdown({ text }: { text: string }) {
  const blocks = useMemo(() => text.split('\n'), [text])
  const out: ReactNode[] = []
  let list: ReactNode[] = []

  const flush = () => {
    if (!list.length) return
    out.push(<ul key={`ul:${out.length}`} style={{ margin: '6px 0 6px 18px', listStyle: 'disc' }}>{list}</ul>)
    list = []
  }

  blocks.forEach((line, i) => {
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line)
    if (bullet) {
      list.push(<li key={`li:${i}`} style={{ marginBottom: 2 }}>{inline(bullet[1], `li${i}`)}</li>)
      return
    }
    flush()
    if (heading) {
      const level = heading[1].length
      out.push(
        <div
          key={`h:${i}`}
          style={{
            marginTop: 16, marginBottom: 4, color: 'var(--ink)',
            fontSize: level <= 2 ? 'var(--fs-base)' : 'var(--fs-sm)',
            fontWeight: 600,
          }}
        >
          {inline(heading[2], `h${i}`)}
        </div>,
      )
      return
    }
    if (line.startsWith('>')) {
      out.push(
        <blockquote
          key={`q:${i}`}
          style={{
            borderLeft: '2px solid var(--hairline-bright)', paddingLeft: 10,
            margin: '6px 0', color: 'var(--ink-dim)',
          }}
        >
          {inline(line.replace(/^>\s?/, ''), `q${i}`)}
        </blockquote>,
      )
      return
    }
    if (line.trim()) {
      out.push(
        <p key={`p:${i}`} style={{ margin: '6px 0', color: 'var(--ink-dim)', lineHeight: 1.55 }}>
          {inline(line, `p${i}`)}
        </p>,
      )
    }
  })
  flush()
  return <div style={{ fontSize: 'var(--fs-sm)' }}>{out}</div>
}
