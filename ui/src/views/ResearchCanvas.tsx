// Spec: Genesis Markdown/60-UI/Research Canvas.md
//
// The canvas: documents, filings, notes and the links between them, laid out
// spatially — with Genesis able to read and write the same object.
//
// Everything on screen is server state. There is no local node array that
// drifts from the store, and no `localStorage` layout: the note is explicit that
// a canvas only one browser can see is invisible to the agent meant to use it.
// So a drag posts a position, a drawn edge posts a claim, and the reply is the
// canvas as it now stands. That round trip is the feature, not overhead — it is
// what makes an overnight research pass able to put a node somewhere you will
// find it in the morning.
//
// React Flow, per UI Stack §5 as amended: addressable nodes with React content,
// panned and zoomed. The journal's d3-force view is a different problem (a
// thousand undifferentiated dots) with a different answer.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background, BackgroundVariant, Controls, MarkerType, MiniMap, ReactFlow,
  ReactFlowProvider, applyNodeChanges,
  type Connection, type Edge, type EdgeChange, type NodeChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api, type CanvasBody, type CanvasRow, type GraphEntity } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { Chip } from '@/components/Primitives'
import { EntityNode, TYPE_COLOUR, type EntityFlowNode } from '@/graph/nodes/EntityNode'

const nodeTypes = { entity: EntityNode }

/**
 * The edge kinds a person may draw by hand.
 *
 * A deliberate subset of the graph's vocabulary. `supersedes`, `held`/`broke`
 * and `correlates_with` are *measured* by agents from data — offering them here
 * would let a person assert by hand a fact whose whole value is that it was
 * computed. What is left is the kinds a human is actually the authority on:
 * what derives from what, what confirms or contradicts what, what a thing is
 * about.
 */
const DRAWABLE = [
  'derived_from', 'confirms', 'contradicts', 'applies_to', 'mentions',
  'invalidated_by',
] as const

/**
 * An edge's id is the claim it makes: source, kind, target.
 *
 * Split on the *last two* separators rather than the first two, because an
 * entity id is `type:key` and a key is arbitrary text — a URL with a pipe in it
 * would otherwise silently retract the wrong edge. The kind and the target are
 * both known-safe tokens, so counting from the right is the safe end.
 */
const edgeId = (source: string, kind: string, target: string) =>
  `${source}|${kind}|${target}`

function splitEdgeId(id: string): [string, string, string] {
  const last = id.lastIndexOf('|')
  const prior = id.lastIndexOf('|', last - 1)
  return [id.slice(0, prior), id.slice(prior + 1, last), id.slice(last + 1)]
}

/** Fold React Flow's `select` changes into a set of ids, or keep the set. */
function applySelect<T extends { type: string; id?: string; selected?: boolean }>(
  current: Set<string>, changes: T[],
): Set<string> {
  const selects = changes.filter((c) => c.type === 'select' && c.id)
  if (selects.length === 0) return current
  const next = new Set(current)
  for (const c of selects) {
    if (c.selected) next.add(c.id as string)
    else next.delete(c.id as string)
  }
  return next
}

export function ResearchCanvas() {
  return (
    <ReactFlowProvider>
      <Canvas />
    </ReactFlowProvider>
  )
}

