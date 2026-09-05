// Spec: Genesis Markdown/70-Schemas/Event Schema.md
//
// The wire contract. Mirrors the Python envelope in `genesis.observability.EventLog`
// and the catalogue in Event Schema.md. When the daemon grows a WebSocket, these
// types are what it must emit — the mock transport produces nothing that is not
// expressible here.
//
// Type discipline (UI Stack §8): prices, sizes and money are STRINGS. They arrive
// as strings and stay strings until formatted. The UI never does arithmetic on
// them; any number that must be computed is computed by an agent and sent.

/** Event Schema §Envelope — `priority`. */
export type Priority = 'critical' | 'high' | 'normal' | 'low'

/** Task Bus lanes. Mirrors `genesis.bus.task.Lane` (lower drains first). */
export type Lane = 'execution' | 'risk' | 'user' | 'event' | 'research' | 'maintenance'

/** Conventions failure classes, carried by `task.failed`. */
export type FailureClass = 'transient' | 'degraded' | 'fatal'

/** Event Schema §Envelope. `data` is narrowed per event by {@link GenesisEvent}. */
export interface Envelope<E extends string = string, D = Record<string, unknown>> {
  event: E
  id: string
  ts: string
  trace_id: string
  source: string
  priority: Priority
  speak: boolean
  dedupe_key?: string
  data: D
}

// --------------------------------------------------------------------------
// Fleet telemetry — Event Schema §Fleet telemetry, consumed by Fleet View.
// All `speak: false`, all on the low-priority lane.
// --------------------------------------------------------------------------

/** `parent_task_id` is load-bearing: without it the graph shows activity, not causation. */
export type TaskDispatched = Envelope<'task.dispatched', {
  task_id: string
  parent_task_id: string | null
  agent: string
  task_type: string
  lane: Lane
}>

export type TaskStarted = Envelope<'task.started', { task_id: string; agent: string }>

export type TaskCompleted = Envelope<'task.completed', {
  task_id: string
  agent: string
  wall_ms: number
  cost_usd: string
  /** Agent Contract §result — the plain-English line the Activity feed renders. */
  spoken_summary?: string
}>

export type TaskFailed = Envelope<'task.failed', {
  task_id: string
  agent: string
  failure_class: FailureClass
  /** Typed, not free text — Conventions. Displayed verbatim, never interpreted. */
  code: string
}>

export type AgentStateChanged = Envelope<'agent.state_changed', {
  agent: string
  from: AgentState
  to: AgentState
  reason: string
}>

/** Drawn as a *memory* edge, only on read — the write may be hours old. */
export type MemoryRead = Envelope<'memory.read', {
  agent: string
  namespace: string
  layer: MemoryLayerId
  written_by: string
  age_ms: number
}>

export type MemoryWritten = Envelope<'memory.written', {
  agent: string
  namespace: string
  layer: MemoryLayerId
  keys: number
}>

// --------------------------------------------------------------------------
// Execution — Event Schema §Execution, the critical lane.
// --------------------------------------------------------------------------

export type OrderProposed = Envelope<'order.proposed', {
  proposal_id: string
  symbol: string
  side: 'buy' | 'sell'
  qty: string
  limit_price: string | null
  proposed_by: string
}>

/** The binding check output. The verdict comes from the risk engine or is not shown. */
export type OrderApproved = Envelope<'order.approved', {
  proposal_id: string
  approval_id: string
  /** Single-use, order-bound. The UI displays that one exists; never its value. */
  token_bound_to: string
  checks: RiskCheck[]
}>

export type OrderRejected = Envelope<'order.rejected', {
  proposal_id: string
  /** Which rule refused. Fail-closed rejections carry `code: 'uncertain_input'`. */
  checks: RiskCheck[]
}>

export type OrderPlaced = Envelope<'order.placed', {
  order_id: string
  approval_id: string
  broker_id: string
  symbol: string
}>

export type OrderFilled = Envelope<'order.filled', {
  fill_id: string
  order_id: string
  symbol: string
  price: string
  qty: string
}>

export type RiskBreached = Envelope<'risk.breached', {
  rule: string
  value: string
  limit: string
}>

