// Spec: Genesis Markdown/10-Architecture/Agent Contract.md · Genesis Markdown/60-UI/Fleet View.md §Nodes
//
// Everything known about one agent, and — as important — everything NOT known.
//
// Fleet View §Not a control surface: this panel shows. Start / stop / restart live
// on the Dashboard agent grid, over HTTP, with the confirmation and audit line
// those actions carry. There is no control here, deliberately: the graph is a
// canvas with pan, zoom and thirty small targets, and an accidental drag that
// stops the risk engine's upstream feed is a class of mistake this surface should
// be *incapable* of, not merely unlikely to permit.
//
// The provenance rule, from Biological Design §3: a field with no event behind it
// says so. "No telemetry" is information; a zero rendered as if it were measured
// is not.

import { memo, useMemo } from 'react'
import { useGenesis } from '@/store/useGenesis'
import { AGENTS_BY_ID, FAMILIES, KILL_SWITCH_ID, RISK_ENGINE_ID } from '@/data/roster'
import { PHASE_META, PhaseMark } from './PhaseMark'
import { ago, elapsed, money } from '@/lib/format'
import type { ModelTier } from '@/types/events'

const TIER_NOTE: Record<ModelTier, string> = {
  none: 'Spinal. Deterministic, sub-millisecond, incapable of hallucinating. A reflex cannot be talked out of firing by a persuasive prompt.',
  nano: 'Trivial classification only.',
  small: 'Cheap judgement; structured output.',
  large: 'Genuinely ambiguous judgement.',
  vision: 'Image reasoning, cross-checked against rules.',
}