function Canvas() {
  const [canvasId, setCanvasId] = useState<string | null>(null)
  const [body, setBody] = useState<CanvasBody | null>(null)
  // Selection is React Flow's, mirrored here rather than owned there: the node
  // array is derived from server state every render, so a `select` change that
  // is not applied is a selection that vanishes on the next reload.
  const [pickedNodes, setPickedNodes] = useState<Set<string>>(() => new Set())
  const [pickedEdges, setPickedEdges] = useState<Set<string>>(() => new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [linkKind, setLinkKind] = useState<string>(DRAWABLE[0])
  const [adding, setAdding] = useState(false)

  const list = useRead(() => api.canvases(), [])

  // Open the most recent canvas on first load, and only then. Opening one is a
  // read, so it costs nothing — but *creating* one is not, and a page that made
  // a canvas because you looked at it would fill the list with debris.
  useEffect(() => {
    if (canvasId || list.state.status !== 'ready') return
    const first = list.state.data.canvases[0]
    if (first) setCanvasId(first.id)
  }, [canvasId, list.state])

  const load = useCallback(async (id: string) => {
    setError(null)
    try {
      const reply = await api.canvas(id)
      setBody(reply.available === false ? null : reply.canvas)
      if (reply.available === false) setError(reply.reason)
    } catch (exc) {
      setError(String(exc))
    }
  }, [])

  useEffect(() => { if (canvasId) void load(canvasId) }, [canvasId, load])

  const nodes = useMemo<EntityFlowNode[]>(() => {
    if (!body) return []
    return body.nodes.map((n) => ({
      id: n.id,
      type: 'entity' as const,
      position: { x: n.x, y: n.y },
      selected: pickedNodes.has(n.id),
      data: {
        entity: n as GraphEntity,
        selected: pickedNodes.has(n.id),
        byAgent: n.added_by !== 'operator',
        pinned: n.pinned,
      },
    }))
  }, [body, pickedNodes])

  // An edge's identity is the claim it is — `(source, kind, target)` — which is
  // also the tuple the graph is unique on, so a React Flow id round-trips to a
  // retraction without a lookup table.
  const edges = useMemo<Edge[]>(() => (body?.edges ?? []).map((e) => {
    const id = edgeId(e.source, e.kind, e.target)
    const mine = e.namespace === 'operator'
    const picked = pickedEdges.has(id)
    return {
      id,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      selected: picked,
      // Every edge is reconnectable and deletable, including an agent's. The
      // server refuses that one *with its reason* — "topic-researcher recorded
      // that link, not you" teaches something a disabled handle does not.
      reconnectable: true,
      label: e.kind.replace(/_/g, ' '),
      // Direction is half the meaning: `derived_from` read backwards is a
      // different claim, so the arrowhead is not decoration.
      markerEnd: {
        type: MarkerType.ArrowClosed, width: 14, height: 14,
        color: picked ? 'var(--core-hot)' : mine ? 'var(--core)' : 'var(--hairline-bright)',
      },
      style: {
        stroke: picked ? 'var(--core-hot)' : mine ? 'var(--core)' : 'var(--hairline-bright)',
        strokeWidth: picked ? 2 : 1,
      },
      labelStyle: { fill: picked ? 'var(--ink)' : 'var(--ink-faint)', fontSize: 9 },
      labelBgStyle: { fill: 'var(--bg-panel)' },
    }
  }), [body, pickedEdges])

  // A drag is committed on release, not on every frame. React Flow emits a
  // change per pointer move; posting each one would be a write per pixel.
  const dragged = useRef<Map<string, { x: number; y: number }>>(new Map())
  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setBody((current) => {
      if (!current) return current
      const asFlow: EntityFlowNode[] = current.nodes.map((n) => ({
        id: n.id, type: 'entity' as const, position: { x: n.x, y: n.y },
        data: { entity: n as GraphEntity, selected: false, byAgent: false, pinned: n.pinned },
      }))
      const next = applyNodeChanges(changes, asFlow)
      const at = new Map(next.map((n) => [n.id, n.position]))
      return {
        ...current,
        nodes: current.nodes.map((n) => ({
          ...n, x: at.get(n.id)?.x ?? n.x, y: at.get(n.id)?.y ?? n.y,
        })),
      }
    })
    setPickedNodes((current) => applySelect(current, changes))
    for (const change of changes) {
      if (change.type === 'position' && change.position) {
        dragged.current.set(change.id, change.position)
        if (change.dragging === false && canvasId) {
          const at = dragged.current.get(change.id)
          dragged.current.delete(change.id)
          if (at) void api.canvasMove(canvasId, change.id, at.x, at.y).catch(() => {
            setError('the position did not save')
          })
        }
      }
    }
  }, [canvasId])

  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    setPickedEdges((current) => applySelect(current, changes))
  }, [])

  /**
   * Rubbing out a line is retracting a claim, so it goes to the graph.
   *
   * React Flow removes nothing itself: the edge disappears when the server
   * sends back a canvas without it. A refused retraction therefore leaves the
   * line exactly where it was, which is the honest outcome — the claim is still
   * recorded, so it is still drawn.
   */
  const unlink = useCallback(async (ids: string[]) => {
    if (!canvasId) return
    setBusy(true)
    setError(null)
    try {
      for (const id of ids) {
        const [source, kind, target] = splitEdgeId(id)
        const reply = await api.canvasUnlink(canvasId, source, kind, target)
        if (reply.ok) setBody(reply.canvas)
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }, [canvasId])

  const onEdgesDelete = useCallback((removed: Edge[]) => {
    void unlink(removed.map((e) => e.id))
  }, [unlink])

  /** Delete on a selected node takes it off the canvas. The graph keeps it. */
  const onNodesDelete = useCallback(async (removed: { id: string }[]) => {
    if (!canvasId || removed.length === 0) return
    try {
      const reply = await api.canvasRemove(canvasId, removed.map((n) => n.id))
      if (reply.ok) setBody(reply.canvas)
      setPickedNodes(new Set())
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    }
  }, [canvasId])

  /**
   * Dragging an edge's end onto another node moves the claim, keeping its kind.
   *
   * Retract then assert, in that order: if the retraction is refused the old
   * edge survives and no second one is invented, which is the failure mode you
   * want when the thing being edited is a record rather than a drawing.
   */
  const onReconnect = useCallback(async (previous: Edge, next: Connection) => {
    if (!canvasId || !next.source || !next.target) return
    const [source, kind, target] = splitEdgeId(previous.id)
    if (next.source === source && next.target === target) return
    setBusy(true)
    setError(null)
    try {
      await api.canvasUnlink(canvasId, source, kind, target)
      const reply = await api.canvasLink(canvasId, next.source, kind, next.target)
      if (reply.ok) setBody(reply.canvas)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
      if (canvasId) void load(canvasId)
    } finally {
      setBusy(false)
    }
  }, [canvasId, load])

  /**
   * What cannot be claimed at all, refused before the round trip.
   *
   * A self-edge is not a claim about the world, and a duplicate of a line
   * already drawn is a no-op the graph would silently swallow — better to
   * refuse the gesture than to let it look like it worked.
   */
  const isValidConnection = useCallback((c: Connection | Edge) => {
    if (!c.source || !c.target || c.source === c.target) return false
    return !(body?.edges ?? []).some(
      (e) => e.source === c.source && e.target === c.target && e.kind === linkKind,
    )
  }, [body, linkKind])

  const onConnect = useCallback(async (connection: Connection) => {
    if (!canvasId || !connection.source || !connection.target) return
    setBusy(true)
    try {
      const reply = await api.canvasLink(
        canvasId, connection.source, linkKind, connection.target,
      )
      if (reply.ok) setBody(reply.canvas)
      else setError('the link was refused')
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc))
    } finally {
      setBusy(false)
    }
  }, [canvasId, linkKind])

  const ask = useCallback(async (query: string) => {
    setBusy(true)
    setError(null)
    try {
      const reply = await api.canvasNew({ query, title: query })
      setBody(reply.canvas)
      setCanvasId(reply.canvas.id)
      list.reload()
    } catch (exc) {
      setError(String(exc))
    } finally {
      setBusy(false)
    }
  }, [list])

  // The inspector answers "what is this", so it wants exactly one thing. A
  // multi-select is for moving and deleting, and has nothing to inspect.
  const only = pickedNodes.size === 1 ? [...pickedNodes][0] : null
  const chosen = body?.nodes.find((n) => n.id === only) ?? null
  const chosenEdge = pickedEdges.size === 1 && pickedNodes.size === 0
    ? [...pickedEdges][0] : null

  return (
    <div className="flex flex-col h-full min-h-0">
      <Toolbar
        canvases={list.state.status === 'ready' ? list.state.data.canvases : []}
        graph={list.state.status === 'ready' ? list.state.data.graph : {}}
        canvasId={canvasId}
        onPick={setCanvasId}
        onAsk={ask}
        onAdd={() => setAdding((v) => !v)}
        linkKind={linkKind}
        onLinkKind={setLinkKind}
        busy={busy}
      />

      {error ? (
        <div className="label hairline-b" style={{ padding: '4px 8px', color: 'var(--state-degraded)' }}>
          {error}
        </div>
      ) : null}

      {adding && canvasId ? (
        <EntityPicker
          onClose={() => setAdding(false)}
          onAdd={async (ids) => {
            const reply = await api.canvasAdd(canvasId, ids)
            if (reply.ok) setBody(reply.canvas)
            setAdding(false)
          }}
          already={new Set((body?.nodes ?? []).map((n) => n.id))}
        />
      ) : null}

      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
          {!canvasId ? (
            <Empty hint="Ask a question above — “Gann”, a ticker, a theme — and Genesis opens a canvas from what it has actually found. Nothing appears here that no agent wrote.">
              no canvas open
            </Empty>
          ) : !body ? (
            <Loading rows={4} label="canvas" />
          ) : body.nodes.length === 0 ? (
            <Empty hint="This canvas is empty. Add nodes from the knowledge graph, or ask a question that seeds one.">
              nothing placed
            </Empty>
          ) : (
            <ReactFlow<EntityFlowNode>
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodesDelete={onNodesDelete}
              onEdgesDelete={onEdgesDelete}
              onReconnect={onReconnect}
              onConnect={onConnect}
              isValidConnection={isValidConnection}
              onPaneClick={() => { setPickedNodes(new Set()); setPickedEdges(new Set()) }}
              nodesDraggable
              nodesConnectable
              elementsSelectable
              // Shift-drag boxes a group; the whole box then drags as one and
              // each node's landing position is posted on release.
              selectionOnDrag={false}
              multiSelectionKeyCode={['Shift', 'Meta', 'Control']}
              deleteKeyCode={['Delete', 'Backspace']}
              // A grid, because a canvas two people edit needs positions that
              // agree to the pixel; 8 is small enough not to feel magnetic.
              snapToGrid
              snapGrid={[8, 8]}
              // A generous target for the end of a dragged connection: the
              // gesture that asserts a claim should not also test your aim.
              connectionRadius={34}
              connectionLineStyle={{ stroke: 'var(--core-hot)', strokeWidth: 1.5 }}
              defaultEdgeOptions={{ type: 'smoothstep' }}
              proOptions={{ hideAttribution: true }}
              minZoom={0.15}
              maxZoom={2.4}
              fitView
            >
              <Background variant={BackgroundVariant.Dots} gap={26} size={1} color="var(--hairline)" />
              <Controls showInteractive={false} position="bottom-right" />
              {/* Worth its corner only once the canvas outgrows the viewport. */}
              {body.nodes.length > 12 ? (
                <MiniMap
                  pannable
                  zoomable
                  position="bottom-left"
                  style={{ width: 132, height: 92, background: 'var(--bg-panel)' }}
                  maskColor="rgba(0,0,0,0.55)"
                  nodeColor={(n) => TYPE_COLOUR[
                    ((n as EntityFlowNode).data?.entity?.type) ?? ''
                  ] ?? 'var(--ink-faint)'}
                  nodeStrokeWidth={0}
                />
              ) : null}
            </ReactFlow>
          )}
        </div>

        {chosenEdge ? (
          <EdgeInspector
            edge={body!.edges.find(
              (e) => edgeId(e.source, e.kind, e.target) === chosenEdge,
            )!}
            label={(id) => body?.nodes.find((n) => n.id === id)?.label ?? id}
            busy={busy}
            onUnlink={() => unlink([chosenEdge])}
          />
        ) : null}

        {chosen ? (
          <Inspector
            node={chosen}
            onRemove={() => onNodesDelete([{ id: chosen.id }])}
            onExpand={async () => {
              if (!canvasId) return
              // Pull the selected node's recorded neighbours onto the canvas.
              const reply = await api.canvas(canvasId, 1)
              if (reply.available === false) return
              const here = new Set(body?.nodes.map((n) => n.id) ?? [])
              const extra = reply.canvas.nodes.filter((n) => !here.has(n.id)).map((n) => n.id)
              if (extra.length) {
                const added = await api.canvasAdd(canvasId, extra)
                if (added.ok) setBody(added.canvas)
              }
            }}
          />
        ) : null}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

function Toolbar({
  canvases, graph, canvasId, onPick, onAsk, onAdd, linkKind, onLinkKind, busy,
}: {
  canvases: CanvasRow[]
  graph: Record<string, number>
  canvasId: string | null
  onPick: (id: string) => void
  onAsk: (q: string) => void
  onAdd: () => void
  linkKind: string
  onLinkKind: (k: string) => void
  busy: boolean
}) {
  const [query, setQuery] = useState('')
  const known = Object.entries(graph).filter(([k]) => !k.startsWith('_'))
  const total = known.reduce((sum, [, n]) => sum + n, 0)

  return (
    <div className="flex flex-col hairline-b" style={{ flexShrink: 0 }}>
      <div className="flex items-center gap-2" style={{ padding: '4px 8px' }}>
        <input
          className="field"
          placeholder="open a canvas on…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && query.trim()) { onAsk(query.trim()); setQuery('') }
          }}
          style={{ flex: 1, minWidth: 120 }}
        />
        <button className="btn-ghost" disabled={busy || !query.trim()} onClick={() => { onAsk(query.trim()); setQuery('') }}>
          open
        </button>
        <button className="btn-ghost" disabled={!canvasId} onClick={onAdd}>add node</button>
        <span style={{ flex: 1 }} />
        <span className="label" style={{ color: 'var(--ink-ghost)' }}>draw as</span>
        <select
          className="field"
          value={linkKind}
          onChange={(e) => onLinkKind(e.target.value)}
          style={{ fontSize: 'var(--fs-tiny)' }}
        >
          {DRAWABLE.map((k) => <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>)}
        </select>
      </div>

      <div className="flex items-center gap-2 scroll-x" style={{ padding: '0 8px 4px' }}>
        {canvases.map((c) => (
          <button
            key={c.id}
            className="btn-ghost"
            data-selected={c.id === canvasId}
            style={{
              textTransform: 'none', letterSpacing: 0, flexShrink: 0,
              color: c.id === canvasId ? 'var(--ink)' : undefined,
            }}
            onClick={() => onPick(c.id)}
          >
            {c.title} <span className="num" style={{ color: 'var(--ink-ghost)' }}>{c.nodes}</span>
          </button>
        ))}
        <span style={{ flex: 1 }} />
        {/* What is in the graph, not on this canvas. "Nothing placed" and
            "nothing to place" are different problems. */}
        <span className="label" style={{ color: 'var(--ink-ghost)', flexShrink: 0 }}>
          graph: {total} entities · {graph._edges ?? 0} edges
        </span>
      </div>
    </div>
  )
}

