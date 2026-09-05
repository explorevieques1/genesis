// Spec: Genesis Markdown/60-UI/Dashboard.md §Activity feed · Genesis Markdown/70-Schemas/Event Schema.md
//
// The persistent live stream. This is the panel that makes the system feel alive
// rather than opaque, and it is also the audit surface: every line carries the
// `trace_id` that produced it, and clicking one focuses the graph on that trace.
//
// Dashboard §Everything links back — every number traces to the log entry that
// produced it, so no row here is a dead end.
//
// Priority semantics are the note's, not invented: `critical` never deduplicated
// away, `low` is log-only telemetry, and fleet telemetry rides the low lane so it
// can never contend with an `order.filled`.

import { memo, useMemo, useState } from 'react'
import { useGenesis } from '@/store/useGenesis'
import type { GenesisEvent, Priority } from '@/types/events'
import { clock } from '@/lib/format'

const PRIORITY_COLOR: Record<Priority, string> = {
  critical: 'var(--verdict-blocked)',
  high: 'var(--state-degraded)',
  normal: 'var(--ink-dim)',
  low: 'var(--ink-ghost)',
}

/** Groups for the filter chips. Execution is its own group because it is money. */
const GROUPS = {
  execution: (n: string) => n.startsWith('order.') || n.startsWith('position.') || n.startsWith('risk.') || n.startsWith('halt.'),
  task: (n: string) => n.startsWith('task.') || n.startsWith('agent.'),
  memory: (n: string) => n.startsWith('memory.'),
  system: (n: string) => n.startsWith('data.') || n.startsWith('mcp.') || n.startsWith('system.') || n.startsWith('ui.') || n.startsWith('voice.'),
} as const

type Group = keyof typeof GROUPS

/** One line of plain English per event. Not raw logs — the operator's view. */
function describe(e: GenesisEvent): string {
  const d = e.data as Record<string, unknown>
  const name: string = e.event
  switch (e.event) {
    case 'task.dispatched': return `${d.agent} ← ${d.task_type}${d.parent_task_id ? ' (child)' : ''}`
    case 'task.started': return `${d.agent} started`
    case 'task.completed': return String(d.spoken_summary ?? `${d.agent} completed in ${d.wall_ms}ms`)
    case 'task.failed': return `${d.agent} failed — ${d.failure_class}: ${d.code}`
    case 'agent.state_changed': return `${d.agent} ${d.from} → ${d.to} (${d.reason})`
    case 'memory.read': return `${d.agent} read ${d.namespace} · ${d.layer}, written by ${d.written_by}`
    case 'memory.written': return `${d.agent} wrote ${d.keys} key(s) to ${d.namespace} · ${d.layer}`
    case 'order.proposed': return `proposal ${d.symbol} ${d.side} ${d.qty} @ ${d.limit_price ?? 'mkt'} by ${d.proposed_by}`
    case 'order.approved': return `APPROVED ${d.proposal_id} — token bound to the order`
    case 'order.rejected': return `REJECTED ${d.proposal_id} — risk engine refused`
    case 'order.placed': return `placed ${d.symbol}, broker ack ${d.broker_id}`
    case 'order.filled': return `FILLED ${d.symbol} ${d.qty} @ ${d.price}`
    case 'risk.breached': return `RISK BREACH ${d.rule}: ${d.value} against limit ${d.limit}`
    case 'halt.engaged': return `HALT ENGAGED — ${d.trigger} (${d.level})`
    case 'agent.down': return `${d.agent} down — ${d.reason}`
    case 'agent.recovered': return `${d.agent} recovered`
    case 'data.stale': return `feed ${d.feed} stale by ${d.age_ms}ms`
    case 'mcp.session_lost': return `MCP session lost: ${d.server} (${d.retries} retries)`
    case 'system.degraded': return `system degraded: ${(d.components as string[]).join(', ')}`
    case 'voice.state_changed': return `core → ${d.to}`
    case 'ui.tier_changed': return `render tier ${d.from} → ${d.to} (${d.reason})`
    default: return name
  }
}