export type HaltEngaged = Envelope<'halt.engaged', {
  trigger: string
  level: 'cancel_all' | 'flatten' | 'halt'
}>

// --------------------------------------------------------------------------
// System health — Event Schema §System health.
// --------------------------------------------------------------------------

export type AgentDown = Envelope<'agent.down', { agent: string; reason: string }>
export type AgentRecovered = Envelope<'agent.recovered', { agent: string }>
export type DataStale = Envelope<'data.stale', { feed: string; age_ms: number }>
export type SystemDegraded = Envelope<'system.degraded', { components: string[] }>
export type McpSessionLost = Envelope<'mcp.session_lost', { server: string; retries: number }>

/** UI Stack §6 — a UI that quietly went blind is the failure to avoid. */
export type UiTierChanged = Envelope<'ui.tier_changed', { from: RenderTier; to: RenderTier; reason: string }>

/** Genesis Core §States / Voice UX state machine. */
export type VoiceStateChanged = Envelope<'voice.state_changed', { to: CoreState }>

export type GenesisEvent =
  | TaskDispatched | TaskStarted | TaskCompleted | TaskFailed
  | AgentStateChanged | MemoryRead | MemoryWritten
  | OrderProposed | OrderApproved | OrderRejected | OrderPlaced | OrderFilled
  | RiskBreached | HaltEngaged
  | AgentDown | AgentRecovered | DataStale | SystemDegraded | McpSessionLost
  | UiTierChanged | VoiceStateChanged

export type GenesisEventName = GenesisEvent['event']

/** Narrowing helper — `if (is(e, 'task.completed')) e.data.wall_ms`. */
export function is<N extends GenesisEventName>(
  e: GenesisEvent,
  name: N,
): e is Extract<GenesisEvent, { event: N }> {
  return e.event === name
}

// --------------------------------------------------------------------------
// Shared vocabularies
// --------------------------------------------------------------------------

/**
 * Mirrors `genesis.agents.base.AgentState` exactly — five states, one machine,
 * rendered by both the Dashboard agent grid and the Fleet View (Fleet View §Nodes).
 *
 * The richer verbs an operator wants — perceiving, thinking, acting, verifying —
 * are NOT states. They are a *phase* derived from the task in flight
 * ({@link ActivityPhase}), because inventing a sixth agent state here would put
 * the UI's vocabulary out of step with the daemon's and the note's.
 */
export type AgentState = 'idle' | 'working' | 'blocked' | 'degraded' | 'down'

/**
 * The visible texture of `working`, derived from the current task's verb.
 * Biological Design: perception, judgement, action and proprioception are
 * different organs doing different things, and the operator should see which.
 */
export type ActivityPhase =
  | 'idle'
  | 'perceiving'   // afferent — reads, feeds, retrieval
  | 'thinking'     // the LLM organ
  | 'acting'       // efferent — a write, authorised and audited
  | 'verifying'    // proprioception — did the act land?
  | 'waiting'      // blocked on a dependency, not on itself
  | 'blocked'
  | 'error'
  | 'complete'

/** LLM Model Tiers. `none` is spinal — see Biological Design §1. */
export type ModelTier = 'none' | 'nano' | 'small' | 'large' | 'vision'

/** Mirrors `AgentDeclaration.family`. */
export type Family = 'research' | 'charting' | 'strategy' | 'execution' | 'journal' | 'core'

/** Memory Fabric §The five layers. */
export type MemoryLayerId = 'working' | 'episodic' | 'graph' | 'vector' | 'ledger'

/** UI Stack §6 degradation ladder. One-way under fault, automatic. */
export type RenderTier = 'hero' | 'ambient' | 'reduced' | 'degraded'

/** Genesis Core §States — five, one-to-one with the Voice UX state machine. */
export type CoreState = 'idle' | 'listening' | 'working' | 'speaking' | 'alert'

/** Approval Modes. Default is `confirm`; `live` must be unmistakable. */
export type ApprovalMode = 'observe' | 'confirm' | 'live'

/** One line of the Pre-Trade Risk Engine's binding check output. */
export interface RiskCheck {
  rule: string
  verdict: 'pass' | 'fail'
  /** Strings, always — UI Stack §8. */
  value: string
  limit: string
}
