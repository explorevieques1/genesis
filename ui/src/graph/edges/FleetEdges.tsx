// Spec: Genesis Markdown/60-UI/Fleet View.md §The correction that shapes everything below
//
// Agents do not talk to each other. Build Order §What not to do is explicit:
// "Do not let any agent talk to another agent directly. Task Bus or memory only."
// So there is no agent-to-agent message to draw, and a viz that implies one is
// lying about the architecture.
//
// Every edge is therefore exactly one of three real things, at three visual
// weights, distinguishable without the legend (an acceptance criterion):
//
//   lineage  solid, directional, animated in the direction of causation
//   memory   dashed, drawn only on read, fading — the write may be hours old
//   event    dotted, fanning from publisher to each subscriber that took a task
//
// The distinction is not decorative. It is how the operator sees whether the
// fleet is coordinating through the bus (intended) or through memory
// side-effects (usually the bug you are hunting).

import { memo } from 'react'
import { BaseEdge, getBezierPath, type EdgeProps, type Edge } from '@xyflow/react'
import type { EdgeKind } from '@/types/fleet'
import { MEMORY_EDGE_TTL_MS } from '@/store/useGenesis'

export interface FleetEdgeData extends Record<string, unknown> {
  kind: EdgeKind
  count: number
  lastAt: number
  now: number
  dimmed: boolean
  label?: string
  /** Live particles on this edge. Travel time is the real task duration. */
  tokens: { taskId: string; startedAt: number; endedAt: number | null; outcome: string }[]
}

export type FleetFlowEdge = Edge<FleetEdgeData, 'fleet'>

const STROKE: Record<EdgeKind, string> = {
  lineage: 'var(--edge-lineage)',
  memory: 'var(--edge-memory)',
  event: 'var(--edge-event)',
}

const DASH: Record<EdgeKind, string | undefined> = {
  lineage: undefined,
  memory: '5 4',
  event: '1.5 4',
}

export const FleetEdge = memo(function FleetEdge(props: EdgeProps<FleetFlowEdge>) {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, id } = props
  const [path] = getBezierPath({
    sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, curvature: 0.28,
  })
  if (!data) return <BaseEdge id={id} path={path} />

  const { kind, count, lastAt, now, dimmed, tokens } = data

  // Memory edges fade from the moment of the read. Lineage and event edges are
  // topology and hold a floor opacity so the shape of the fleet stays readable.
  const age = now - lastAt
  const freshness = kind === 'memory'
    ? Math.max(0, 1 - age / MEMORY_EDGE_TTL_MS)
    : Math.max(0.22, 1 - age / 120_000)

  // Intensity tracks tasks IN FLIGHT, not cumulative volume.
  const inFlight = tokens.filter((t) => t.endedAt === null).length
  const opacity = dimmed ? 0.05 : Math.min(0.95, 0.2 + freshness * 0.5 + inFlight * 0.18)
  const width = kind === 'lineage' ? 1 + Math.min(inFlight, 4) * 0.5 : 1

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={{
          stroke: STROKE[kind],
          strokeWidth: width,
          strokeDasharray: DASH[kind],
          strokeOpacity: opacity,
          fill: 'none',
        }}
      />
      {!dimmed && kind === 'lineage' && tokens.map((t) => (
        <EdgeToken key={t.taskId} path={path} token={t} now={now} />
      ))}
      {!dimmed && kind === 'event' && count > 0 && inFlight === 0 && null}
    </>
  )
})

/**
 * One particle per task, released at dispatch, arriving at completion.
 *
 * Travel time is the *real* task duration, so a slow agent is visibly slow — the
 * edge stays occupied. This is a latency display disguised as an animation, and
 * that is why the position is driven by elapsed wall time rather than by a fixed
 * CSS duration.
 *
 * A failed task drops its particle where it failed and leaves a marker.
 */
function EdgeToken({
  path, token, now,
}: {
  path: string
  token: { taskId: string; startedAt: number; endedAt: number | null; outcome: string }
  now: number
}) {
  const end = token.endedAt
  if (token.outcome === 'failed' && end !== null) {
    // Frozen at the point of failure. It does not continue and it does not vanish.
    const frac = clamp01((end - token.startedAt) / 4000)
    return (
      <FrozenMark path={path} frac={frac} color="var(--state-down)" />
    )
  }
  if (end !== null) {
    // Completed: arrived. Held briefly at the target as an emission spike.
    const fade = clamp01(1 - (now - end) / 2000)
    if (fade <= 0) return null
    return <FrozenMark path={path} frac={1} color="var(--core-hot)" opacity={fade} r={2.6} />
  }
  // Running: the particle advances against an *estimated* duration, but never
  // reaches the target — it parks at 92% until completion is actually observed.
  // Arriving on estimate alone would be the UI asserting a task finished when it
  // has no evidence that it did (Biological Design §3).
  // Clamped at both ends: the render clock can lag the event clock (a throttled
  // rAF, a backgrounded window), and a negative keyPoints value is an invalid
  // SVG attribute that silently drops the particle rather than erroring visibly.
  const frac = clamp01(Math.min(0.92, (now - token.startedAt) / 6000))
  return <FrozenMark path={path} frac={frac} color="var(--core-hot)" r={2.4} />
}

function FrozenMark({
  path, frac: raw, color, opacity = 1, r = 3,
}: { path: string; frac: number; color: string; opacity?: number; r?: number }) {
  const frac = clamp01(raw)
  return (
    <circle r={r} fill={color} opacity={opacity} style={{ filter: `drop-shadow(0 0 4px ${color})` }}>
      <animateMotion dur="0.001s" fill="freeze" keyPoints={`${frac};${frac}`} keyTimes="0;1" calcMode="linear" path={path} />
    </circle>
  )
}

const clamp01 = (n: number) => Math.max(0, Math.min(1, n))

// -- structure: the always-on topology skeleton -------------------------------
//
// Fleet View §Layout draws the fleet's shape — sources ▶ MCP ▶ families ▶
// orchestrator, memory below. The three live edge classes above ride on top of
// that shape. Without it, an idle fleet (no daemon, or a quiet morning) is
// thirty disconnected boxes and the operator cannot see the system at all.
//
// It carries no data, never animates, and is not selectable — it is wiring, not
// traffic. It does NOT imply agent-to-agent messaging: every line runs to the
// orchestrator, an MCP surface, or the memory fabric, which is exactly what the
// architecture allows.

export interface StructureEdgeData extends Record<string, unknown> { dimmed: boolean }
export type StructureFlowEdge = Edge<StructureEdgeData, 'structure'>

export const StructureEdge = memo(function StructureEdge(props: EdgeProps<StructureFlowEdge>) {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, id } = props
  const [path] = getBezierPath({
    sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, curvature: 0.2,
  })
  return (
    <BaseEdge
      id={id}
      path={path}
      style={{
        stroke: 'var(--hairline-bright)',
        strokeWidth: 1,
        strokeOpacity: data?.dimmed ? 0.06 : 0.5,
        fill: 'none',
      }}
    />
  )
})
