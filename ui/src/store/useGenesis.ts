// Spec: Genesis Markdown/60-UI/Fleet View.md · Genesis Markdown/60-UI/Dashboard.md
//
// The single fold from the event stream to the view model.
//
// UI Stack §9: **no client-side state store of record.** Nothing here is an
// authority. Every field is derived from a pushed event or from the static
// roster, and a refresh loses nothing because a snapshot plus a replay rebuilds
// all of it. In particular there is no position, no P&L and no risk verdict
// computed here — those arrive, or they are not shown.

import { create } from 'zustand'
import type {
  ActivityPhase, AgentState, CoreState, GenesisEvent, MemoryLayerId, RenderTier,
} from '@/types/events'
import { is } from '@/types/events'
import type {
  AgentRuntime, ConnectionState, EdgeKind, FleetEdge, MemoryLayerRuntime,
  OrderFlight, SafetyFloor, SystemHealth, TaskRecord, Token,
} from '@/types/fleet'
import { AGENTS, AGENTS_BY_ID, MEMORY_LAYERS, ORCHESTRATOR_ID } from '@/data/roster'
import type { Transport } from '@/transport/transport'

/** How long a value may go unrefreshed before it is rendered as stale. */
export const STALE_AFTER_MS = 20_000
/** Ring size for the event stream. Bounded — the Episodic Log is the archive. */
const EVENT_RING = 600
const TASK_RING = 400
/** A memory edge fades out over this window; the write it points at may be old. */
export const MEMORY_EDGE_TTL_MS = 45_000

export interface Selection {
  agentId: string | null
  taskId: string | null
  traceId: string | null
  eventId: string | null
}

export interface Filters {
  query: string
  families: Set<string>
  /** Hide agents with no runtime activity — the clutter control at 30+ nodes. */
  activeOnly: boolean
  edgeKinds: Set<EdgeKind>
  collapsedFamilies: Set<string>
}

export type SurfaceView = 'organism' | 'trace' | 'memory' | 'execution'

interface GenesisStore {
  // ---- transport ----
  connection: ConnectionState
  transport: Transport | null
  attach: (t: Transport) => void
  detach: () => void

  // ---- pushed / derived state ----
  agents: Record<string, AgentRuntime>
  tasks: Record<string, TaskRecord>
  taskOrder: string[]
  edges: Record<string, FleetEdge>
  tokens: Token[]
  events: GenesisEvent[]
  orders: OrderFlight[]
  memory: Record<MemoryLayerId, MemoryLayerRuntime>
  safety: SafetyFloor
  health: SystemHealth
  coreState: CoreState
  tier: RenderTier

  // ---- ui-only state ----
  view: SurfaceView
  selection: Selection
  filters: Filters
  /** Trace replay: null = live. A number is a wall-clock ms position in the trace. */
  replayAt: number | null

  setView: (v: SurfaceView) => void
  select: (s: Partial<Selection>) => void
  clearSelection: () => void
  setFilter: (f: Partial<Omit<Filters, 'families' | 'edgeKinds' | 'collapsedFamilies'>>) => void
  toggleFamily: (f: string) => void
  toggleCollapsed: (f: string) => void
  toggleEdgeKind: (k: EdgeKind) => void
  setReplayAt: (ms: number | null) => void
  setTier: (t: RenderTier, reason: string) => void
  ingest: (e: GenesisEvent) => void
  prune: () => void
}

const freshAgent = (): AgentRuntime => ({
  state: 'idle', phase: 'idle', taskId: null, taskType: null, startedAt: null,
  lastSummary: null, costToday: '0.0000', tasksCompleted: 0, tasksFailed: 0,
  lastSeen: 0, failure: null,
})

const initialAgents = (): Record<string, AgentRuntime> => {
  const out: Record<string, AgentRuntime> = { [ORCHESTRATOR_ID]: freshAgent() }
  for (const s of AGENTS) out[s.id] = freshAgent()
  return out
}

const initialMemory = (): Record<MemoryLayerId, MemoryLayerRuntime> =>
  Object.fromEntries(
    MEMORY_LAYERS.map((l) => [l.id, { reads: 0, writes: 0, lastReadAt: null, lastWriteAt: null }]),
  ) as Record<MemoryLayerId, MemoryLayerRuntime>

