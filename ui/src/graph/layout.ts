// Spec: Genesis Markdown/60-UI/Fleet View.md §Layout
//
// Two layouts, one rule: **positions are computed once per topology change and
// cached.** A graph that re-solves when a task lands is unreadable, and worse, it
// destroys the operator's spatial memory of where the execution family sits.
// Nothing in the live event path may move a node.
//
//   `layered`  — elkjs, left-to-right, the topology in System Overview. This is
//                what the note specifies, and it is what you read when you are
//                asking "where did this come from".
//   `organism`  — a radial body map: Genesis at the centre, families as orbital
//                bands, the execution band closest to the core because it is the
//                one that touches money. This is the default main screen.
//
// The organism layout is an addition to the note, recorded in Fleet View.md
// §Layout — spec and code move in the same commit (Biological Design §5).

import type { ElkNode } from 'elkjs/lib/elk-api'
import type { Family } from '@/types/events'
import { FAMILY_ORDER, FAMILIES } from '@/data/roster'

export type LayoutMode = 'organism' | 'layered'

export interface LayoutInput {
  id: string
  /** `agent` | `family` | `core` | `mcp` | `memory` | `spinal` */
  group: string
  family: Family | null
  width: number
  height: number
}

export interface LayoutEdgeInput { id: string; source: string; target: string }

export type Positions = Record<string, { x: number; y: number }>

/**
 * elkjs is ~1.4 MB and only the `layered` mode needs it. The default `organism`
 * layout is deterministic and synchronous, so the solver is loaded on first use
 * rather than on first paint — the body map must be on screen fast.
 */
let elkPromise: Promise<{ layout(g: ElkNode): Promise<ElkNode> }> | null = null
const getElk = () => (elkPromise ??= import('elkjs/lib/elk.bundled.js').then(
  (m) => new (m.default as new () => { layout(g: ElkNode): Promise<ElkNode> })(),
))

/**
 * The dial. Each family owns a disjoint angular sector and a fixed radius, so an
 * agent is in the same place in every session and never migrates between bands.
 *
 * Execution is innermost — it is the band that touches money, and the note asks
 * for it to be distinguishable at a glance and given a boundary of its own.
 */
const BAND_ORDER: Family[] = ['execution', 'journal', 'strategy', 'research', 'charting']

const BAND_R: Record<Family, number> = {
  execution: 390, journal: 620, strategy: 620, research: 640, charting: 640, core: 0,
}

/** Disjoint sectors, 4° gutters. Degrees, screen space (y down, 0° is right). */
const BAND_SWEEP: Record<Family, [number, number]> = {
  execution: [-46, 46],
  journal: [42, 106],
  strategy: [114, 178],
  research: [186, 250],
  charting: [258, 322],
  core: [0, 0],
}

/** Radial stagger within a band, so 176px-wide labels in a dense arc clear each other. */
const BAND_STAGGER = 112

const rad = (deg: number) => (deg * Math.PI) / 180

/**
 * Radial body map. Deterministic and synchronous — no solver, so it cannot
 * wobble. Agents are placed by their index within their family, which is fixed
 * by the roster, so a given agent is in the same place in every session.
 */
export function organismLayout(nodes: LayoutInput[]): Positions {
  const pos: Positions = {}
  const byFamily = new Map<Family, LayoutInput[]>()
  for (const n of nodes) {
    if (n.group === 'core') { pos[n.id] = { x: -n.width / 2, y: -n.height / 2 }; continue }
    if (!n.family) continue
    const list = byFamily.get(n.family) ?? []
    list.push(n)
    byFamily.set(n.family, list)
  }

  for (const fam of BAND_ORDER) {
    const list = byFamily.get(fam) ?? []
    if (list.length === 0) continue
    const [a0, a1] = BAND_SWEEP[fam]
    const r = BAND_R[fam]
    const step = list.length === 1 ? 0 : (a1 - a0) / (list.length - 1)
    list.forEach((n, i) => {
      const angle = rad(list.length === 1 ? (a0 + a1) / 2 : a0 + step * i)
      const rr = r + (i % 2 === 0 ? 0 : BAND_STAGGER)
      pos[n.id] = {
        x: Math.cos(angle) * rr - n.width / 2,
        y: Math.sin(angle) * rr - n.height / 2,
      }
    })
  }

  // Senses and hands sit outside every band, on the side their pathway implies:
  // afferent left (signal coming in), efferent right (signal going out).
  const mcp = nodes.filter((n) => n.group === 'mcp')
  mcp.forEach((n, i) => {
    const half = Math.ceil(mcp.length / 2)
    const left = i < half
    const row = left ? i : i - half
    const count = left ? half : mcp.length - half
    pos[n.id] = {
      x: (left ? -1240 : 1060) - n.width / 2,
      y: (row - (count - 1) / 2) * 58 - n.height / 2,
    }
  })

  const mem = nodes.filter((n) => n.group === 'memory')
  mem.forEach((n, i) => {
    pos[n.id] = {
      x: (i - (mem.length - 1) / 2) * 196 - n.width / 2,
      y: 940 - n.height / 2,
    }
  })

  return pos
}

/**
 * elkjs layered layout — Fleet View §Layout. Family grouping is spatial and fixed
 * via `layerConstraint`-like partitioning so the execution band keeps its own row.
 */
export async function layeredLayout(
  nodes: LayoutInput[], edges: LayoutEdgeInput[],
): Promise<Positions> {
  const partition = (n: LayoutInput): number => {
    if (n.group === 'mcp') return 0
    if (n.group === 'memory') return 4
    if (n.group === 'core') return 3
    switch (n.family) {
      case 'research': case 'charting': return 1
      case 'strategy': case 'journal': return 2
      case 'execution': return 2
      default: return 2
    }
  }

  const graph: ElkNode = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.layered.spacing.nodeNodeBetweenLayers': '160',
      'elk.spacing.nodeNode': '26',
      'elk.partitioning.activate': 'true',
      'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
      'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
      'elk.edgeRouting': 'SPLINES',
    },
    children: nodes.map((n) => ({
      id: n.id,
      width: n.width,
      height: n.height,
      layoutOptions: { 'elk.partitioning.partition': String(partition(n)) },
    })),
    // Only real edges shape the layout. A layout influenced by transient memory
    // edges would move nodes as memory traffic changed — the wobble the note bans.
    edges: edges.map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] })),
  }

  const solved = await (await getElk()).layout(graph)
  const pos: Positions = {}
  for (const c of solved.children ?? []) {
    pos[c.id] = { x: c.x ?? 0, y: c.y ?? 0 }
  }
  return pos
}

/**
 * A signature of the *topology*, not of the live state. The layout is recomputed
 * only when this changes — which is what keeps positions stable under load.
 */
export function topologySignature(
  mode: LayoutMode, nodes: LayoutInput[], edges: LayoutEdgeInput[],
): string {
  return `${mode}|${nodes.map((n) => n.id).sort().join(',')}|${edges.map((e) => e.id).sort().join(',')}`
}

export const FAMILY_LABELS = FAMILY_ORDER.map((f) => FAMILIES[f])
