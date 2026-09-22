// Spec: Genesis Markdown/10-Architecture/Biological Design.md §The map
//
// `BIO` — the organism as a top-down tree: Genesis → the loop → each organ,
// with a line on what it can do today and the notes that specify it inside.
//
// Every node comes from `/v1/biology`, which parses the note's own table. There
// is no organ list in this file. Add a row to the note and the tree grows; that
// is the point of reading the body map instead of keeping a copy of it.
//
// Two kinds of status, kept visibly apart:
//   build  ○ ◐ ●  the vault's `status:` on each linked note, rolled up
//   live   ━ ╌ ✕ ?  the store's health, for the six organs that report one
// A built organ can be down and a spec'd one can have nothing to report. Merging
// the two into one colour would hide both of those facts.
//
// It shows. Nothing here acts, same as the body map (Fleet View §Not a control
// surface). Positions are computed, not dragged.

import { memo, useEffect, useMemo } from 'react'
import {
  Background, BackgroundVariant, Controls, Handle, Position, ReactFlow, useReactFlow,
  type Edge, type Node, type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api, type Organ, type OrganStatus } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Loading } from '@/components/States'
import { HEALTH_COLOR, HEALTH_GLYPH } from '@/components/SystemHealth'
import { ago } from '@/lib/format'
import { useGenesis } from '@/store/useGenesis'
import type { HealthState, SystemHealth } from '@/types/fleet'

/** The note's own order: "perception, memory, rhythm, reflex, action and homeostasis", then judgement. */
const LOOP_ORDER = ['perception', 'memory', 'rhythm', 'reflex', 'action', 'homeostasis', 'judgement']

/**
 * The organs the store has a live health reading for. The pairing is the one
 * `SystemHealth.ORGANS` already draws in the status row. `voice` is the
 * listening loop, so it lights Hearing.
 */
const LIVE: Partial<Record<string, keyof SystemHealth>> = {
  'Heartbeat': 'daemon',
  'Long-term memory': 'memory',
  'Muscle memory': 'risk',
  'Hands': 'execution',
  'Senses': 'connectivity',
  'Hearing': 'voice',
}

export const STATUS_GLYPH: Record<OrganStatus, string> = {
  built: '●', building: '◐', spec: '○', missing: '✕', 'n/a': '·',
}
const STATUS_COLOR: Record<OrganStatus, string> = {
  built: 'var(--verdict-pass)',
  building: 'var(--state-blocked)',
  spec: 'var(--ink-ghost)',
  missing: 'var(--state-down)',
  'n/a': 'var(--ink-faint)',
}

/** Same rule as `genesis.biology.rollup` — the parent is only as built as its children. */
function rollup(s: OrganStatus[]): OrganStatus {
  const c = s.filter((x) => x !== 'n/a')
  if (!c.length) return 'n/a'
  if (c.every((x) => x === 'built')) return 'built'
  if (c.every((x) => x === 'spec' || x === 'missing')) return 'spec'
  return 'building'
}

const W = 236
const STAGE_GAP = 34
const INDENT = 22
const ROOT_Y = 0
const STAGE_Y = 120
const ORGAN_Y = 232
const ORGAN_GAP = 14
/** Summary lines at ~31 characters each — the card's text width at `--fs-micro`. Estimated so layout needs no DOM measure. */
const summaryHeight = (o: Organ) => (o.summary ? Math.ceil(o.summary.length / 31) * 15 + 2 : 0)
const organHeight = (o: Organ) => 78 + summaryHeight(o) + o.parts.length * 19

// -- nodes ------------------------------------------------------------------

type RootData = { organs: number; built: number; status: OrganStatus }
type StageData = { loop: string; count: number; status: OrganStatus }
type OrganData = { organ: Organ; live: HealthState | null }
type BioNode = Node<RootData, 'root'> | Node<StageData, 'stage'> | Node<OrganData, 'organ'>

function StatusTag({ status }: { status: OrganStatus }) {
  return (
    <span className="num" style={{ color: STATUS_COLOR[status], fontSize: 'var(--fs-micro)', whiteSpace: 'nowrap' }}>
      {STATUS_GLYPH[status]} {status}
    </span>
  )
}

