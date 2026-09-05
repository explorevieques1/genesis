// Spec: Genesis Markdown/60-UI/Fleet View.md §Events
//
// A scripted Genesis, for building the UI before the daemon grows a socket.
//
// The constraint that makes this useful rather than decorative: **it emits
// nothing the real system could not emit.** Every frame is a valid
// `GenesisEvent`; causation flows only through `parent_task_id`, memory edges
// only through `memory.read`, and an order only ever travels
// propose_order → approval → place_approved. When the daemon is ready, deleting
// this file and pointing `LiveTransport` at the socket changes no other file.
//
// It is deliberately NOT a random event firehose. It runs a pre-market brief as
// a causal script, because the thing the UI has to get right is causation.

import type {
  GenesisEvent, Lane, RiskCheck,
} from '@/types/events'
import { AGENTS, AGENTS_BY_ID, ORCHESTRATOR_ID } from '@/data/roster'
import type { Snapshot, Transport, EventHandler, StatusHandler } from './transport'

let seq = 0
const id = (p: string) => `${p}_${(++seq).toString(36).padStart(5, '0')}`
const now = () => new Date().toISOString()

interface Ctx {
  emit: (e: GenesisEvent) => void
  trace: string
}

const envelope = <N extends string, D>(
  event: N, source: string, trace: string, data: D,
  priority: GenesisEvent['priority'] = 'low', speak = false,
) => ({ event, id: id('evt'), ts: now(), trace_id: trace, source, priority, speak, data })

const laneFor = (agent: string): Lane => {
  const fam = AGENTS_BY_ID.get(agent)?.family
  if (fam === 'execution') return 'execution'
  if (fam === 'strategy') return 'research'
  return 'research'
}

/** One agent doing one unit of work, with the memory reads that made it possible. */
interface Step {
  agent: string
  type: string
  /** ms of simulated work — becomes the particle's travel time on the edge. */
  ms: number
  summary: string
  /** Memory reads this step performs: [namespace, layer, written_by]. */
  reads?: [string, GenesisEvent extends never ? never : 'working' | 'episodic' | 'graph' | 'vector' | 'ledger', string][]
  writes?: ['working' | 'episodic' | 'graph' | 'vector' | 'ledger', string][]
  /** Fail this step instead of completing it. Failures leave a marker; they never vanish. */
  fail?: { failure_class: 'transient' | 'degraded' | 'fatal'; code: string }
  /** Children dispatched by this step — the lineage edges. */
  children?: Step[]
}

