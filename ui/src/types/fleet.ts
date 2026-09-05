// Spec: Genesis Markdown/60-UI/Fleet View.md
//
// The derived view model. Everything here is reduced from the event stream in
// `types/events.ts` plus the static roster in `data/roster.ts` — the UI holds no
// state of record (UI Stack §9), so every field below is either pushed or derived
// from something pushed.

import type {
  ActivityPhase, AgentState, ApprovalMode, CoreState, Family, FailureClass,
  Lane, MemoryLayerId, ModelTier, Priority, RenderTier, RiskCheck,
} from './events'

/** Static topology: one entry per agent in Agent Index.md. Never mutated. */
export interface AgentSpec {
  id: string
  name: string
  family: Family
  /** `none` renders as spinal — Biological Design §1. */
  tier: ModelTier
  /** One line, from the agent's own note. Shown in the inspector. */
  job: string
  /** Cadence key from Agent Index: D O C X E. */
  cadence: string
  /** Which vault note specifies it — the body map's return nerve. */
  note: string
  /** Vault frontmatter `status:`. `built` agents can actually appear in traces. */
  build: 'spec' | 'building' | 'built'
  /** MCP capability patterns this agent is allow-listed for (Agent Contract). */
  tools?: string[]
  /** Memory Fabric namespaces, split afferent / efferent (Biological Design §2). */
  reads?: string[]
  writes?: string[]
}

/** Live state for one agent, folded from `agent.state_changed` + task lifecycle. */
export interface AgentRuntime {
  state: AgentState
  phase: ActivityPhase
  /** The task in flight, if any. */
  taskId: string | null
  taskType: string | null
  /** Epoch ms the current task started — elapsed is computed at render time. */
  startedAt: number | null
  /** Last plain-English line this agent produced (Agent Contract `spoken_summary`). */
  lastSummary: string | null
  /** Today's spend. A string: money never becomes a JS number. */
  costToday: string
  tasksCompleted: number
  tasksFailed: number
  /** Epoch ms of the most recent event mentioning this agent — drives staleness. */
  lastSeen: number
  /** Set by `task.failed`; cleared only by acknowledgement (Fleet View §Edges in motion). */
  failure: { taskId: string; failureClass: FailureClass; code: string; at: number } | null
}

/** Fleet View §The correction that shapes everything below — exactly three edge classes. */
export type EdgeKind = 'lineage' | 'memory' | 'event'

export interface FleetEdge {
  id: string
  kind: EdgeKind
  source: string
  target: string
  /** How many observations produced this edge. Drives intensity, not width. */
  count: number
  /** Epoch ms of the most recent observation — memory edges fade from this. */
  lastAt: number
  traceIds: string[]
  /** For memory edges: which layer and namespace the read hit. */
  namespace?: string
  layer?: MemoryLayerId
  /** For event edges: the event name that fanned out. */
  eventName?: string
}

/** One particle in flight along a lineage edge. Travel time IS the task duration. */
export interface Token {
  taskId: string
  edgeId: string
  startedAt: number
  /** null while running — the particle sits on the edge, which is the latency display. */
  endedAt: number | null
  outcome: 'running' | 'completed' | 'failed'
}

/** A task as reconstructed from its lifecycle events. The unit of the Trace view. */
export interface TaskRecord {
  id: string
  parentId: string | null
  traceId: string
  agent: string
  type: string
  lane: Lane
  dispatchedAt: number
  startedAt: number | null
  endedAt: number | null
  state: 'dispatched' | 'running' | 'done' | 'failed'
  wallMs: number | null
  costUsd: string | null
  summary: string | null
  failure: { failureClass: FailureClass; code: string } | null
}

/** Memory Fabric §The five layers — the static description behind the viz. */
export interface MemoryLayer {
  id: MemoryLayerId
  name: string
  store: string
  question: string
  lifetime: string
  note: string
}

/** Live counters per layer, folded from `memory.read` / `memory.written`. */
export interface MemoryLayerRuntime {
  reads: number
  writes: number
  lastReadAt: number | null
  lastWriteAt: number | null
}

/**
 * Safety Invariants #1 — the only execution path that exists.
 * There is no `place_order`. The UI models the three legs explicitly so it is
 * structurally unable to render a shortcut between them.
 */
export type ExecutionLeg = 'propose_order' | 'approval' | 'place_approved'

export interface OrderFlight {
  proposalId: string
  traceId: string
  symbol: string
  side: 'buy' | 'sell'
  qty: string
  limitPrice: string | null
  proposedBy: string
  leg: ExecutionLeg
  verdict: 'pending' | 'approved' | 'rejected'
  checks: RiskCheck[]
  approvalId: string | null
  orderId: string | null
  /**
   * Proprioception (Biological Design §3). `placed` means the broker acknowledged;
   * `filled` means a fill was observed. The UI says an order was placed only when
   * one of these is true — never because a `place_approved` call returned.
   */
  confirmed: 'none' | 'placed' | 'filled'
  fill: { price: string; qty: string } | null
  at: number
}

/** The plain-DOM safety floor (UI Stack §6). Last value received, always painted. */
export interface SafetyFloor {
  approvalMode: ApprovalMode
  /** Strings. Formatted, never computed. */
  portfolioHeat: string
  heatLimit: string
  dailyLossHeadroom: string
  openPositions: number
  halted: boolean
  haltTrigger: string | null
  /** Epoch ms each value was last refreshed — anything older than the threshold is stale. */
  asOf: number
}

/** Health of the organs the operator must be able to see at a glance. */
export type HealthState = 'ok' | 'degraded' | 'down' | 'unknown'

export interface SystemHealth {
  daemon: HealthState
  memory: HealthState
  risk: HealthState
  voice: HealthState
  execution: HealthState
  connectivity: HealthState
}

export interface ConnectionState {
  /** `live` only when a real transport is attached. `mock` must be unmistakable. */
  kind: 'mock' | 'live'
  status: 'connecting' | 'open' | 'closed'
  /** Set when a gap could not be closed — puts the surface in `degraded`. */
  gap: boolean
  lastEventAt: number | null
}

export type { ActivityPhase, AgentState, ApprovalMode, CoreState, Family, Lane, MemoryLayerId, ModelTier, Priority, RenderTier, RiskCheck }