export const AgentInspector = memo(function AgentInspector({ now }: { now: number }) {
  const agentId = useGenesis((s) => s.selection.agentId)
  const runtime = useGenesis((s) => (agentId ? s.agents[agentId] : undefined))
  const tasks = useGenesis((s) => s.tasks)
  const edges = useGenesis((s) => s.edges)
  const events = useGenesis((s) => s.events)
  const select = useGenesis((s) => s.select)

  const spec = agentId ? AGENTS_BY_ID.get(agentId) : undefined

  const history = useMemo(
    () => (agentId
      ? Object.values(tasks).filter((t) => t.agent === agentId).sort((a, b) => b.dispatchedAt - a.dispatchedAt).slice(0, 12)
      : []),
    [tasks, agentId],
  )

  const memoryEdges = useMemo(
    () => (agentId ? Object.values(edges).filter((e) => e.kind === 'memory' && (e.source === agentId || e.target === agentId)) : []),
    [edges, agentId],
  )

  const messages = useMemo(
    () => (agentId
      ? events.filter((e) => e.source === agentId || (e.data as { agent?: string }).agent === agentId).slice(0, 10)
      : []),
    [events, agentId],
  )

  if (!spec || !agentId) {
    return (
      <Empty>
        Select an agent in the body map to inspect it.
        <div style={{ marginTop: 6, color: 'var(--ink-ghost)' }}>
          The graph shows; it never controls. Start / stop / restart live on the agent grid, over
          HTTP, with an audit line.
        </div>
      </Empty>
    )
  }

  const rt = runtime
  const unseen = (rt?.lastSeen ?? 0) === 0
  const spinal = spec.tier === 'none'
  const isSystem = agentId === RISK_ENGINE_ID || agentId === KILL_SWITCH_ID

  return (
    <div className="scroll-y h-full min-h-0" style={{ padding: '8px 10px' }}>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-[6px]">
            <span style={{ color: `var(--family-${spec.family})` }}>{FAMILIES[spec.family].glyph}</span>
            <span style={{ fontSize: 'var(--fs-lg)', fontWeight: 600 }}>{spec.name}</span>
          </div>
          <div className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)' }}>{spec.id}</div>
        </div>
        <button
          onClick={() => select({ agentId: null })}
          style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)' }}
        >
          close
        </button>
      </div>

      <p style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)', margin: '6px 0 8px' }}>{spec.job}</p>

      {isSystem && (
        <Callout>
          {agentId === RISK_ENGINE_ID
            ? 'No order reaches a broker without passing this. Not a policy — a structure. There is no place_order tool; only propose_order → approval → place_approved, with signed, single-use, order-bound tokens. It fails closed: uncertain input, missing data or an exception is a rejection.'
            : 'Runs in a process the agent cannot signal. It must work when everything else is broken, which is why it is not on the task bus and not behind this socket.'}
        </Callout>
      )}

      <Section label="state">
        <Row k="agent state" v={rt?.state ?? 'idle'} tone={rt?.state === 'down' ? 'bad' : undefined} />
        <Row
          k="phase"
          v={<span className="flex items-center gap-1"><PhaseMark phase={rt?.phase ?? 'idle'} />{PHASE_META[rt?.phase ?? 'idle'].label}</span>}
        />
        <Row k="current task" v={rt?.taskType ?? '—'} />
        <Row k="elapsed" v={rt?.startedAt ? elapsed(now - rt.startedAt) : '—'} />
        <Row
          k="last seen"
          v={unseen ? 'no telemetry received' : ago(now - (rt?.lastSeen ?? now))}
          tone={unseen ? 'unknown' : undefined}
        />
        {rt?.failure && (
          <Row
            k="failure"
            v={`${rt.failure.failureClass} · ${rt.failure.code}`}
            tone="bad"
          />
        )}
      </Section>

      <Section label="model tier">
        <div className="flex items-center gap-[6px]">
          <span
            className="num"
            style={{
              padding: '1px 6px', borderRadius: 2, fontSize: 'var(--fs-micro)',
              color: spinal ? 'var(--spinal)' : 'var(--judgement)',
              border: `1px solid ${spinal ? 'var(--spinal-dim)' : 'color-mix(in oklab, var(--judgement) 40%, transparent)'}`,
            }}
          >
            {spinal ? 'REFLEX · tier none' : `JUDGEMENT · tier ${spec.tier}`}
          </span>
        </div>
        <p style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', marginTop: 4 }}>
          {TIER_NOTE[spec.tier]}
        </p>
      </Section>

      <Section label="runtime">
        <Row k="cadence" v={spec.cadence} />
        <Row k="tasks completed" v={unseen ? '— no telemetry' : String(rt?.tasksCompleted ?? 0)} tone={unseen ? 'unknown' : undefined} />
        <Row k="tasks failed" v={unseen ? '— no telemetry' : String(rt?.tasksFailed ?? 0)} tone={(rt?.tasksFailed ?? 0) > 0 ? 'bad' : undefined} />
        <Row k="cost today" v={unseen ? '— no telemetry' : money(rt?.costToday ?? '0', { prefix: '$' })} tone={unseen ? 'unknown' : undefined} />
        <Row k="implementation" v={spec.build} tone={spec.build === 'spec' ? 'unknown' : undefined} />
      </Section>

      {rt?.lastSummary && (
        <Section label="last reported">
          <p style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink)' }}>{rt.lastSummary}</p>
          <p style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)', marginTop: 3 }}>
            The agent's own spoken_summary, verbatim. Not a UI interpretation of it.
          </p>
        </Section>
      )}

      <Section label={`tools — ${spec.tools?.length ?? 0} capability pattern(s)`}>
        {(spec.tools ?? []).length === 0
          ? <Muted>No tool grants. This agent reaches nothing outside the fabric.</Muted>
          : (spec.tools ?? []).map((t) => (
            <div key={t} className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-dim)' }}>
              <span style={{ color: 'var(--phase-perceiving)' }}>▶</span> {t}
            </div>
          ))}
      </Section>

      <Section label="memory access">
        <div className="flex gap-3">
          <div className="flex-1">
            <div className="label" style={{ color: 'var(--phase-perceiving)' }}>afferent — reads</div>
            {(spec.reads ?? ['shared']).map((n) => <NsRow key={n} ns={n} />)}
          </div>
          <div className="flex-1">
            <div className="label" style={{ color: 'var(--phase-acting)' }}>efferent — writes</div>
            {(spec.writes ?? []).length === 0
              ? <Muted>none</Muted>
              : (spec.writes ?? []).map((n) => <NsRow key={n} ns={n} />)}
          </div>
        </div>
        <p style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)', marginTop: 4 }}>
          Single-writer namespaces. Reads are cheap and retryable; writes need
          authorisation, ordering and complete audit — different nerves, not one
          undifferentiated list.
        </p>
      </Section>

      <Section label={`observed memory edges — ${memoryEdges.length}`}>
        {memoryEdges.length === 0
          ? <Muted>None observed. A memory edge is drawn only on read.</Muted>
          : memoryEdges.map((e) => (
            <div key={e.id} className="num truncate" style={{ fontSize: 'var(--fs-micro)', color: 'var(--edge-memory)' }}>
              {e.source === agentId ? `→ ${e.target}` : `← ${e.source}`} · {e.namespace ?? '?'} · {e.layer ?? '?'} ×{e.count}
            </div>
          ))}
      </Section>

      <Section label={`execution history — last ${history.length}`}>
        {history.length === 0
          ? <Muted>No tasks observed on this agent in the current window.</Muted>
          : history.map((t) => (
            <button
              key={t.id}
              onClick={() => select({ taskId: t.id, traceId: t.traceId })}
              className="w-full text-left flex items-center gap-[6px]"
              style={{ fontSize: 'var(--fs-micro)', padding: '1px 0' }}
            >
              <span
                style={{
                  color: t.state === 'failed' ? 'var(--state-down)'
                    : t.state === 'done' ? 'var(--verdict-pass)' : 'var(--state-working)',
                }}
              >
                {t.state === 'failed' ? '✕' : t.state === 'done' ? '✓' : '▸'}
              </span>
              <span className="num truncate" style={{ color: 'var(--ink-dim)', flex: 1 }}>{t.type}</span>
              <span className="num" style={{ color: 'var(--ink-ghost)' }}>
                {t.wallMs !== null ? elapsed(t.wallMs) : 'running'}
              </span>
            </button>
          ))}
      </Section>

      <Section label={`messages — last ${messages.length} events naming this agent`}>
        {messages.map((e) => (
          <div key={e.id} className="num truncate" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)' }}>
            {e.event}
          </div>
        ))}
      </Section>

      <Section label="body map">
        <div className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)' }}>
          {spec.note}
        </div>
        <p style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)', marginTop: 3 }}>
          {FAMILIES[spec.family].organ}
        </p>
      </Section>
    </div>
  )
})