const PREMARKET: Step = {
  agent: ORCHESTRATOR_ID, type: 'brief.compose', ms: 900,
  summary: 'Composing the pre-market brief.',
  children: [
    {
      agent: 'market-analyst', type: 'regime.read', ms: 2600,
      summary: 'Regime is risk-on but breadth is narrowing; 10y at 4.31%.',
      reads: [['shared', 'graph', 'digest'], ['lessons', 'vector', 'insight-miner']],
      writes: [['graph', 'market-analyst']],
    },
    {
      agent: 'news-and-catalyst', type: 'catalyst.scan', ms: 3400,
      summary: '14 headlines tagged; NVDA earnings in 2 sessions is the live one.',
      reads: [['shared', 'graph', 'digest']],
      writes: [['episodic', 'news-and-catalyst']],
      children: [
        {
          agent: 'sentiment', type: 'sentiment.read', ms: 1400,
          summary: 'Put/call at 0.62 — crowded long into the print.',
          reads: [['news-and-catalyst', 'graph', 'news-and-catalyst']],
        },
      ],
    },
    {
      agent: 'screener', type: 'scan.run', ms: 1800,
      summary: '6 hits on the compression scan.',
      writes: [['episodic', 'screener']],
      children: [
        {
          agent: 'chart-markup', type: 'markup.create', ms: 2200,
          summary: 'NVDA 4H: supply 128.40–129.10, demand 118.90. Spec written.',
          reads: [['screener', 'episodic', 'screener']],
          writes: [['graph', 'chart-markup']],
          children: [
            {
              agent: 'pattern-recognition', type: 'pattern.classify', ms: 2900,
              summary: 'Ascending triangle, 0.71 confidence; rule check agrees.',
              reads: [['chart-markup', 'graph', 'chart-markup']],
            },
            {
              agent: 'multi-timeframe', type: 'mtf.compose', ms: 3100,
              summary: 'Alignment 0.68 across 1H/4H/1D. Weekly disagrees.',
              reads: [['chart-markup', 'graph', 'chart-markup']],
            },
            {
              agent: 'level-watcher', type: 'level.arm', ms: 260,
              summary: '4 levels armed on NVDA. Reflex — no model in this path.',
              reads: [['chart-markup', 'graph', 'chart-markup']],
            },
          ],
        },
        {
          agent: 'fundamental', type: 'valuation.read', ms: 4200,
          summary: 'Source returned 502 twice.',
          fail: { failure_class: 'transient', code: 'mcp.upstream_5xx' },
        },
      ],
    },
    {
      agent: 'idea-synthesizer', type: 'idea.synthesize', ms: 3800,
      summary: 'One idea ranked above threshold: NVDA long, 0.66, R:R 2.8.',
      reads: [
        ['market-analyst', 'graph', 'market-analyst'],
        ['chart-markup', 'graph', 'chart-markup'],
        ['lessons', 'vector', 'insight-miner'],
      ],
      writes: [['graph', 'idea-synthesizer']],
      children: [
        {
          agent: 'portfolio-and-allocation', type: 'size.compute', ms: 420,
          summary: 'Size 240 sh at 0.75R. Deterministic — no model.',
          reads: [['ledger', 'ledger', 'position-and-pnl-accountant']],
        },
        {
          agent: 'prop-firm-guard', type: 'rules.check', ms: 180,
          summary: 'FTMO daily-loss headroom 71%. Within all four rules.',
          reads: [['ledger', 'ledger', 'position-and-pnl-accountant']],
        },
      ],
    },
    {
      agent: 'digest', type: 'digest.morning', ms: 1600,
      summary: 'Morning brief ready. 1 idea, 4 levels armed, 1 source degraded.',
      reads: [['shared', 'working', ORCHESTRATOR_ID]],
      writes: [['episodic', 'digest']],
    },
  ],
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

/** Walk one step and its children, emitting the real lifecycle. */
async function runStep(
  ctx: Ctx, step: Step, parentTaskId: string | null, alive: () => boolean,
): Promise<void> {
  if (!alive()) return
  const taskId = id('t')
  ctx.emit(envelope('task.dispatched', ORCHESTRATOR_ID, ctx.trace, {
    task_id: taskId, parent_task_id: parentTaskId, agent: step.agent,
    task_type: step.type, lane: laneFor(step.agent),
  }) as GenesisEvent)

  await sleep(120)
  if (!alive()) return
  ctx.emit(envelope('task.started', step.agent, ctx.trace, {
    task_id: taskId, agent: step.agent,
  }) as GenesisEvent)
  ctx.emit(envelope('agent.state_changed', step.agent, ctx.trace, {
    agent: step.agent, from: 'idle', to: 'working', reason: step.type,
  }, 'normal') as GenesisEvent)

  // Memory reads happen early in the step — a read edge is drawn on read, and
  // the write it points back to may be hours old.
  for (const [ns, layer, writtenBy] of step.reads ?? []) {
    await sleep(90)
    if (!alive()) return
    ctx.emit(envelope('memory.read', step.agent, ctx.trace, {
      agent: step.agent, namespace: ns, layer, written_by: writtenBy,
      age_ms: Math.floor(6e4 + Math.random() * 3.6e6),
    }) as GenesisEvent)
  }

  const kids = step.children ?? []
  const work = sleep(step.ms)
  // Children are dispatched partway through the parent, which is what makes the
  // parent's edge stay occupied while its subtree runs.
  const kidRuns = (async () => {
    await sleep(Math.min(step.ms * 0.4, 900))
    await Promise.all(kids.map((k) => runStep(ctx, k, taskId, alive)))
  })()
  await work
  if (!alive()) return

  for (const [layer, ns] of step.writes ?? []) {
    ctx.emit(envelope('memory.written', step.agent, ctx.trace, {
      agent: step.agent, namespace: ns, layer, keys: 1 + Math.floor(Math.random() * 4),
    }) as GenesisEvent)
  }

  if (step.fail) {
    ctx.emit(envelope('task.failed', step.agent, ctx.trace, {
      task_id: taskId, agent: step.agent, ...step.fail,
    }, 'normal') as GenesisEvent)
    ctx.emit(envelope('agent.state_changed', step.agent, ctx.trace, {
      agent: step.agent, from: 'working', to: 'degraded', reason: step.fail.code,
    }, 'normal') as GenesisEvent)
  } else {
    ctx.emit(envelope('task.completed', step.agent, ctx.trace, {
      task_id: taskId, agent: step.agent, wall_ms: step.ms,
      cost_usd: (Math.random() * 0.04).toFixed(4), spoken_summary: step.summary,
    }) as GenesisEvent)
    ctx.emit(envelope('agent.state_changed', step.agent, ctx.trace, {
      agent: step.agent, from: 'working', to: 'idle', reason: 'task.completed',
    }, 'normal') as GenesisEvent)
  }
  await kidRuns
}

const PASSING: RiskCheck[] = [
  { rule: 'max_position_pct', verdict: 'pass', value: '3.10', limit: '5.00' },
  { rule: 'portfolio_heat', verdict: 'pass', value: '4.20', limit: '6.00' },
  { rule: 'daily_loss_headroom', verdict: 'pass', value: '1840.00', limit: '2500.00' },
  { rule: 'correlation_cluster', verdict: 'pass', value: '0.41', limit: '0.70' },
  { rule: 'propfirm_consistency', verdict: 'pass', value: '18.40', limit: '30.00' },
  { rule: 'fat_finger_notional', verdict: 'pass', value: '29856.00', limit: '75000.00' },
]

const REJECTING: RiskCheck[] = [
  { rule: 'max_position_pct', verdict: 'pass', value: '4.60', limit: '5.00' },
  { rule: 'portfolio_heat', verdict: 'fail', value: '6.40', limit: '6.00' },
  { rule: 'daily_loss_headroom', verdict: 'pass', value: '1840.00', limit: '2500.00' },
]

/**
 * The only execution path that exists. Note there is no branch in which an order
 * reaches the broker without an `order.approved` preceding it — the mock cannot
 * express one, which is the point.
 */
async function runOrder(
  ctx: Ctx, approved: boolean, alive: () => boolean,
): Promise<void> {
  const proposalId = id('prop')
  ctx.emit(envelope('order.proposed', 'idea-synthesizer', ctx.trace, {
    proposal_id: proposalId, symbol: 'NVDA', side: 'buy', qty: '240',
    limit_price: '124.40', proposed_by: 'idea-synthesizer',
  }, 'normal') as GenesisEvent)

  await sleep(700)
  if (!alive()) return

  if (!approved) {
    ctx.emit(envelope('order.rejected', 'pre-trade-risk-engine', ctx.trace, {
      proposal_id: proposalId, checks: REJECTING,
    }, 'high', true) as GenesisEvent)
    ctx.emit(envelope('risk.breached', 'pre-trade-risk-engine', ctx.trace, {
      rule: 'portfolio_heat', value: '6.40', limit: '6.00',
    }, 'critical', true) as GenesisEvent)
    return
  }

  const approvalId = id('appr')
  ctx.emit(envelope('order.approved', 'pre-trade-risk-engine', ctx.trace, {
    proposal_id: proposalId, approval_id: approvalId,
    token_bound_to: proposalId, checks: PASSING,
  }, 'high', true) as GenesisEvent)

  await sleep(900)
  if (!alive()) return
  const orderId = id('ord')
  ctx.emit(envelope('order.placed', 'order-manager', ctx.trace, {
    order_id: orderId, approval_id: approvalId, broker_id: 'alp_7714b2', symbol: 'NVDA',
  }, 'high') as GenesisEvent)

  await sleep(1600)
  if (!alive()) return
  ctx.emit(envelope('order.filled', 'broker-adapter', ctx.trace, {
    fill_id: id('fill'), order_id: orderId, symbol: 'NVDA',
    price: '124.38', qty: '240',
  }, 'high', true) as GenesisEvent)

  await sleep(400)
  if (!alive()) return
  await runStep(ctx, {
    agent: 'trade-journal', type: 'journal.write', ms: 1200,
    summary: 'NVDA long journalled with the 4H markup and the thesis.',
    reads: [['ledger', 'ledger', 'position-and-pnl-accountant']],
    writes: [['episodic', 'trade-journal']],
  }, null, alive)
}

export class MockTransport implements Transport {
  readonly kind = 'mock' as const
  private stopped = false
  private timers: number[] = []

  start(onEvent: EventHandler, onStatus: StatusHandler): void {
    this.stopped = false
    onStatus('connecting', false)
    const alive = () => !this.stopped

    const t = window.setTimeout(async () => {
      onStatus('open', false)
      const emit = (e: GenesisEvent) => { if (!this.stopped) onEvent(e) }

      // Cycle forever: brief → an approved order → health noise → a rejection.
      for (let cycle = 0; alive(); cycle++) {
        const trace = id('tr')
        const ctx: Ctx = { emit, trace }
        emit(envelope('voice.state_changed', ORCHESTRATOR_ID, trace, { to: 'working' }, 'low') as GenesisEvent)
        await runStep(ctx, PREMARKET, null, alive)
        if (!alive()) break
        emit(envelope('voice.state_changed', ORCHESTRATOR_ID, trace, { to: 'speaking' }, 'low') as GenesisEvent)
        await sleep(1400)
        if (!alive()) break

        await runOrder({ emit, trace: id('tr') }, cycle % 3 !== 2, alive)
        if (!alive()) break

        emit(envelope('voice.state_changed', ORCHESTRATOR_ID, trace, { to: 'idle' }, 'low') as GenesisEvent)

        if (cycle % 3 === 1) {
          emit(envelope('data.stale', 'watchdog', trace, { feed: 'yfinance', age_ms: 94000 }, 'normal') as GenesisEvent)
          emit(envelope('mcp.session_lost', 'watchdog', trace, { server: 'openbb-mcp', retries: 2 }, 'normal') as GenesisEvent)
        }
        if (cycle % 3 === 2) {
          emit(envelope('agent.recovered', 'watchdog', trace, { agent: 'fundamental' }, 'normal') as GenesisEvent)
        }
        await sleep(2600)
      }
    }, 380)
    this.timers.push(t)
  }

  stop(): void {
    this.stopped = true
    this.timers.forEach(clearTimeout)
    this.timers = []
  }

  async snapshot(): Promise<Snapshot> {
    return {
      watermark: id('evt'),
      // Strings, not numbers — UI Stack §8. The UI formats; it never computes.
      safety: {
        approvalMode: 'confirm',
        portfolioHeat: '4.20',
        heatLimit: '6.00',
        dailyLossHeadroom: '1840.00',
        openPositions: 2,
        halted: false,
        haltTrigger: null,
        asOf: Date.now(),
      },
      health: {
        daemon: 'ok', memory: 'ok', risk: 'ok',
        voice: 'ok', execution: 'ok', connectivity: 'ok',
      },
    }
  }
}

/** Every agent the mock script can actually touch. Used by the "unbuilt" hint. */
export const MOCK_ACTIVE_AGENTS = new Set(
  AGENTS.filter((s) => s.build === 'built' || s.family === 'research' || s.family === 'execution')
    .map((s) => s.id),
)