function EntityPicker({
  onClose, onAdd, already,
}: {
  onClose: () => void
  onAdd: (ids: string[]) => void | Promise<void>
  already: Set<string>
}) {
  const [query, setQuery] = useState('')
  const found = useRead(() => api.canvasEntities(query), [query])

  return (
    <div className="hairline-b" style={{ padding: '4px 8px', flexShrink: 0 }}>
      <div className="flex items-center gap-2">
        <input
          className="field"
          autoFocus
          placeholder="search the knowledge graph"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ flex: 1 }}
        />
        <button className="btn-ghost" onClick={onClose}>done</button>
      </div>
      <div className="flex gap-1 scroll-x" style={{ paddingTop: 4, maxWidth: '100%' }}>
        {found.state.status === 'ready' && found.state.data.entities.length === 0 ? (
          <span className="label" style={{ color: 'var(--ink-ghost)' }}>
            nothing in the graph matches
          </span>
        ) : null}
        {found.state.status === 'ready' && found.state.data.entities.map((e) => (
          <button
            key={e.id}
            className="btn-ghost"
            disabled={already.has(e.id)}
            style={{
              textTransform: 'none', letterSpacing: 0, flexShrink: 0,
              borderLeft: `2px solid ${TYPE_COLOUR[e.type] ?? 'var(--ink-faint)'}`,
              opacity: already.has(e.id) ? 0.4 : 1,
            }}
            onClick={() => void onAdd([e.id])}
          >
            {e.label.slice(0, 42)}
          </button>
        ))}
      </div>
    </div>
  )
}

