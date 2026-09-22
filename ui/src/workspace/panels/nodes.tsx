// Spec: Genesis Markdown/60-UI/Nodes.md
//
// `NOD` — Obsidian's graph view, over the [[Notebook]] vault.
//
// Every note a dot, every `[[link]]` a line. **Nothing here is stored**: the
// graph is derived from the files on each read, so it is correct the instant a
// note changes — including a note changed in Obsidian rather than in `NOT`.
// There is no `nodes.db` and there must not be one; a cached link graph is a
// second truth that goes stale invisibly, because the picture still draws.
//
// The renderer is `ForceGraph`, unchanged, the same one the journal graph uses.
// A second graph library for a second graph is how a surface ends up with two
// different ideas of what a node looks like.
//
// Not built, deliberately: groups (colour-by-search), the animate time-lapse,
// arrows, and the four force sliders. Each is a preference panel over a picture
// that is already readable. Add groups first if any of them is missed.

import { useMemo, useState } from 'react'
import { api, type GraphEdge } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { ForceGraph, type GraphNodeInput } from '@/components/graph/ForceGraph'
import { useWorkspace } from '@/workspace/context'
import { revealPanel } from '@/workspace/dock'

/**
 * Colours by kind, from the family tokens.
 *
 * An unresolved link is `--ink-faint` on purpose: it is a note that does not
 * exist, and it should read as a gap in the vault rather than as a peer of the
 * notes around it.
 */
const PALETTE: Record<string, string> = {
  note: 'var(--family-journal)',
  unresolved: 'var(--ink-faint)',
  tag: 'var(--core)',
  attachment: 'var(--family-charting)',
}

export function NotebookGraphPanel() {
  const { notePath, select } = useWorkspace()
  const [tags, setTags] = useState(false)
  const [attachments, setAttachments] = useState(false)
  const [unresolved, setUnresolved] = useState(true)
  const [orphans, setOrphans] = useState(true)
  // Off by default: the global graph is the thing you open this for. Local is
  // what you switch to once you have a note in mind.
  const [local, setLocal] = useState(false)
  const [depth, setDepth] = useState(1)

  const focus = local && notePath ? notePath : ''
  const params = useMemo(() => ({
    tags: String(tags), attachments: String(attachments),
    unresolved: String(unresolved), orphans: String(orphans),
    focus, depth: String(depth),
  }), [tags, attachments, unresolved, orphans, focus, depth])

  const { state, reload } = useRead(
    () => api.notebookGraph(params),
    [params.tags, params.attachments, params.unresolved, params.orphans, params.focus, params.depth],
  )

  if (state.status === 'loading') return <Loading rows={4} label="graph" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  const { nodes, edges, notes } = state.data
  const selectedId = notePath ? `note:${notePath}` : null

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 hairline-b" style={{ padding: '4px 8px', flexShrink: 0, flexWrap: 'wrap' }}>
        <Toggle label="unresolved" on={unresolved} set={setUnresolved} />
        <Toggle label="orphans" on={orphans} set={setOrphans} />
        <Toggle label="tags" on={tags} set={setTags} />
        <Toggle label="attachments" on={attachments} set={setAttachments} />
        <Toggle label="local" on={local} set={setLocal} disabled={!notePath} />
        {local && notePath && (
          <label className="label" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            depth
            <input
              type="range" min={1} max={3} value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
              style={{ width: 56 }}
            />
            <span className="num">{depth}</span>
          </label>
        )}
        <span style={{ flex: 1 }} />
        <span className="label" style={{ color: 'var(--ink-ghost)' }}>
          {nodes.length} of {notes} notes · {edges.length} links
        </span>
      </div>

      {!nodes.length ? (
        <Empty hint="Notes appear here as soon as the vault has some. Write [[a link]] in one and a line joins them.">
          {local ? 'nothing within reach of this note' : 'the vault is empty'}
        </Empty>
      ) : (
        <div style={{ flex: 1, minHeight: 0 }}>
          <ForceGraph
            nodes={nodes as GraphNodeInput[]}
            edges={edges as GraphEdge[]}
            palette={PALETTE}
            selectedId={selectedId}
            onSelect={(id) => {
              // Only a real note opens. Clicking a tag or an unresolved link
              // filters nothing and creates nothing — it is a dot saying
              // something is missing, and acting on it belongs in `NOT` where
              // the link that asked for it is visible.
              if (!id?.startsWith('note:')) return
              select({ notePath: id.slice('note:'.length) })
              revealPanel('notebook', { title: 'Notebook' })
            }}
          />
        </div>
      )}
    </div>
  )
}

function Toggle({ label, on, set, disabled }: {
  label: string
  on: boolean
  set: (next: boolean) => void
  disabled?: boolean
}) {
  return (
    <button
      className="btn-ghost"
      data-selected={on}
      disabled={disabled}
      title={disabled ? 'open a note first' : undefined}
      style={{ color: on && !disabled ? 'var(--ink)' : 'var(--ink-ghost)' }}
      onClick={() => set(!on)}
    >
      {on ? '◉' : '○'} {label}
    </button>
  )
}
