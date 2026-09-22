// Spec: Genesis Markdown/60-UI/Fleet View.md
//
// Builds the React Flow node and edge arrays from the roster plus the live fold.
//
// The load-bearing separation in this file: **topology and state are computed at
// different rates.** Positions come from a layout that is solved once per
// topology change and cached; live state only ever changes a node's `data`.
// Nothing on the event path can move a node, which is what makes the note's
// "node positions are stable across questions" true rather than hoped.

import { useEffect, useMemo, useRef, useState } from 'react'
import type { FleetEdge as FleetEdgeModel } from '@/types/fleet'
import {
  AGENTS as ROSTER, KILL_SWITCH_ID, MCP_SERVERS,
  MEMORY_LAYERS, ORCHESTRATOR_ID, RISK_ENGINE_ID,
} from '@/data/roster'
import { useFleetReconciliation } from '@/api/fleet'
import { useGenesis } from '@/store/useGenesis'
import {
  layeredLayout, organismLayout, topologySignature,
  type LayoutEdgeInput, type LayoutInput, type LayoutMode, type Positions,
} from './layout'
import type { AgentFlowNode } from './nodes/AgentNode'
import type { CoreFlowNode } from './nodes/CoreNode'
import type { McpFlowNode, MemoryFlowNode, SpinalFlowNode } from './nodes/SystemNode'
import type { FleetFlowEdge, StructureFlowEdge } from './edges/FleetEdges'

export type FleetNode = AgentFlowNode | CoreFlowNode | SpinalFlowNode | McpFlowNode | MemoryFlowNode

const AGENT_W = 176
const AGENT_H = 44

/**
 * The static node set. Never changes at runtime — this IS the topology.
 *
 * Uses the vault ROSTER rather than the reconciled fleet, deliberately. Layout
 * is computed from this, and if it shrank when the daemon reported an agent
 * absent, every node on the map would move the moment `/v1/fleet/agents`
 * answered. `Fleet View` bans that wobble: an unbuilt agent keeps its place and
 * is drawn as absent.
 */
function topologyNodes(showMcp: boolean, showMemory: boolean): LayoutInput[] {
  const out: LayoutInput[] = [
    { id: ORCHESTRATOR_ID, group: 'core', family: 'core', width: 200, height: 84 },
  ]
  for (const s of ROSTER) {
    const spinal = s.id === RISK_ENGINE_ID || s.id === KILL_SWITCH_ID
    out.push({
      id: s.id,
      group: spinal ? 'spinal' : 'agent',
      family: s.family,
      width: spinal ? 210 : AGENT_W,
      height: spinal ? 46 : AGENT_H,
    })
  }
  if (showMcp) {
    for (const m of MCP_SERVERS) out.push({ id: `mcp:${m.id}`, group: 'mcp', family: null, width: 190, height: 26 })
  }
  if (showMemory) {
    for (const l of MEMORY_LAYERS) out.push({ id: `mem:${l.id}`, group: 'memory', family: null, width: 168, height: 40 })
  }
  return out
}

/**
 * Structural edges used only to *shape* the layered layout. Deliberately not the
 * live edges: a layout influenced by transient memory traffic would reposition
 * nodes as that traffic changed, which is the wobble the note bans.
 */
function topologyEdges(nodes: LayoutInput[]): LayoutEdgeInput[] {
  const present = new Set(nodes.map((n) => n.id))
  const out: LayoutEdgeInput[] = []
  for (const s of ROSTER) {
    if (!present.has(s.id)) continue
    out.push({ id: `topo:${s.id}`, source: s.id, target: ORCHESTRATOR_ID })
  }
  for (const m of MCP_SERVERS) {
    const nid = `mcp:${m.id}`
    if (!present.has(nid)) continue
    // Afferent servers feed the fleet; efferent servers are fed by it.
    const anchor = ROSTER.find((a) => a.tools?.some((t) => t.startsWith(m.id)))?.id
      ?? (m.pathway === 'efferent' ? 'order-manager' : 'screener')
    out.push(m.pathway === 'afferent'
      ? { id: `topo:${nid}`, source: nid, target: anchor }
      : { id: `topo:${nid}`, source: anchor, target: nid })
  }
  return out
}