/**
 * The selected node, and the way into what it actually is.
 *
 * This panel is the "open research results and view its findings" half of the
 * feature. A node is a reference; this is where the reference is followed.
 */
function Inspector({
  node, onRemove, onExpand,
}: {
  node: CanvasBody['nodes'][number]
  onRemove: () => void | Promise<void>
  onExpand: () => void | Promise<void>
}) {
  const isNote = Boolean(node.ref && !node.ref.startsWith('http'))
  const note = useRead(
    () => (isNote ? api.researchNote(node.ref as string) : Promise.resolve({ available: false, reason: 'not a note' } as never)),
    [node.ref],
  )

  return (
    <div
      className="scroll-y"
      style={{
        width: 300, flexShrink: 0, borderLeft: '1px solid var(--hairline)',
        padding: 10, background: 'var(--bg-panel)',
      }}
    >
      <div className="flex items-center gap-1">
        <Chip tone="neutral">{node.type}</Chip>
        {node.added_by !== 'operator' ? (
          <span className="label" style={{ color: 'var(--ink-ghost)' }}>
            placed by {node.added_by}
          </span>
        ) : null}
      </div>
      <div style={{ fontSize: 'var(--fs-base)', color: 'var(--ink)', marginTop: 6 }}>
        {node.label}
      </div>

      {node.ref?.startsWith('http') ? (
        <a
          href={node.ref}
          target="_blank"
          rel="noreferrer noopener"
          className="label"
          style={{ color: 'var(--core)', textTransform: 'none', letterSpacing: 0, display: 'block', marginTop: 6 }}
        >
          {node.ref}
        </a>
      ) : null}

      {isNote ? (
        note.state.status === 'loading' ? <Loading rows={3} label="note" />
          : note.state.status === 'ready' ? (
            <div style={{ marginTop: 10 }}>
              <div className="label">what it found</div>
              <p style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink-dim)', lineHeight: 1.5 }}>
                {String(note.state.data.note.summary || '—')}
              </p>
              <div className="label" style={{ marginTop: 8 }}>
                {(note.state.data.note.sources as unknown[])?.length ?? 0} sources ·
                {' '}confidence {(Number(note.state.data.note.confidence) * 100).toFixed(0)}%
              </div>
            </div>
          ) : <Absent reason={note.state.reason} />
      ) : null}

      <div className="flex gap-1" style={{ marginTop: 12 }}>
        <button className="btn-ghost" onClick={() => void onExpand()}>expand</button>
        <button className="btn-ghost" onClick={() => void onRemove()}>remove</button>
      </div>
      <div className="label" style={{ color: 'var(--ink-ghost)', marginTop: 10 }}>
        removing takes it off this canvas. What Genesis learned stays in the graph.
      </div>
    </div>
  )
}

