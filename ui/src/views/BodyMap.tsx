// Spec: Genesis Markdown/60-UI/Fleet View.md
//
// The main screen: Genesis at the centre, the five families as orbital bands,
// the MCP surface outside them and the memory fabric below.
//
// Fleet View §Not a control surface — this canvas SHOWS. There is no start, stop
// or restart reachable from here, and adding one would be a spec violation rather
// than a feature: an accidental drag that stops the risk engine's upstream feed is
// a class of mistake the surface should be incapable of.
//
// Nodes are not draggable for the same reason positions are cached — the
// operator's spatial memory of where the execution family sits is worth more than
// the ability to rearrange it.

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background, BackgroundVariant, Controls, ReactFlow, useReactFlow,
  type NodeMouseHandler,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useGenesis } from '@/store/useGenesis'
import { useFleetGraph, type FleetNode } from '@/graph/useFleetGraph'
import type { LayoutMode } from '@/graph/layout'
import { AgentNode } from '@/graph/nodes/AgentNode'
import { CoreNode } from '@/graph/nodes/CoreNode'
import { McpNode, MemoryNode, SpinalNode } from '@/graph/nodes/SystemNode'
import { FleetEdge, StructureEdge } from '@/graph/edges/FleetEdges'
import { FAMILIES, FAMILY_ORDER } from '@/data/roster'
import { Chip } from '@/components/EventStream'

const nodeTypes = {
  agent: AgentNode,
  core: CoreNode,
  spinal: SpinalNode,
  mcp: McpNode,
  memory: MemoryNode,
}
const edgeTypes = { fleet: FleetEdge, structure: StructureEdge }

export const BodyMap = memo(function BodyMap({ now }: { now: number }) {
  const [mode, setMode] = useState<LayoutMode>('organism')
  const [showMcp, setShowMcp] = useState(true)
  const [showMemory, setShowMemory] = useState(true)
  const [showStructure, setShowStructure] = useState(true)

  const filters = useGenesis((s) => s.filters)
  const setFilter = useGenesis((s) => s.setFilter)
  const toggleCollapsed = useGenesis((s) => s.toggleCollapsed)
  const toggleEdgeKind = useGenesis((s) => s.toggleEdgeKind)
  const select = useGenesis((s) => s.select)
  const clearSelection = useGenesis((s) => s.clearSelection)
  const selection = useGenesis((s) => s.selection)

  const { nodes, edges, layoutSig } = useFleetGraph({ mode, showMcp, showMemory, showStructure, now })

  // The default frame is the ORGANISM, not the whole canvas. Fitting the MCP
  // columns and the memory row too would shrink the fleet to unreadable — the
  // senses and the stores are deliberately just off-frame, one pan away.
  const organismFrame = useMemo(
    () => nodes.filter((n) => n.type !== 'mcp' && n.type !== 'memory').map((n) => ({ id: n.id })),
    [nodes],
  )

  const onNodeClick = useCallback<NodeMouseHandler<FleetNode>>((_, node) => {
    // Selection is inspection, never actuation. The only thing a click does is
    // focus the surface and populate the inspector.
    if (node.type === 'agent' || node.type === 'spinal') select({ agentId: node.id, traceId: null })
  }, [select])

  return (
    <div className="relative h-full w-full">
      <ReactFlow<FleetNode>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={onNodeClick}
        onPaneClick={clearSelection}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        proOptions={{ hideAttribution: true }}
        minZoom={0.12}
        maxZoom={2.2}
        defaultViewport={{ x: 0, y: 0, zoom: 0.62 }}
      >
        <Background variant={BackgroundVariant.Dots} gap={26} size={1} color="var(--hairline)" />
        <Controls showInteractive={false} position="bottom-right" />
        <FitToTopology layoutSig={layoutSig} frame={organismFrame} />
      </ReactFlow>

      {/* --- controls: filtering, collapsing, focus ------------------------ */}
      <div
        className="absolute panel"
        style={{ left: 10, top: 10, padding: 8, width: 232, backdropFilter: 'blur(6px)' }}
      >
        <input
          value={filters.query}
          onChange={(e) => setFilter({ query: e.target.value })}
          placeholder="search agents, tasks, families…"
          style={{
            width: '100%', background: 'var(--bg-inset)', border: '1px solid var(--hairline)',
            borderRadius: 'var(--r-sm)', padding: '3px 7px', fontSize: 'var(--fs-tiny)', outline: 'none',
          }}
        />

        <div className="label" style={{ margin: '8px 0 3px' }}>families — click to collapse</div>
        <div className="flex flex-col gap-[2px]">
          {FAMILY_ORDER.map((f) => {
            const meta = FAMILIES[f]
            const collapsed = filters.collapsedFamilies.has(f)
            return (
              <button
                key={f}
                onClick={() => toggleCollapsed(f)}
                title={meta.organ}
                className="flex items-center gap-[6px] w-full text-left"
                style={{ fontSize: 'var(--fs-micro)', opacity: collapsed ? 0.68 : 1 }}
              >
                <span style={{ width: 3, height: 11, background: `var(--family-${f})`, flexShrink: 0 }} />
                <span style={{ color: 'var(--ink-dim)' }}>{meta.label}</span>
                {meta.risk === 'red' && (
                  <span
                    className="label"
                    style={{ color: 'var(--family-execution)' }}
                    title="Touches money — Safety Invariants apply in full"
                  >
                    money
                  </span>
                )}
                <span className="ml-auto" style={{ color: 'var(--ink-ghost)' }}>
                  {collapsed ? 'hidden' : 'shown'}
                </span>
              </button>
            )
          })}
        </div>

        <div className="label" style={{ margin: '8px 0 3px' }}>edges — three real things</div>
        <div className="flex flex-col gap-[2px]">
          <EdgeLegend
            kind="lineage" on={filters.edgeKinds.has('lineage')} onClick={() => toggleEdgeKind('lineage')}
            what="a task spawned a child task on the bus"
          />
          <EdgeLegend
            kind="memory" on={filters.edgeKinds.has('memory')} onClick={() => toggleEdgeKind('memory')}
            what="one agent read what another wrote"
          />
          <EdgeLegend
            kind="event" on={filters.edgeKinds.has('event')} onClick={() => toggleEdgeKind('event')}
            what="a published event a subscriber acted on"
          />
        </div>
        <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)', marginTop: 4, lineHeight: 1.35 }}>
          Agents never call each other. There is no agent-to-agent message to draw.
        </div>

        <div className="label" style={{ margin: '8px 0 3px' }}>view</div>
        <div className="flex flex-wrap gap-1">
          <Chip on={mode === 'organism'} onClick={() => setMode('organism')} title="Radial body map — Genesis at the centre, execution innermost">organism</Chip>
          <Chip on={mode === 'layered'} onClick={() => setMode('layered')} title="elkjs layered, left-to-right — the System Overview topology">layered</Chip>
          <Chip on={showMcp} onClick={() => setShowMcp((v) => !v)} title="Senses (afferent) and hands (efferent)">mcp</Chip>
          <Chip on={showMemory} onClick={() => setShowMemory((v) => !v)}>memory</Chip>
          <Chip on={showStructure} onClick={() => setShowStructure((v) => !v)} title="The always-on topology skeleton. Off = live traffic only.">wiring</Chip>
          <Chip on={filters.activeOnly} onClick={() => setFilter({ activeOnly: !filters.activeOnly })} title="Hide agents with no telemetry — the clutter control at 30+ nodes">active only</Chip>
        </div>

        <div className="label" style={{ margin: '8px 0 3px' }}>node status</div>
        <div className="flex flex-col gap-[2px]">
          <StatusLegend color="var(--state-working)" filled text="working — lit, glowing" />
          <StatusLegend color="var(--state-idle)" filled text="idle — built, reporting in" />
          <StatusLegend color="var(--state-idle)" text="offline — built, no telemetry" />
          <StatusLegend color="var(--ink-ghost)" dashed text="spec — no module on disk yet" />
        </div>
      </div>

      {(selection.traceId || selection.agentId) && (
        <button
          onClick={clearSelection}
          className="absolute panel"
          style={{
            left: '50%', transform: 'translateX(-50%)', top: 10, padding: '3px 10px',
            fontSize: 'var(--fs-micro)', color: 'var(--core-hot)', borderColor: 'var(--core)',
          }}
        >
          {selection.traceId ? `focused on trace ${selection.traceId}` : `focused on ${selection.agentId}`} — clear
        </button>
      )}
    </div>
  )
})