const box = (status: OrganStatus) => ({
  background: 'var(--bg-panel)',
  borderRadius: 'var(--r-md)',
  border: `1px ${status === 'spec' ? 'dashed' : 'solid'} ${status === 'missing' ? STATUS_COLOR.missing : 'var(--hairline-bright)'}`,
})

const RootNode = memo(function RootNode({ data }: NodeProps<Node<RootData, 'root'>>) {
  return (
    <div style={{ ...box(data.status), width: W + 40, padding: '10px 12px', borderColor: 'var(--core)', textAlign: 'center' }}>
      <div style={{ fontSize: 'var(--fs-base)', color: 'var(--ink)' }}>🧬 Genesis</div>
      <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', marginTop: 2 }}>
        {data.built} of {data.organs} organs built · <StatusTag status={data.status} />
      </div>
      <Handle type="source" position={Position.Bottom} isConnectable={false} style={{ opacity: 0 }} />
    </div>
  )
})

const StageNode = memo(function StageNode({ data }: NodeProps<Node<StageData, 'stage'>>) {
  return (
    <div style={{ ...box(data.status), width: W, padding: '7px 10px', background: 'var(--bg-raised)' }}>
      <Handle type="target" position={Position.Top} isConnectable={false} style={{ opacity: 0 }} />
      <div className="flex items-baseline gap-2">
        <span className="label" style={{ color: 'var(--ink)', fontSize: 'var(--fs-tiny)' }}>{data.loop}</span>
        <span className="num" style={{ color: 'var(--ink-ghost)', fontSize: 'var(--fs-micro)' }}>{data.count}</span>
        <span className="ml-auto"><StatusTag status={data.status} /></span>
      </div>
      {/* The spine the organs hang off runs down the left edge. */}
      <Handle type="source" position={Position.Bottom} isConnectable={false} style={{ opacity: 0, left: 10 }} />
    </div>
  )
})