/**
 * The selected line: what it claims, who claimed it, and how to take it back.
 *
 * The Delete key does this too. The button exists because a capability reachable
 * only by knowing a keystroke is a capability half the operators do not have —
 * the same parity argument that puts `--unlink` on the CLI.
 */
function EdgeInspector({
  edge, label, busy, onUnlink,
}: {
  edge: CanvasBody['edges'][number]
  label: (id: string) => string
  busy: boolean
  onUnlink: () => void | Promise<void>
}) {
  const mine = edge.namespace === 'operator'
  return (
    <div
      style={{
        width: 300, flexShrink: 0, borderLeft: '1px solid var(--hairline)',
        padding: 10, background: 'var(--bg-panel)',
      }}
    >
      <div className="flex items-center gap-1">
        <Chip tone={mine ? 'core' : 'neutral'}>{edge.kind.replace(/_/g, ' ')}</Chip>
        <span className="label" style={{ color: 'var(--ink-ghost)' }}>
          {mine ? 'you drew this' : `asserted by ${edge.namespace}`}
        </span>
      </div>

      <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)', marginTop: 8, lineHeight: 1.4 }}>
        {label(edge.source)}
        <div className="label" style={{ color: 'var(--core)', margin: '2px 0' }}>
          ↓ {edge.kind.replace(/_/g, ' ')}
        </div>
        {label(edge.target)}
      </div>

      <div className="flex gap-1" style={{ marginTop: 12 }}>
        <button className="btn-ghost" disabled={busy || !mine} onClick={() => void onUnlink()}>
          unlink
        </button>
      </div>
      <div className="label" style={{ color: 'var(--ink-ghost)', marginTop: 10 }}>
        {mine
          ? 'unlinking retracts the claim from the knowledge graph. Delete does the same.'
          : `${edge.namespace} recorded this — it is provenance, not decoration. Remove a node to take it off the canvas.`}
      </div>
    </div>
  )
}
