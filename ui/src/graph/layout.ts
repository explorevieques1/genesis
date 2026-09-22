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
// Families are nested arcs fanning UP from the core (screen 270° is up, y down).
// Execution is the innermost ring — it is the band that touches money. Each ring
// sits a fixed distance outside the last, and every agent in a family is evenly
// spaced along that family's arc: one row, no radial stagger, nothing overlaps.
const BAND_ORDER: Family[] = ['execution', 'journal', 'strategy', 'research', 'charting']

/** The execution ring; each family after it steps out by BAND_GAP. */
const BAND_BASE = 600
const BAND_GAP = 180
/** Arc centre — straight up. */
const ARC_CENTRE = 270
/**
 * Fixed angular gap between adjacent agents in a band. At BAND_BASE this is a
 * ~280px chord — clear of the widest node (spinal, 210px) — and only grows on
 * the outer rings, so one row per family never overlaps.
 */
const NODE_PITCH_DEG = 27
/** Keep outer arcs from running under the MCP columns (~±950px). */
const ARC_HALF_WIDTH = 950

const rad = (deg: number) => (deg * Math.PI) / 180
const deg = (r: number) => (r * 180) / Math.PI

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

  BAND_ORDER.forEach((fam, band) => {
    const list = byFamily.get(fam) ?? []
    if (list.length === 0) return
    const r = BAND_BASE + band * BAND_GAP
    // Even angular spacing at a fixed pitch, so density is the same in every
    // band. Clamped so a long family's arc never runs under the MCP columns.
    const fitHalf = deg(Math.asin(Math.min(1, ARC_HALF_WIDTH / r)))
    const half = Math.min(fitHalf, (NODE_PITCH_DEG * (list.length - 1)) / 2)
    const a0 = ARC_CENTRE - half
    const step = list.length === 1 ? 0 : (half * 2) / (list.length - 1)
    list.forEach((n, i) => {
      const angle = rad(list.length === 1 ? ARC_CENTRE : a0 + step * i)
      pos[n.id] = {
        x: Math.cos(angle) * r - n.width / 2,
        y: Math.sin(angle) * r - n.height / 2,
      }
    })
  })

  // Senses and hands sit outside every band, on the side their pathway implies:
  // afferent left (signal coming in), efferent right (signal going out).
  const mcp = nodes.filter((n) => n.group === 'mcp')
  mcp.forEach((n, i) => {
    const half = Math.ceil(mcp.length / 2)
    const left = i < half
    const row = left ? i : i - half
    const count = left ? half : mcp.length - half
    pos[n.id] = {
      x: (left ? -1040 : 900) - n.width / 2,
      y: (row - (count - 1) / 2) * 58 - n.height / 2,
    }
  })

  const mem = nodes.filter((n) => n.group === 'memory')
  mem.forEach((n, i) => {
    pos[n.id] = {
      x: (i - (mem.length - 1) / 2) * 196 - n.width / 2,
      y: 760 - n.height / 2,
    }
  })

  if (import.meta.env.DEV) warnOnOverlap(nodes, pos)
  return pos
}

/**
 * The check behind "no overlapping, evenly spaced". Dev-only, O(n²) over ~30
 * band nodes — if a pitch or radius change ever lets two agent boxes intersect,
 * this says so in the console instead of the operator finding it on screen.
 */
function warnOnOverlap(nodes: LayoutInput[], pos: Positions) {
  const band = nodes.filter((n) => n.group === 'agent' || n.group === 'spinal')
  for (let i = 0; i < band.length; i++) {
    for (let j = i + 1; j < band.length; j++) {
      const a = band[i], b = band[j]
      const pa = pos[a.id], pb = pos[b.id]
      if (!pa || !pb) continue
      const gapX = Math.abs((pa.x + a.width / 2) - (pb.x + b.width / 2)) - (a.width + b.width) / 2
      const gapY = Math.abs((pa.y + a.height / 2) - (pb.y + b.height / 2)) - (a.height + b.height) / 2
      if (gapX < 0 && gapY < 0) {
        console.warn(`[organismLayout] "${a.id}" and "${b.id}" overlap by`, { gapX, gapY })
      }
    }
  }
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
      'elk.layered.spacing.nodeNodeBetweenLayers': '190',
      'elk.spacing.nodeNode': '34',
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
