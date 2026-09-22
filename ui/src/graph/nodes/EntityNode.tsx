// Spec: Genesis Markdown/60-UI/Research Canvas.md · 40-Memory/Knowledge Graph.md
//
// One node on the research canvas: a knowledge-graph entity.
//
// The node shows the entity's **type** as loudly as its label, because the type
// is what makes the graph answerable rather than merely connected. A canvas of
// forty identical boxes is a picture; a canvas where a thesis, the documents it
// derives from and the symbol it applies to are visibly different things is a
// thing you can read.
//
// A node with a `ref` is openable — that is the "open research results and view
// its findings" half. A node without one is a real node with nothing to open
// yet (a symbol, say), and it says so by not offering the affordance rather
// than by offering one that does nothing.

import { memo } from 'react'
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react'
import type { GraphEntity } from '@/api/client'

export interface EntityNodeData extends Record<string, unknown> {
  entity: GraphEntity
  selected: boolean
  /** Placed by an agent rather than by the person looking at it. */
  byAgent: boolean
  pinned: boolean
}

export type EntityFlowNode = Node<EntityNodeData, 'entity'>

/**
 * Colour by entity type, from the family tokens.
 *
 * Research-family colour for the things research produces, charting colour for
 * price objects, journal colour for things learned from your own history. The
 * canvas is not its own visual world — a `lesson` here is the same colour as a
 * lesson in the journal graph.
 */
export const TYPE_COLOUR: Record<string, string> = {
  thesis: 'var(--family-research)',
  idea: 'var(--core)',
  document: 'var(--ink-faint)',
  symbol: 'var(--family-charting)',
  level: 'var(--family-charting)',
  regime: 'var(--family-strategy, var(--family-charting))',
  setup: 'var(--family-strategy, var(--core))',
  strategy: 'var(--family-strategy, var(--core))',
  lesson: 'var(--family-journal)',
  trade: 'var(--family-journal)',
  catalyst: 'var(--state-degraded)',
  belief: 'var(--core-flare)',
}

export const EntityNode = memo(function EntityNode({ data }: NodeProps<EntityFlowNode>) {
  const { entity, selected, byAgent, pinned } = data
  const accent = TYPE_COLOUR[entity.type] ?? 'var(--ink-faint)'
  const degraded = Boolean((entity.data as { degraded?: boolean })?.degraded)

  return (
    <div
      style={{
        minWidth: 132, maxWidth: 232,
        background: 'var(--bg-panel)',
        border: `1px solid ${selected ? 'var(--core-hot)' : 'var(--hairline)'}`,
        borderLeft: `3px solid ${accent}`,
        borderRadius: 3,
        padding: '6px 8px',
        boxShadow: selected ? 'var(--shadow-lg)' : 'none',
      }}
    >
      {/* Both sides connectable: an edge on this canvas is a claim, and a claim
          can point either way depending on which node you started from. */}
      <Handle type="target" position={Position.Left} style={{ opacity: 0.35 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0.35 }} />

      <div className="flex items-center gap-1" style={{ marginBottom: 2 }}>
        <span className="label" style={{ color: accent }}>{entity.type}</span>
        {pinned ? <span className="label" style={{ color: 'var(--ink-ghost)' }}>pinned</span> : null}
        {byAgent ? <span className="label" style={{ color: 'var(--ink-ghost)' }}>· agent</span> : null}
        {degraded ? <span className="label" style={{ color: 'var(--state-degraded)' }}>· degraded</span> : null}
      </div>

      <div
        style={{
          fontSize: 'var(--fs-sm)', color: 'var(--ink)', lineHeight: 1.3,
          overflow: 'hidden', display: '-webkit-box',
          WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
        }}
      >
        {entity.label}
      </div>

      {entity.ref ? (
        <div
          className="label"
          style={{
            color: 'var(--ink-ghost)', marginTop: 3, textTransform: 'none',
            letterSpacing: 0, overflow: 'hidden', textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {entity.ref.startsWith('http') ? new URL(entity.ref).hostname : entity.ref}
        </div>
      ) : null}
    </div>
  )
})