export const EventStream = memo(function EventStream() {
  const events = useGenesis((s) => s.events)
  const select = useGenesis((s) => s.select)
  const selection = useGenesis((s) => s.selection)
  const [groups, setGroups] = useState<Set<Group>>(new Set(Object.keys(GROUPS) as Group[]))
  const [query, setQuery] = useState('')
  const [pinnedOnly, setPinnedOnly] = useState(false)

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return events.filter((e) => {
      // `critical` is never filtered out. Event Schema §Priority semantics:
      // critical is "never deduplicated away" and it must not be hideable either.
      if (e.priority === 'critical') return true
      if (pinnedOnly && e.priority === 'low') return false
      const g = (Object.keys(GROUPS) as Group[]).find((k) => GROUPS[k](e.event))
      if (g && !groups.has(g)) return false
      if (q && !(e.event.includes(q) || describe(e).toLowerCase().includes(q) || e.trace_id.includes(q))) return false
      return true
    })
  }, [events, groups, query, pinnedOnly])

  const toggle = (g: Group) => setGroups((prev) => {
    const next = new Set(prev)
    if (next.has(g)) next.delete(g); else next.add(g)
    return next
  })

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-1 px-2 py-[5px] hairline-b" style={{ flexShrink: 0 }}>
        <span className="label">event stream</span>
        <span className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)' }}>
          {shown.length}/{events.length}
        </span>
        <input
          value={query}
          onChange={(ev) => setQuery(ev.target.value)}
          placeholder="filter…"
          style={{
            marginLeft: 'auto', width: 96, background: 'var(--bg-inset)',
            border: '1px solid var(--hairline)', borderRadius: 'var(--r-sm)',
            padding: '1px 6px', fontSize: 'var(--fs-micro)', outline: 'none',
          }}
        />
      </div>

      <div className="flex flex-wrap gap-1 px-2 py-[4px] hairline-b" style={{ flexShrink: 0 }}>
        {(Object.keys(GROUPS) as Group[]).map((g) => (
          <Chip key={g} on={groups.has(g)} onClick={() => toggle(g)}>{g}</Chip>
        ))}
        <Chip on={pinnedOnly} onClick={() => setPinnedOnly((v) => !v)}>hide telemetry</Chip>
      </div>

      <div className="scroll-y flex-1 min-h-0">
        {shown.length === 0 && (
          <div style={{ padding: 10, fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)' }}>
            No events match. The stream is bounded to the last 600 — the Episodic Log is the archive.
          </div>
        )}
        {shown.map((e) => {
          const active = selection.traceId === e.trace_id
          return (
            <button
              key={e.id}
              onClick={() => select({ traceId: active ? null : e.trace_id, eventId: e.id, agentId: null })}
              className="anim-rise w-full text-left flex gap-[6px] px-2 py-[2px]"
              style={{
                background: active ? 'color-mix(in oklab, var(--core) 14%, transparent)' : 'transparent',
                borderLeft: `2px solid ${e.priority === 'critical' || e.priority === 'high'
                  ? PRIORITY_COLOR[e.priority] : 'transparent'}`,
              }}
              title={`${e.event} · trace ${e.trace_id} · source ${e.source} · priority ${e.priority}`}
            >
              <span className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)', flexShrink: 0 }}>
                {clock(e.ts).slice(0, 12)}
              </span>
              <span
                className="num"
                style={{ fontSize: 'var(--fs-micro)', color: PRIORITY_COLOR[e.priority], flexShrink: 0, width: 116 }}
              >
                {e.event}
              </span>
              <span
                className="truncate"
                style={{
                  fontSize: 'var(--fs-tiny)',
                  color: e.priority === 'critical' ? 'var(--verdict-blocked)'
                    : e.priority === 'low' ? 'var(--ink-faint)' : 'var(--ink-dim)',
                }}
              >
                {describe(e)}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
})

export function Chip({
  on, onClick, children, title,
}: { on: boolean; onClick: () => void; children: React.ReactNode; title?: string }) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        fontSize: 'var(--fs-micro)',
        letterSpacing: '0.06em',
        padding: '1px 6px',
        borderRadius: 'var(--r-sm)',
        border: `1px solid ${on ? 'var(--hairline-bright)' : 'var(--hairline)'}`,
        background: on ? 'var(--bg-raised)' : 'transparent',
        color: on ? 'var(--ink-dim)' : 'var(--ink-ghost)',
      }}
    >
      {children}
    </button>
  )
}