function StatusLegend({
  color, filled, dashed, text,
}: { color: string; filled?: boolean; dashed?: boolean; text: string }) {
  return (
    <div className="flex items-center gap-[6px]" style={{ fontSize: 'var(--fs-micro)' }}>
      <span
        style={{
          width: 7, height: 7, borderRadius: 999, flexShrink: 0,
          background: filled ? color : 'transparent',
          border: filled ? 'none' : `1px ${dashed ? 'dashed' : 'solid'} ${color}`,
        }}
      />
      <span style={{ color: 'var(--ink-dim)' }}>{text}</span>
    </div>
  )
}

function EdgeLegend({
  kind, on, onClick, what,
}: { kind: 'lineage' | 'memory' | 'event'; on: boolean; onClick: () => void; what: string }) {
  return (
    <button
      onClick={onClick}
      title={what}
      className="flex items-center gap-[6px] w-full text-left"
      style={{ fontSize: 'var(--fs-micro)', opacity: on ? 1 : 0.62 }}
    >
      <svg width="22" height="8" style={{ flexShrink: 0 }}>
        <line
          x1="0" y1="4" x2="22" y2="4"
          stroke={`var(--edge-${kind})`}
          strokeWidth={kind === 'lineage' ? 1.8 : 1}
          strokeDasharray={kind === 'memory' ? '5 4' : kind === 'event' ? '1.5 4' : undefined}
        />
      </svg>
      <span style={{ color: 'var(--ink-dim)' }}>{kind}</span>
    </button>
  )
}

/**
 * Re-frames the viewport when the *topology* changes — a new layout mode, or the
 * first time a solver returns positions. Never on data: a viewport that re-framed
 * when a task landed would undo the operator's pan on every event, which is the
 * same failure as a graph that re-lays-out under load.
 *
 * `fitView` on the ReactFlow element itself is not enough here, because the first
 * render happens before the layout has resolved and fits an empty graph.
 */
function FitToTopology({
  layoutSig, frame,
}: { layoutSig: string; frame: { id: string }[] }) {
  const { fitView } = useReactFlow()
  // `frame` changes on every data tick, so it is read through a ref rather than
  // being a dependency — otherwise the viewport would re-fit on every event,
  // which is the same failure as a graph that re-lays-out under load.
  const frameRef = useRef(frame)
  frameRef.current = frame
  useEffect(() => {
    if (!layoutSig) return
    const t = setTimeout(
      () => fitView({ nodes: frameRef.current, padding: 0.14, maxZoom: 1.0, duration: 320 }),
      80,
    )
    return () => clearTimeout(t)
  }, [layoutSig, fitView])
  return null
}
