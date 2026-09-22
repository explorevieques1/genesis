// Spec: Genesis Markdown/60-UI/Feed.md
//
// `FD` — what the automations have produced, newest first. One row per run that
// left something durable: a note, a news brief, a journal observation, an alert.
// Click the artifact and it opens where it lives — `NOT` for a note, `NW` for a
// brief — because the feed is a way in, not a second copy of the text.
//
// It never opens itself. A scheduled job is not a request, and `Operating Model`
// §3 only lets Genesis put a panel on screen while answering one. The job leaves
// the artifact; the trader comes looking.
//
// Runs that produced nothing are not here — a gate that correctly stopped a
// chain is run history (`CD`), not news. Tier none: this reads a log.

import { useCallback } from 'react'
import { api, type FeedArtifact, type FeedItem } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { Chip } from '@/components/Primitives'
import { revealPanel } from '@/workspace/dock'
import { useWorkspace } from '@/workspace/context'

const KIND_LABEL: Record<string, string> = {
  note: 'note', brief: 'brief', observation: 'journalled',
}

function when(at: string) {
  const then = new Date(at)
  const mins = Math.round((Date.now() - then.getTime()) / 60000)
  if (mins < 60) return `${Math.max(0, mins)}m ago`
  if (mins < 24 * 60) return `${Math.round(mins / 60)}h ago`
  return then.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

export function FeedPanel() {
  const { state, reload, fetchedAt } = useRead(() => api.automationFeed(50), [])
  const { select } = useWorkspace()

  const open = useCallback((artifact: FeedArtifact) => {
    if (artifact.kind === 'note') {
      select({ notePath: artifact.target })
      revealPanel('notebook')
    } else if (artifact.kind === 'brief') {
      revealPanel('news', { params: { brief: artifact.target } })
    } else {
      revealPanel('journal-entries')
    }
  }, [select])

  const body = state.status === 'ready' ? state.data : null

  return (
    <div className="flex flex-col h-full min-h-0" style={{ fontSize: 'var(--fs-sm)' }}>
      <div className="flex items-center gap-2 hairline-b" style={{ padding: '4px 8px', flexShrink: 0 }}>
        <span className="label" style={{ color: 'var(--ink-dim)' }}>
          {body ? `${body.items.length} produced` : 'feed'}
        </span>
        {!!body?.new && <Chip tone="core" title={`Produced in the last ${body.new_hours}h`}>{body.new} NEW</Chip>}
        <span style={{ flex: 1 }} />
        <button type="button" className="btn-ghost" onClick={reload}>refresh</button>
      </div>

      {state.status === 'loading' ? <Loading rows={5} label="what has run" />
        : state.status !== 'ready' || !body ? <Absent reason={state.reason ?? 'no data'} onRetry={reload} />
          : body.items.length === 0
            ? (
              <Empty hint="An automation that writes a note, a brief or an observation shows up here. Workflow builder → templates → Daily movers.">
                nothing produced yet
              </Empty>
            )
            : (
              <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
                {body.items.map((item) => <Row key={item.id} item={item} onOpen={open} />)}
              </div>
            )}

      <div className="flex items-center gap-2 hairline-t" style={{ padding: '4px 8px', flexShrink: 0 }}>
        <span className="label" style={{ color: 'var(--ink-faint)' }}>
          derived from the run log — nothing here is a second copy
        </span>
        <span className="label" style={{ marginLeft: 'auto', color: 'var(--ink-ghost)' }}>
          {fetchedAt ? `read ${new Date(fetchedAt).toLocaleTimeString()}` : ''}
        </span>
      </div>
    </div>
  )
}

function Row({ item, onOpen }: { item: FeedItem; onOpen: (a: FeedArtifact) => void }) {
  const failed = item.status === 'failed'
  return (
    <article className="hairline-b" style={{ padding: '6px 8px' }}>
      <div className="flex items-baseline gap-2">
        {item.new && <span style={{ color: 'var(--accent)', fontSize: 'var(--fs-tiny)' }}>●</span>}
        <span style={{ fontWeight: 600, color: 'var(--ink)' }}>{item.title}</span>
        {failed && <Chip tone="warn" title="The run failed partway — what it did produce is below">PARTIAL</Chip>}
        <span className="label" style={{ marginLeft: 'auto', color: 'var(--ink-ghost)', whiteSpace: 'nowrap' }}>
          {when(item.at)}
        </span>
      </div>
      <div className="label" style={{ color: 'var(--ink-faint)', marginTop: 1 }}>{item.workflow.name}</div>
      {item.summary && (
        <p style={{
          margin: '4px 0 0', color: 'var(--ink-dim)', fontSize: 'var(--fs-tiny)',
          whiteSpace: 'pre-wrap', maxHeight: '5.5em', overflow: 'hidden',
        }}>{item.summary}</p>
      )}
      <div className="flex items-center gap-1" style={{ marginTop: 4, flexWrap: 'wrap' }}>
        {item.artifacts.map((a) => (
          <button key={`${a.kind}:${a.target}`} type="button" className="btn-ghost"
            title={`Open in ${a.module === 'notebook' ? 'NOT' : a.module === 'news' ? 'NW' : 'JE'}: ${a.target}`}
            onClick={() => onOpen(a)}>
            {KIND_LABEL[a.kind] ?? a.kind} · {a.label.length > 40 ? `${a.label.slice(0, 39)}…` : a.label}
          </button>
        ))}
      </div>
    </article>
  )
}