/** Solves and caches the layout. Recomputed only when the signature changes. */
function useLayout(mode: LayoutMode, showMcp: boolean, showMemory: boolean) {
  // The signature of the layout currently ON SCREEN, which is not the same as the
  // signature being solved: the layered solver is async, so for a second or two
  // after a mode switch the positions are still the previous layout's. Anything
  // that must react to "the arrangement actually changed" — the viewport fit —
  // has to key off this, not off the requested mode.
  const [solved, setSolved] = useState<{ sig: string; positions: Positions }>({ sig: '', positions: {} })
  const cache = useRef(new Map<string, Positions>())

  const { nodes, edges, sig } = useMemo(() => {
    const n = topologyNodes(showMcp, showMemory)
    const e = topologyEdges(n)
    return { nodes: n, edges: e, sig: topologySignature(mode, n, e) }
  }, [mode, showMcp, showMemory])

  useEffect(() => {
    const hit = cache.current.get(sig)
    if (hit) { setSolved({ sig, positions: hit }); return }

    if (mode === 'organism') {
      const pos = organismLayout(nodes)
      cache.current.set(sig, pos)
      setSolved({ sig, positions: pos })
      return
    }

    let cancelled = false
    layeredLayout(nodes, edges).then((pos) => {
      if (cancelled) return
      cache.current.set(sig, pos)
      setSolved({ sig, positions: pos })
    }).catch(() => {
      // A layout that failed to solve falls back to the deterministic radial one
      // rather than to an empty canvas. Losing the graph would be losing a view
      // of the fleet, which is worse than losing the preferred arrangement.
      if (!cancelled) setSolved({ sig, positions: organismLayout(nodes) })
    })
    return () => { cancelled = true }
  }, [sig, mode, nodes, edges])

  return solved
}

export interface FleetGraphOptions {
  mode: LayoutMode
  showMcp: boolean
  showMemory: boolean
  /** The always-on topology skeleton — every agent to the orchestrator, MCP to
   *  its anchor, memory to the core. Off by default only if the operator wants
   *  a pure traffic view. */
  showStructure: boolean
  /** Wall-clock ms, ticked by the render loop. Drives elapsed times and fades. */
  now: number
}

/**
 * Nodes tick slower than edges, deliberately.
 *
 * Node `data` carries elapsed-time labels, which are rendered to a tenth of a
 * second — so rebuilding the node array on the render clock (~20 Hz) re-diffs
 * every node twenty times a second to produce a label that changed in one of
 * them. At thirty-plus agents that is the cost that eats the note's ≥50 fps
 * budget, and it makes every node perpetually "in motion" for anything that
 * watches the DOM.
 *
 * Edges keep the fast clock: a particle's position IS the latency display, and
 * quantising it would make the one genuinely continuous thing on screen choppy.
 */
const NODE_TICK_MS = 250

/**
 * Identity preservation for the node array.
 *
 * React Flow treats a node object it has not seen before as unmeasured, and it
 * paints an unmeasured node with `visibility: hidden` until the next measure
 * pass. Handing it a freshly-built array every render therefore makes every node
 * flicker — invisible for a frame or two at a time — which is both a rendering
 * cost and, worse, a node the operator can fail to click.
 *
 * So a node object is reused verbatim unless something the node actually renders
 * changed. The signature below is the list of those things; anything added to a
 * node's `data` that affects its appearance must be added here too, or the node
 * will stop updating.
 */
function useStableNodes(next: FleetNode[]): FleetNode[] {
  const cache = useRef(new Map<string, { sig: string; node: FleetNode }>())
  return useMemo(() => {
    const seen = new Map<string, { sig: string; node: FleetNode }>()
    const out = next.map((n) => {
      const sig = nodeSignature(n)
      const prev = cache.current.get(n.id)
      const node = prev && prev.sig === sig ? prev.node : n
      seen.set(n.id, { sig, node })
      return node
    })
    cache.current = seen
    return out
  }, [next])
}

function nodeSignature(n: FleetNode): string {
  const p = n.position
  const base = `${n.type}|${Math.round(p.x)},${Math.round(p.y)}`
  switch (n.type) {
    case 'agent': {
      const d = n.data
      // `now` is deliberately absent: it changes constantly and only shifts an
      // elapsed label. `startedAt` covers the case that matters — a task began
      // or ended — and the quantised node clock refreshes the label from there.
      return `${base}|${d.state}|${d.phase}|${d.taskType}|${d.startedAt}|${d.failed}|${d.selected}|${d.dimmed}|${d.unseen}|${d.unbuilt}|${d.now}`
    }
    case 'core':
      return `${base}|${n.data.state}|${n.data.inFlight}`
    case 'spinal': {
      const d = n.data
      return `${base}|${d.health}|${d.armed}|${d.dimmed}|${d.selected}`
    }
    case 'mcp':
      return `${base}|${n.data.dimmed}`
    case 'memory': {
      const d = n.data
      return `${base}|${d.reads}|${d.writes}|${d.hot}|${d.dimmed}`
    }
    default:
      return base
  }
}