/**
 * Biological Design: the visible texture of `working`. Derived from the task
 * verb, never from a sixth agent state — the state vocabulary stays the daemon's.
 *
 * Reads and retrievals are afferent; anything that writes to a store or a broker
 * is efferent; a reconciliation or confirmation read is proprioception.
 */
export function phaseFor(taskType: string | null, spec = { tier: 'large' as string }): ActivityPhase {
  if (!taskType) return 'idle'
  const verb = taskType.split('.')[1] ?? taskType
  if (/^(read|scan|watch|fetch|arm|recall|search)/.test(verb)) return 'perceiving'
  if (/^(write|place|cancel|modify|create|journal|render)/.test(verb)) return 'acting'
  if (/^(check|verify|reconcile|compare)/.test(verb)) return 'verifying'
  // A spinal component never "thinks" — it computes. Showing it as thinking would
  // be the UI claiming a model is in a path the architecture forbids one in.
  if (spec.tier === 'none') return 'verifying'
  return 'thinking'
}

const edgeId = (kind: EdgeKind, s: string, t: string) => `${kind}:${s}->${t}`

const touch = (
  edges: Record<string, FleetEdge>, kind: EdgeKind, source: string, target: string,
  ts: number, traceId: string, extra: Partial<FleetEdge> = {},
) => {
  if (source === target) return
  const eid = edgeId(kind, source, target)
  const prev = edges[eid]
  edges[eid] = prev
    ? { ...prev, ...extra, count: prev.count + 1, lastAt: ts,
        traceIds: prev.traceIds.includes(traceId) ? prev.traceIds : [...prev.traceIds.slice(-19), traceId] }
    : { id: eid, kind, source, target, count: 1, lastAt: ts, traceIds: [traceId], ...extra }
}