const OrganNode = memo(function OrganNode({ data }: NodeProps<Node<OrganData, 'organ'>>) {
  const { organ: o, live } = data
  return (
    <div style={{ ...box(o.status), width: W - INDENT, padding: '7px 9px', overflow: 'hidden' }}>
      <Handle type="target" position={Position.Left} isConnectable={false} style={{ opacity: 0 }} />
      <div className="flex items-center gap-[6px]">
        <span style={{ width: 3, height: 13, background: STATUS_COLOR[o.status], flexShrink: 0 }} />
        <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)' }}>{o.organ}</span>
        {o.phase1 && (
          <span className="label" style={{ color: 'var(--ink-faint)' }} title="A bold row in the note: built in Phase 1">P1</span>
        )}
        <span className="ml-auto"><StatusTag status={o.status} /></span>
      </div>
      <div
        title={o.genesis}
        style={{
          fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', margin: '3px 0 5px', lineHeight: 1.3,
          height: 28, overflow: 'hidden',
        }}
      >
        {o.genesis}
      </div>
      {o.summary && (
        <div
          style={{
            fontSize: 'var(--fs-micro)', color: 'var(--ink-dim)', lineHeight: 1.35,
            minHeight: summaryHeight(o), marginBottom: 4,
            borderLeft: `2px solid ${STATUS_COLOR[o.status]}`, paddingLeft: 6,
          }}
        >
          {o.summary}
        </div>
      )}
      {live && (
        <div className="flex items-center gap-[6px]" style={{ fontSize: 'var(--fs-micro)', marginBottom: 3 }}>
          <span className="label">live</span>
          <span className="num" style={{ color: HEALTH_COLOR[live] }}>{HEALTH_GLYPH[live]} {live}</span>
        </div>
      )}
      {o.parts.map((p) => (
        <div
          key={p.name}
          title={p.path ?? 'no note by this name: the map links to something that does not exist'}
          className="flex items-center gap-[6px]"
          style={{ fontSize: 'var(--fs-micro)', height: 19 }}
        >
          <span className="num" style={{ color: STATUS_COLOR[p.status], width: 10 }}>{STATUS_GLYPH[p.status]}</span>
          <span style={{ color: 'var(--ink-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {p.name}
          </span>
        </div>
      ))}
    </div>
  )
})

const nodeTypes = { root: RootNode, stage: StageNode, organ: OrganNode }

// -- layout -----------------------------------------------------------------

/** Deterministic: stages in loop order across, organs stacked under each. No solver. */
function layout(organs: Organ[], health: SystemHealth, connected: boolean) {
  const loops = [...new Set(organs.map((o) => o.loop))].sort((a, b) => {
    const ia = LOOP_ORDER.indexOf(a), ib = LOOP_ORDER.indexOf(b)
    // A loop value the note gains later still gets drawn, after the known ones.
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.localeCompare(b)
  })
  const width = loops.length * W + (loops.length - 1) * STAGE_GAP
  const nodes: BioNode[] = [{
    id: 'root', type: 'root', position: { x: width / 2 - (W + 40) / 2, y: ROOT_Y },
    data: {
      organs: organs.length,
      built: organs.filter((o) => o.status === 'built').length,
      status: rollup(organs.map((o) => o.status)),
    },
  }]
  const edges: Edge[] = []
  const edge = (source: string, target: string): Edge => ({
    id: `${source}>${target}`, source, target, type: 'smoothstep', selectable: false,
    style: { stroke: 'var(--hairline-bright)', strokeWidth: 1.2 },
  })

  loops.forEach((loop, i) => {
    const x = i * (W + STAGE_GAP)
    const members = organs.filter((o) => o.loop === loop)
    const sid = `stage:${loop}`
    nodes.push({
      id: sid, type: 'stage', position: { x, y: STAGE_Y },
      data: { loop, count: members.length, status: rollup(members.map((o) => o.status)) },
    })
    edges.push(edge('root', sid))
    let y = ORGAN_Y
    for (const o of members) {
      const oid = `organ:${o.organ}`
      const key = LIVE[o.organ]
      nodes.push({
        id: oid, type: 'organ', position: { x: x + INDENT, y },
        data: { organ: o, live: key ? (connected ? health[key] : 'unknown') : null },
      })
      edges.push(edge(sid, oid))
      y += organHeight(o) + ORGAN_GAP
    }
  })
  return { nodes, edges }
}

// -- view -------------------------------------------------------------------

export function Biology() {
  const { state, reload, fetchedAt } = useRead(() => api.biology(), [])
  const health = useGenesis((s) => s.health)
  const connected = useGenesis((s) => s.connection.status === 'open')
  const { fitView } = useReactFlow()

  const organs = state.status === 'ready' ? state.data.organs : null
  const graph = useMemo(
    () => (organs ? layout(organs, health, connected) : null),
    [organs, health, connected],
  )

  // Frame once per fetch, never on a health tick: a health change must not undo a pan.
  useEffect(() => {
    if (!organs) return
    const t = setTimeout(() => fitView({ padding: 0.08, maxZoom: 1, duration: 280 }), 60)
    return () => clearTimeout(t)
  }, [organs, fitView])

  if (state.status === 'loading') return <Loading rows={6} label="reading the body map" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  return (
    <div className="relative h-full w-full">
      <ReactFlow<BioNode>
        nodes={graph!.nodes}
        edges={graph!.edges}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
        minZoom={0.2}
        maxZoom={2}
      >
        <Background variant={BackgroundVariant.Dots} gap={26} size={1} color="var(--hairline)" />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>

      <div className="absolute panel" style={{ right: 10, top: 10, padding: '6px 8px', width: 220, backdropFilter: 'blur(6px)' }}>
        <div className="label" style={{ marginBottom: 3 }}>build — from the vault</div>
        <div className="flex flex-wrap" style={{ gap: '1px 10px' }}>
          {(['built', 'building', 'spec', 'missing'] as OrganStatus[]).map((s) => <StatusTag key={s} status={s} />)}
        </div>
        <div className="label" style={{ margin: '6px 0 3px' }}>live — from the daemon</div>
        <div className="flex flex-wrap" style={{ gap: '1px 10px' }}>
          {(['ok', 'degraded', 'down', 'unknown'] as HealthState[]).map((h) => (
            <span key={h} className="num" style={{ color: HEALTH_COLOR[h], fontSize: 'var(--fs-micro)' }}>
              {HEALTH_GLYPH[h]} {h}
            </span>
          ))}
        </div>
        <div className="flex items-center" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)', marginTop: 6 }}>
          <span title={state.data.source}>read {fetchedAt ? ago(fetchedAt) : ''}</span>
          <button onClick={reload} className="ml-auto" style={{ color: 'var(--ink-dim)' }}>re-read</button>
        </div>
      </div>
    </div>
  )
}