function NsRow({ ns }: { ns: string }) {
  return (
    <div className="num truncate" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-dim)' }}>{ns}</div>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 10, paddingTop: 7, borderTop: '1px solid var(--hairline)' }}>
      <div className="label" style={{ marginBottom: 3 }}>{label}</div>
      {children}
    </div>
  )
}

function Row({ k, v, tone }: { k: string; v: React.ReactNode; tone?: 'bad' | 'unknown' }) {
  return (
    <div className="flex items-baseline gap-2" style={{ fontSize: 'var(--fs-micro)' }}>
      <span style={{ color: 'var(--ink-ghost)', width: 96, flexShrink: 0 }}>{k}</span>
      <span
        className="num truncate"
        style={{ color: tone === 'bad' ? 'var(--state-down)' : tone === 'unknown' ? 'var(--ink-ghost)' : 'var(--ink-dim)' }}
      >
        {v}
      </span>
    </div>
  )
}

const Muted = ({ children }: { children: React.ReactNode }) => (
  <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)' }}>{children}</div>
)

const Empty = ({ children }: { children: React.ReactNode }) => (
  <div style={{ padding: 12, fontSize: 'var(--fs-tiny)', color: 'var(--ink-faint)' }}>{children}</div>
)

function Callout({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        borderTop: '1px solid var(--spinal-dim)',
        borderRight: '1px solid var(--spinal-dim)',
        borderBottom: '1px solid var(--spinal-dim)',
        borderLeft: '2px solid var(--spinal)',
        background: 'var(--bg-inset)',
        padding: '6px 8px',
        fontSize: 'var(--fs-micro)',
        color: 'var(--ink-dim)',
        borderRadius: 'var(--r-sm)',
      }}
    >
      {children}
    </div>
  )
}