export const useGenesis = create<GenesisStore>((set, get) => ({
  connection: { kind: 'mock', status: 'closed', gap: false, lastEventAt: null },
  transport: null,

  agents: initialAgents(),
  tasks: {},
  taskOrder: [],
  edges: {},
  tokens: [],
  events: [],
  orders: [],
  memory: initialMemory(),
  safety: {
    approvalMode: 'confirm', portfolioHeat: '—', heatLimit: '—',
    dailyLossHeadroom: '—', openPositions: 0, halted: false, haltTrigger: null, asOf: 0,
  },
  health: {
    daemon: 'unknown', memory: 'unknown', risk: 'unknown',
    voice: 'unknown', execution: 'unknown', connectivity: 'unknown',
  },
  coreState: 'idle',
  tier: 'ambient',

  view: 'organism',
  selection: { agentId: null, taskId: null, traceId: null, eventId: null },
  filters: {
    query: '',
    families: new Set(['research', 'charting', 'strategy', 'execution', 'journal', 'core']),
    activeOnly: false,
    edgeKinds: new Set<EdgeKind>(['lineage', 'memory', 'event']),
    collapsedFamilies: new Set<string>(),
  },
  replayAt: null,

  attach(t) {
    get().detach()
    set({ transport: t, connection: { kind: t.kind, status: 'connecting', gap: false, lastEventAt: null } })
    t.snapshot()
      .then((snap) => set({ safety: snap.safety, health: snap.health }))
      .catch(() => set((s) => ({
        // A snapshot we could not get is a gap. Say so; do not paint confidence.
        connection: { ...s.connection, gap: true },
        health: { ...s.health, connectivity: 'degraded' },
      })))
    t.start(
      (e) => get().ingest(e),
      (status, gap) => set((s) => ({
        connection: { ...s.connection, status, gap },
        health: {
          ...s.health,
          connectivity: status === 'open' ? (gap ? 'degraded' : 'ok') : 'down',
        },
        // UI Stack §6: the ladder is automatic. It drops on fault without
        // waiting for a user choice, and it climbs back only on a *healthy*
        // reconnect — a gap the transport could not close keeps it down, because
        // a surface with a hole in its history must not present as whole.
        tier: status === 'open' && !gap
          ? (s.tier === 'degraded' ? 'ambient' : s.tier)
          : 'degraded',
      })),
    )
  },

  detach() {
    get().transport?.stop()
    set({ transport: null, connection: { kind: 'mock', status: 'closed', gap: false, lastEventAt: null } })
  },

  setView: (view) => set({ view }),
  select: (s) => set((st) => ({ selection: { ...st.selection, ...s } })),
  clearSelection: () => set({
    selection: { agentId: null, taskId: null, traceId: null, eventId: null },
    replayAt: null,
  }),
  setFilter: (f) => set((s) => ({ filters: { ...s.filters, ...f } })),
  toggleFamily: (f) => set((s) => {
    const families = new Set(s.filters.families)
    if (families.has(f)) families.delete(f); else families.add(f)
    return { filters: { ...s.filters, families } }
  }),
  toggleCollapsed: (f) => set((s) => {
    const collapsedFamilies = new Set(s.filters.collapsedFamilies)
    if (collapsedFamilies.has(f)) collapsedFamilies.delete(f); else collapsedFamilies.add(f)
    return { filters: { ...s.filters, collapsedFamilies } }
  }),
  toggleEdgeKind: (k) => set((s) => {
    const edgeKinds = new Set(s.filters.edgeKinds)
    if (edgeKinds.has(k)) edgeKinds.delete(k); else edgeKinds.add(k)
    return { filters: { ...s.filters, edgeKinds } }
  }),
  setReplayAt: (replayAt) => set({ replayAt }),
  setTier: (tier) => set({ tier }),

  // ------------------------------------------------------------------
  // The fold. One switch, one event, no side channels.
  // ------------------------------------------------------------------
  ingest(e) {
    const ts = Date.parse(e.ts) || Date.now()
    set((s) => {
      const agents = { ...s.agents }
      const tasks = { ...s.tasks }
      const edges = { ...s.edges }
      let taskOrder = s.taskOrder
      let tokens = s.tokens
      let orders = s.orders
      const memory = { ...s.memory }
      let health = s.health
      let safety = s.safety
      let coreState = s.coreState

      const bump = (agent: string, patch: Partial<AgentRuntime>) => {
        const prev = agents[agent] ?? freshAgent()
        agents[agent] = { ...prev, ...patch, lastSeen: ts }
      }

      if (is(e, 'task.dispatched')) {
        const d = e.data
        const rec: TaskRecord = {
          id: d.task_id, parentId: d.parent_task_id, traceId: e.trace_id,
          agent: d.agent, type: d.task_type, lane: d.lane, dispatchedAt: ts,
          startedAt: null, endedAt: null, state: 'dispatched',
          wallMs: null, costUsd: null, summary: null, failure: null,
        }
        tasks[d.task_id] = rec
        taskOrder = [...taskOrder, d.task_id].slice(-TASK_RING)

        // Lineage: a task spawned a child task on the bus. The edge runs from the
        // parent's agent to the child's — the only causation the architecture has.
        const parentAgent = d.parent_task_id ? tasks[d.parent_task_id]?.agent : ORCHESTRATOR_ID
        const source = parentAgent ?? ORCHESTRATOR_ID
        touch(edges, 'lineage', source, d.agent, ts, e.trace_id)
        const token: Token = {
          taskId: d.task_id, edgeId: edgeId('lineage', source, d.agent),
          startedAt: ts, endedAt: null, outcome: 'running',
        }
        tokens = [...tokens, token].slice(-200)
      }

      else if (is(e, 'task.started')) {
        const rec = tasks[e.data.task_id]
        if (rec) tasks[rec.id] = { ...rec, startedAt: ts, state: 'running' }
        const spec = AGENTS_BY_ID.get(e.data.agent)
        bump(e.data.agent, {
          taskId: e.data.task_id, taskType: rec?.type ?? null, startedAt: ts,
          phase: phaseFor(rec?.type ?? null, { tier: spec?.tier ?? 'large' }),
        })
      }

      else if (is(e, 'task.completed')) {
        const d = e.data
        const rec = tasks[d.task_id]
        if (rec) {
          tasks[rec.id] = {
            ...rec, endedAt: ts, state: 'done', wallMs: d.wall_ms,
            costUsd: d.cost_usd, summary: d.spoken_summary ?? null,
          }
        }
        tokens = tokens.map((t) =>
          t.taskId === d.task_id ? { ...t, endedAt: ts, outcome: 'completed' as const } : t)
        const prev = agents[d.agent] ?? freshAgent()
        bump(d.agent, {
          phase: 'complete', taskId: null, taskType: null, startedAt: null,
          lastSummary: d.spoken_summary ?? prev.lastSummary,
          tasksCompleted: prev.tasksCompleted + 1,
          // Money stays a string. Summed as fixed-point, never as a float.
          costToday: addMoney(prev.costToday, d.cost_usd),
        })
      }

      else if (is(e, 'task.failed')) {
        const d = e.data
        const rec = tasks[d.task_id]
        if (rec) {
          tasks[rec.id] = {
            ...rec, endedAt: ts, state: 'failed',
            failure: { failureClass: d.failure_class, code: d.code },
          }
        }
        // Fleet View §Edges in motion: a failed task drops its particle at the
        // point of failure and leaves a marker. Failures never simply stop.
        tokens = tokens.map((t) =>
          t.taskId === d.task_id ? { ...t, endedAt: ts, outcome: 'failed' as const } : t)
        const prev = agents[d.agent] ?? freshAgent()
        bump(d.agent, {
          phase: 'error', taskId: null, taskType: null, startedAt: null,
          tasksFailed: prev.tasksFailed + 1,
          failure: { taskId: d.task_id, failureClass: d.failure_class, code: d.code, at: ts },
        })
      }

      else if (is(e, 'agent.state_changed')) {
        bump(e.data.agent, { state: e.data.to as AgentState })
      }

      else if (is(e, 'memory.read')) {
        const d = e.data
        // Drawn only on read, and only if we know who wrote it — the whole value
        // of a memory edge is that it names coordination that bypassed the bus.
        if (d.written_by && d.written_by !== d.agent) {
          touch(edges, 'memory', d.written_by, d.agent, ts, e.trace_id,
            { namespace: d.namespace, layer: d.layer })
        }
        memory[d.layer] = {
          ...memory[d.layer],
          reads: memory[d.layer].reads + 1, lastReadAt: ts,
        }
        bump(d.agent, { phase: 'perceiving' })
      }

      else if (is(e, 'memory.written')) {
        const d = e.data
        memory[d.layer] = {
          ...memory[d.layer],
          writes: memory[d.layer].writes + 1, lastWriteAt: ts,
        }
      }

      // ---- execution: propose_order → approval → place_approved ----
      else if (is(e, 'order.proposed')) {
        const d = e.data
        const flight: OrderFlight = {
          proposalId: d.proposal_id, traceId: e.trace_id, symbol: d.symbol,
          side: d.side, qty: d.qty, limitPrice: d.limit_price,
          proposedBy: d.proposed_by, leg: 'propose_order', verdict: 'pending',
          checks: [], approvalId: null, orderId: null, confirmed: 'none',
          fill: null, at: ts,
        }
        orders = [flight, ...orders].slice(0, 40)
        touch(edges, 'event', d.proposed_by, 'pre-trade-risk-engine', ts, e.trace_id,
          { eventName: 'order.proposed' })
      }

      else if (is(e, 'order.approved')) {
        const d = e.data
        orders = orders.map((o) => o.proposalId === d.proposal_id
          ? { ...o, leg: 'approval', verdict: 'approved', checks: d.checks, approvalId: d.approval_id }
          : o)
        touch(edges, 'event', 'pre-trade-risk-engine', 'order-manager', ts, e.trace_id,
          { eventName: 'order.approved' })
      }

      else if (is(e, 'order.rejected')) {
        const d = e.data
        orders = orders.map((o) => o.proposalId === d.proposal_id
          ? { ...o, leg: 'approval', verdict: 'rejected', checks: d.checks }
          : o)
      }

      else if (is(e, 'order.placed')) {
        const d = e.data
        // `placed` is set from the broker's own acknowledgement, carried by this
        // event. The UI never marks an order placed because a call returned.
        orders = orders.map((o) => o.approvalId === d.approval_id
          ? { ...o, leg: 'place_approved', orderId: d.order_id, confirmed: 'placed' }
          : o)
        touch(edges, 'event', 'order-manager', 'broker-adapter', ts, e.trace_id,
          { eventName: 'order.placed' })
      }

      else if (is(e, 'order.filled')) {
        const d = e.data
        orders = orders.map((o) => o.orderId === d.order_id
          ? { ...o, confirmed: 'filled', fill: { price: d.price, qty: d.qty } }
          : o)
      }

      else if (is(e, 'risk.breached')) {
        health = { ...health, risk: 'degraded' }
        coreState = 'alert'
      }

      else if (is(e, 'halt.engaged')) {
        safety = { ...safety, halted: true, haltTrigger: e.data.trigger, asOf: ts }
        coreState = 'alert'
        health = { ...health, execution: 'down' }
      }

      else if (is(e, 'agent.down')) {
        bump(e.data.agent, { state: 'down' })
        health = { ...health, daemon: 'degraded' }
      }
      else if (is(e, 'agent.recovered')) {
        bump(e.data.agent, { state: 'idle', phase: 'idle', failure: null })
      }
      else if (is(e, 'data.stale')) { health = { ...health, memory: 'degraded' } }
      else if (is(e, 'mcp.session_lost')) { health = { ...health, connectivity: 'degraded' } }
      else if (is(e, 'system.degraded')) { health = { ...health, daemon: 'degraded' } }
      else if (is(e, 'voice.state_changed')) { coreState = e.data.to }

      // The safety floor's freshness clock advances on any event that carries a
      // value it renders — never on unrelated traffic, or "stale" would never fire.
      if (e.event === 'order.filled' || e.event === 'order.approved' || e.event === 'halt.engaged') {
        safety = { ...safety, asOf: ts }
      }

      return {
        agents, tasks, taskOrder, edges, tokens, orders, memory, health, safety, coreState,
        events: [e, ...s.events].slice(0, EVENT_RING),
        connection: { ...s.connection, lastEventAt: ts },
      }
    })
  },

  /** Ages out spent particles and dead memory edges. Driven by one rAF ticker. */
  prune() {
    const cut = Date.now()
    set((s) => {
      const tokens = s.tokens.filter((t) => t.endedAt === null || cut - t.endedAt < 2500)
      const edges: Record<string, FleetEdge> = {}
      for (const [k, ed] of Object.entries(s.edges)) {
        // Memory edges are transient by nature; lineage and event edges are
        // topology and persist so positions stay stable between questions.
        if (ed.kind === 'memory' && cut - ed.lastAt > MEMORY_EDGE_TTL_MS) continue
        edges[k] = ed
      }
      return tokens.length === s.tokens.length &&
        Object.keys(edges).length === Object.keys(s.edges).length
        ? s
        : { ...s, tokens, edges }
    })
  },
}))