export function useFleetGraph({ mode, showMcp, showMemory, showStructure, now }: FleetGraphOptions) {
  // The roster says what the organism should be; the daemon says what it is.
  // `build` comes from the daemon, so an agent that exists only in the vault
  // renders as absent rather than as a healthy idle one — see `api/fleet.ts`.
  const { specs: AGENTS } = useFleetReconciliation()

  const { sig: layoutSig, positions } = useLayout(mode, showMcp, showMemory)
  const nodeNow = Math.floor(now / NODE_TICK_MS) * NODE_TICK_MS
  const agents = useGenesis((s) => s.agents)
  const liveEdges = useGenesis((s) => s.edges)
  const tokens = useGenesis((s) => s.tokens)
  const tasks = useGenesis((s) => s.tasks)
  const memory = useGenesis((s) => s.memory)
  const health = useGenesis((s) => s.health)
  const coreState = useGenesis((s) => s.coreState)
  const safety = useGenesis((s) => s.safety)
  const selection = useGenesis((s) => s.selection)
  const filters = useGenesis((s) => s.filters)

  /**
   * Focus set. Trace mode: everything outside the selected `trace_id` dims.
   * Agent focus: everything not adjacent to the selected agent dims.
   * Null means no focus — nothing dims.
   */
  const focus = useMemo<Set<string> | null>(() => {
    if (selection.traceId) {
      const set = new Set<string>([ORCHESTRATOR_ID])
      for (const t of Object.values(tasks)) {
        if (t.traceId === selection.traceId) set.add(t.agent)
      }
      for (const e of Object.values(liveEdges)) {
        if (e.traceIds.includes(selection.traceId)) { set.add(e.source); set.add(e.target) }
      }
      return set
    }
    if (selection.agentId) {
      const set = new Set<string>([selection.agentId])
      for (const e of Object.values(liveEdges)) {
        if (e.source === selection.agentId) set.add(e.target)
        if (e.target === selection.agentId) set.add(e.source)
      }
      return set
    }
    return null
  }, [selection.traceId, selection.agentId, tasks, liveEdges])

  /** Search and family filters. An agent filtered out is removed, not dimmed. */
  const visible = useMemo(() => {
    const q = filters.query.trim().toLowerCase()
    const set = new Set<string>([ORCHESTRATOR_ID])
    for (const s of AGENTS) {
      if (!filters.families.has(s.family)) continue
      if (filters.collapsedFamilies.has(s.family)) continue
      if (filters.activeOnly && (agents[s.id]?.lastSeen ?? 0) === 0) continue
      if (q && !(
        s.id.includes(q) || s.name.toLowerCase().includes(q) ||
        s.job.toLowerCase().includes(q) || s.family.includes(q) ||
        (agents[s.id]?.taskType ?? '').toLowerCase().includes(q)
      )) continue
      set.add(s.id)
    }
    // Safety Invariants #1 and #4 are structural. The risk engine and the kill
    // switch are never filtered out of the body map — a surface that can hide
    // the gate is a surface that can mislead about whether it exists.
    set.add(RISK_ENGINE_ID)
    set.add(KILL_SWITCH_ID)
    return set
  }, [filters, agents, AGENTS])

  const rawNodes = useMemo<FleetNode[]>(() => {
    const out: FleetNode[] = []
    const at = (id: string) => positions[id] ?? { x: 0, y: 0 }
    const dim = (id: string) => (focus ? !focus.has(id) : false)

    const inFlight = tokens.filter((t) => t.endedAt === null).length
    out.push({
      id: ORCHESTRATOR_ID,
      type: 'core',
      position: at(ORCHESTRATOR_ID),
      draggable: false,
      selectable: false,
      data: { state: coreState, inFlight, label: 'GENESIS' },
    })

    for (const s of AGENTS) {
      if (!visible.has(s.id)) continue
      const rt = agents[s.id]
      const spinal = s.id === RISK_ENGINE_ID || s.id === KILL_SWITCH_ID
      if (spinal) {
        out.push({
          id: s.id,
          type: 'spinal',
          position: at(s.id),
          draggable: false,
          data: {
            id: s.id,
            label: s.name,
            sub: s.id === KILL_SWITCH_ID
              ? 'Separate process · outside agent control'
              : 'tier: none · fails closed',
            health: s.id === KILL_SWITCH_ID
              ? (safety.halted ? 'down' : health.execution)
              : health.risk,
            armed: s.id === KILL_SWITCH_ID ? !safety.halted : true,
            dimmed: dim(s.id),
            selected: selection.agentId === s.id,
          },
        })
        continue
      }
      out.push({
        id: s.id,
        type: 'agent',
        position: at(s.id),
        draggable: false,
        data: {
          spec: s,
          state: rt?.state ?? 'idle',
          phase: rt?.phase ?? 'idle',
          taskType: rt?.taskType ?? null,
          startedAt: rt?.startedAt ?? null,
          costToday: rt?.costToday ?? '0.0000',
          failed: rt?.failure != null,
          selected: selection.agentId === s.id,
          dimmed: dim(s.id),
          unseen: (rt?.lastSeen ?? 0) === 0,
          // Specified in the vault, no module on disk. Distinct from `unseen`,
          // which means "built, but has never done anything".
          unbuilt: s.build === 'spec',
          now: nodeNow,
        },
      })
    }

    if (showMcp) {
      for (const m of MCP_SERVERS) {
        out.push({
          id: `mcp:${m.id}`, type: 'mcp', position: at(`mcp:${m.id}`),
          draggable: false, data: { server: m, dimmed: focus !== null },
        })
      }
    }
    if (showMemory) {
      for (const l of MEMORY_LAYERS) {
        const rt = memory[l.id]
        out.push({
          id: `mem:${l.id}`, type: 'memory', position: at(`mem:${l.id}`),
          draggable: false,
          data: {
            layer: l, reads: rt.reads, writes: rt.writes,
            hot: rt.lastReadAt !== null && nodeNow - rt.lastReadAt < 4000,
            dimmed: focus !== null,
          },
        })
      }
    }
    return out
  }, [positions, agents, memory, health, safety, coreState, tokens, visible, focus, selection.agentId, showMcp, showMemory, nodeNow, AGENTS])

  const nodes = useStableNodes(rawNodes)

  const edges = useMemo<FleetFlowEdge[]>(() => {
    const byEdge = new Map<string, FleetGraphToken[]>()
    for (const t of tokens) {
      const list = byEdge.get(t.edgeId) ?? []
      list.push(t)
      byEdge.set(t.edgeId, list)
    }
    const out: FleetFlowEdge[] = []
    for (const e of Object.values(liveEdges) as FleetEdgeModel[]) {
      if (!filters.edgeKinds.has(e.kind)) continue
      if (!visible.has(e.source) || !visible.has(e.target)) continue
      const dimmed = focus !== null && !(focus.has(e.source) && focus.has(e.target))
      out.push({
        id: e.id,
        source: e.source,
        target: e.target,
        type: 'fleet',
        data: {
          kind: e.kind,
          count: e.count,
          lastAt: e.lastAt,
          now,
          dimmed,
          label: e.namespace ?? e.eventName,
          tokens: byEdge.get(e.id) ?? [],
        },
      })
    }
    return out
  }, [liveEdges, tokens, visible, focus, filters.edgeKinds, now])

  const structureEdges = useMemo<StructureFlowEdge[]>(() => {
    if (!showStructure) return []
    const out: StructureFlowEdge[] = []
    const link = (id: string, source: string, target: string, dimmed: boolean) =>
      out.push({ id, source, target, type: 'structure', selectable: false, data: { dimmed } })

    for (const s of AGENTS) {
      if (!visible.has(s.id)) continue
      link(`struct:${s.id}`, s.id, ORCHESTRATOR_ID, focus !== null && !focus.has(s.id))
    }
    if (showMcp) {
      for (const m of MCP_SERVERS) {
        const nid = `mcp:${m.id}`
        const anchor = AGENTS.find((a) => a.tools?.some((t) => t.startsWith(m.id)))?.id
          ?? (m.pathway === 'efferent' ? 'order-manager' : 'screener')
        if (!visible.has(anchor)) continue
        // Afferent edges point *into* the fleet, efferent point out. Direction
        // is the whole information content of the edge, so it is a branch
        // rather than an expression evaluated for its effect.
        if (m.pathway === 'afferent') {
          link(`struct:${nid}`, nid, anchor, focus !== null)
        } else {
          link(`struct:${nid}`, anchor, nid, focus !== null)
        }
      }
    }
    if (showMemory) {
      for (const l of MEMORY_LAYERS) link(`struct:mem:${l.id}`, `mem:${l.id}`, ORCHESTRATOR_ID, focus !== null)
    }
    return out
  }, [showStructure, showMcp, showMemory, visible, focus, AGENTS])

  const allEdges = useMemo(() => [...structureEdges, ...edges], [structureEdges, edges])

  return { nodes, edges: allEdges, positions, layoutSig, focus, visible }
}

interface FleetGraphToken {
  taskId: string
  startedAt: number
  endedAt: number | null
  outcome: string
}