/**
 * Fixed-point addition on money strings. Two decimals in, four out — the UI must
 * never turn a price or a cost into an IEEE 754 double (UI Stack §8). This is the
 * one arithmetic exception, and it is confined to a running display counter.
 */
function addMoney(a: string, b: string): string {
  const scale = 10_000
  const toInt = (v: string) => Math.round((Number.parseFloat(v) || 0) * scale)
  return ((toInt(a) + toInt(b)) / scale).toFixed(4)
}

/**
 * Is anything actually moving?
 *
 * The surface used to animate at ~20 fps unconditionally, including when the
 * fleet was completely idle -- 25 React Flow nodes and 54 store subscriptions
 * re-rendering twenty times a second to show nothing changing. On a machine
 * with 8 GB that is the whole lag complaint, and it is also wrong in principle:
 * an organism at rest should cost almost nothing, and Genesis is at rest until
 * it is asked for something.
 *
 * So the clock reads this and stops. A token still travelling, an agent still
 * working, or the core mid-utterance keeps the fast loop alive; nothing in
 * flight drops it to a one-second heartbeat.
 */
export const selectBusy = (s: GenesisStore): boolean => {
  if (s.coreState !== 'idle') return true
  for (const t of s.tokens) {
    // A finished token still fades for ~2s, so it counts as motion until it is
    // actually gone -- otherwise the fade freezes half-drawn.
    if (t.endedAt === null || Date.now() - t.endedAt < 2500) return true
  }
  for (const id in s.agents) {
    if (s.agents[id].state !== 'idle') return true
  }
  return false
}

/** True when a timestamp is old enough that the value must be rendered as stale. */
export const isStale = (at: number | null, now: number, after = STALE_AFTER_MS) =>
  at === null || at === 0 || now - at > after
