// Spec: Genesis Markdown/20-Agents/Journal/Agent — Trade Journal.md · Agent — Insight Miner.md
//
// The journal, as a graph and as a ledger.
//
// The graph edges are **recorded relationships, not similarity scores**. A
// lesson points at the entries it was drawn from because `Lesson.evidence`
// holds those ids; an entry points at its symbol because it has one. Nothing
// here is inferred from text overlap or an embedding, which matters because a
// graph built from similarity looks identical to one built from provenance and
// means something entirely different — the first shows what resembles what,
// the second shows what *justifies* what. Only the second is worth a click when
// you are asking why you believe something.
//
// `journal.db` does not exist until the journal agent has written to it, so the
// common state of this page today is `Absent` — and it says so, with the path.

import { useEffect, useState } from 'react'
import { api, type GraphEdge, type GraphNode } from '@/api/client'
import { useRead } from '@/api/useRead'
import { useCapability } from '@/api/capabilities'
import { Absent, Empty, Loading, RequiresCapability } from '@/components/States'
import { Caveats, Chip, Num, PanelBody, Section, Table } from '@/components/Primitives'
import { ForceGraph } from '@/components/graph/ForceGraph'
import { useWorkspace } from '@/workspace/context'
import { revealPanel } from '@/workspace/dock'

/**
 * Node colours by kind.
 *
 * Family tokens, so a journal node and a journal agent are the same colour
 * across the app — the graph is not its own visual world.
 */
const PALETTE: Record<string, string> = {
  entry: 'var(--family-journal)',
  lesson: 'var(--core)',
  symbol: 'var(--family-charting)',
  hypothesis: 'var(--phase-thinking)',
}

export function JournalGraphPanel() {
  const capability = useCapability('journal.store')
  return (
    <RequiresCapability capability={capability}>
      {() => <Graph />}
    </RequiresCapability>
  )
}

function Graph() {
  const { nodeId, select } = useWorkspace()
  const { state, reload } = useRead(() => api.journalGraph(), [])

  if (state.status === 'loading') return <Loading rows={4} label="graph" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  const { nodes, edges } = state.data
  if (!nodes.length) {
    return (
      <Empty hint="The journal is empty. Entries appear here once the trade journal agent has written one, and lessons once the insight miner has drawn one from them.">
        nothing recorded yet
      </Empty>
    )
  }

  const counts = nodes.reduce<Record<string, number>>((acc, node) => {
    acc[node.kind] = (acc[node.kind] ?? 0) + 1
    return acc
  }, {})

  return (
    <div className="flex flex-col h-full min-h-0">
      <div
        className="flex items-center gap-2 hairline-b"
        style={{ padding: '4px 8px', flexShrink: 0 }}
      >
        {Object.entries(counts).map(([kind, count]) => (
          <span key={kind} className="flex items-center gap-1">
            <span
              style={{
                width: 7, height: 7, borderRadius: '50%',
                background: PALETTE[kind] ?? 'var(--ink-faint)',
              }}
            />
            <span className="label">{kind}</span>
            <span className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)' }}>
              {count}
            </span>
          </span>
        ))}
        <span style={{ flex: 1 }} />
        <span className="label" style={{ color: 'var(--ink-ghost)' }}>
          {edges.length} recorded links · drag to arrange · scroll to zoom
        </span>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <ForceGraph
          nodes={nodes as GraphNode[]}
          edges={edges as GraphEdge[]}
          palette={PALETTE}
          selectedId={nodeId}
          onSelect={(id) => select({ nodeId: id })}
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

export function JournalEntriesPanel() {
  const capability = useCapability('journal.store')
  const { nodeId, select } = useWorkspace()
  const { state, reload } = useRead(() => api.journalEntries(300), [])

  return (
    <RequiresCapability capability={capability}>
      {() => {
        if (state.status === 'loading') return <Loading rows={5} label="entries" />
        if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

        const entries = state.data.entries
        if (!entries.length) {
          return <Empty hint="Every closed trade becomes an entry here, with the plan it was meant to follow.">no entries</Empty>
        }

        return (
          <PanelBody pad={0}>
            <Table
              rows={entries}
              // `id` and `entry_ts`, as `/v1/journal/entries` returns them.
              // This read `entry_id`/`opened_at`/`outcome`, which no response
              // has ever carried: the date column was blank and selection
              // keyed on undefined.
              keyOf={(row, i) => `entry:${row.id ?? i}`}
              selectedKey={nodeId}
              onSelect={(row) => select({ nodeId: `entry:${row.id}` })}
              columns={[
                {
                  key: 'when', header: 'opened', width: 84,
                  render: (row) => (
                    <span className="num">{String(row.entry_ts ?? '').slice(0, 10)}</span>
                  ),
                },
                {
                  key: 'symbol', header: 'symbol', width: 62,
                  render: (row) => (
                    <span style={{ color: 'var(--ink)' }}>{String(row.symbol ?? '—')}</span>
                  ),
                },
                {
                  key: 'outcome', header: 'outcome', width: 74,
                  render: (row) => {
                    // Derived, because the entry stores the arithmetic and not
                    // a label: R above zero won, below lost, exactly zero is
                    // scratch, and no R yet is a trade still open.
                    const r = row.r_multiple as number | null | undefined
                    if (r === null || r === undefined) return null
                    const outcome = r > 0 ? 'WIN' : r < 0 ? 'LOSS' : 'SCRATCH'
                    return (
                      <Chip tone={r > 0 ? 'good' : r < 0 ? 'bad' : 'neutral'}>{outcome}</Chip>
                    )
                  },
                },
                {
                  key: 'r', header: 'R', align: 'right', width: 54,
                  render: (row) => <Num value={row.r_multiple as number} digits={2} signed tone />,
                },
                {
                  key: 'plan', header: 'followed plan', align: 'right',
                  render: (row) => {
                    const adherence = row.plan_adherence as { followed?: boolean } | undefined
                    if (!adherence || adherence.followed === undefined) return null
                    return (
                      <Chip tone={adherence.followed ? 'good' : 'warn'}>
                        {adherence.followed ? 'yes' : 'deviated'}
                      </Chip>
                    )
                  },
                },
              ]}
            />
          </PanelBody>
        )
      }}
    </RequiresCapability>
  )
}

// ---------------------------------------------------------------------------

export function JournalPatternsPanel() {
  const capability = useCapability('journal.patterns')
  const { state, reload } = useRead(() => api.journalPatterns(), [])

  return (
    <RequiresCapability capability={capability}>
      {() => {
        if (state.status === 'loading') return <Loading rows={3} label="patterns" />
        if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

        const { findings, sample } = state.data
        if (!findings.length) {
          return (
            <Empty
              hint={
                sample
                  ? `${sample} entries examined, no pattern reached its confidence threshold. A detector that fires on a thin sample is worse than one that stays quiet.`
                  : 'Detectors run over recorded entries. There are none yet.'
              }
            >
              no patterns detected
            </Empty>
          )
        }

        return (
          <PanelBody>
            <div className="label" style={{ color: 'var(--ink-ghost)' }}>
              over {sample} entries · deterministic detectors, no model
            </div>
            {findings.map((finding, index) => (
              <Section key={index} title={String(finding.name ?? finding.kind ?? 'finding')} dense>
                <div style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)', lineHeight: 1.55 }}>
                  {String(finding.summary ?? finding.claim ?? '')}
                </div>
                <div className="flex gap-2 items-center">
                  {finding.confidence !== undefined && (
                    <Chip tone={Number(finding.confidence) > 0.7 ? 'good' : 'warn'}>
                      confidence {Number(finding.confidence).toFixed(2)}
                    </Chip>
                  )}
                  {finding.n !== undefined && (
                    <span className="label">n={String(finding.n)}</span>
                  )}
                </div>
              </Section>
            ))}
            <Caveats
              tone="info"
              items={[
                'A finding is a correlation over your own recorded trades, not a rule. It says what happened, not what will.',
              ]}
            />
          </PanelBody>
        )
      }}
    </RequiresCapability>
  )
}

// ---------------------------------------------------------------------------

/**
 * JD — the journal agents, by hand (Operating Model §1). Each button submits
 * the same task the planner or a workflow would, to the daemon's bus, so the
 * daemon's fully wired agent runs it. The Trade Journal has no button: it
 * records a fill, and there is nothing to record without one.
 */
const RUNS: { label: string; agent: string; args?: Record<string, unknown> }[] = [
  { label: 'Morning brief', agent: 'digest', args: { kind: 'morning' } },
  { label: 'Evening recap', agent: 'digest', args: { kind: 'evening' } },
  { label: 'Performance review', agent: 'performance-analyst', args: { days: 7 } },
  { label: 'Mine insights', agent: 'insight-miner' },
  { label: 'Health check', agent: 'watchdog' },
  { label: 'Drift check', agent: 'drift' },
]

type Run = { label: string; state: string; text?: string; data?: unknown; reason?: string }

export function JournalDeskPanel() {
  const [run, setRun] = useState<Run | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const lessons = useRead(() => api.journalLessons(), [])

  // ponytail: polls one task at 1s while it runs; switch to task events if the bus bridges them to the socket.
  useEffect(() => {
    if (!taskId) return
    const timer = setInterval(async () => {
      try {
        const t = await api.journalTask(taskId)
        if (!t.available) throw new Error(t.reason)
        if (!['done', 'failed', 'cancelled', 'shed'].includes(t.state)) {
          setRun((r) => (r ? { ...r, state: t.state } : r))
          return
        }
        clearInterval(timer)
        setTaskId(null)
        setRun((r) => r && {
          ...r, state: t.state,
          text: String(t.result?.spoken_summary ?? ''),
          data: t.result?.data,
          reason: t.failure ? String(t.failure.reason ?? 'failed') : undefined,
        })
        if (t.state === 'done') lessons.reload()
      } catch (err) {
        clearInterval(timer)
        setTaskId(null)
        setRun((r) => r && { ...r, state: 'failed', reason: String((err as Error).message ?? err) })
      }
    }, 1000)
    return () => clearInterval(timer)
  }, [taskId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function start(label: string, agent: string, args?: Record<string, unknown>) {
    setRun({ label, state: 'submitting' })
    try {
      const { task } = await api.journalRun(agent, args)
      if (!task) return setRun({ label, state: 'failed', reason: 'an identical task is already in flight' })
      setRun({ label, state: 'pending' })
      setTaskId(task)
    } catch (err) {
      setRun({ label, state: 'failed', reason: String((err as Error).message ?? err) })
    }
  }

  return (
    <PanelBody>
      <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
        {RUNS.map((r) => (
          <button key={r.label} className="btn" disabled={taskId !== null}
            onClick={() => start(r.label, r.agent, r.args)}>
            {r.label}
          </button>
        ))}
      </div>

      {run && (
        <Section title={run.label} dense
          actions={<Chip tone={run.state === 'done' ? 'good' : run.state === 'failed' ? 'bad' : 'neutral'}>{run.state}</Chip>}>
          {run.reason && <Caveats items={[run.reason]} />}
          {run.text && (
            <div style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)', lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>
              {run.text}
            </div>
          )}
          {run.state === 'done' && run.data !== undefined && (
            <details>
              <summary className="label">data</summary>
              <pre style={{ fontSize: 'var(--fs-tiny)', whiteSpace: 'pre-wrap' }}>{JSON.stringify(run.data, null, 2)}</pre>
            </details>
          )}
        </Section>
      )}

      {lessons.state.status === 'loading' && <Loading rows={2} label="lessons" />}
      {lessons.state.status !== 'loading' && lessons.state.status !== 'ready' && (
        <Absent reason={lessons.state.reason} onRetry={lessons.reload} />
      )}
      {lessons.state.status === 'ready' && (
        <>
          <Section title={`Lessons · ${lessons.state.data.lessons.length}`} dense>
            {lessons.state.data.lessons.length
              ? lessons.state.data.lessons.map((l, i) => (
                <div key={i} style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)' }}>
                  <b style={{ color: 'var(--ink)' }}>{String(l.title ?? '')}</b> {String(l.finding ?? '')}
                </div>
              ))
              : <span className="label">none yet — a lesson needs at least 20 observations</span>}
          </Section>
          <Section title={`Hypotheses · ${lessons.state.data.hypotheses.length}`} dense>
            {lessons.state.data.hypotheses.map((h, i) => (
              <div key={i} style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)' }}>
                {String(h.finding ?? h.key ?? 'hypothesis')}
              </div>
            ))}
          </Section>
        </>
      )}
    </PanelBody>
  )
}

// ---------------------------------------------------------------------------

/**
 * `JM` — the ranges of candles you marked, newest first.
 *
 * The one part of the journal a person authors. Picking one opens the chart on
 * that series so the bars it was drawn over are back on screen; the zone
 * itself is still a saved drawing there.
 */
export function JournalMarksPanel() {
  const { select } = useWorkspace()
  const { state, reload } = useRead(() => api.journalMarks(), [])

  if (state.status === 'loading') return <Loading rows={4} label="marks" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  const marks = state.data.marks
  if (!marks.length) {
    return (
      <Empty hint="Draw a zone over the bars on CH, select it, and press journal — an entry, an exit, or an idea you did not take.">
        nothing marked yet
      </Empty>
    )
  }

  return (
    <PanelBody pad={0}>
      <Table
        rows={marks as unknown as Record<string, unknown>[]}
        keyOf={(row) => String(row.id)}
        onSelect={(row) => {
          const detail = row.detail as { symbol: string; timeframe: string; series: string }
          const [symbolId] = String(detail.series || '').split('|')
          select({ symbolId: symbolId || detail.symbol, timeframe: detail.timeframe })
          revealPanel('chart')
        }}
        columns={[
          {
            key: 'kind', header: '', width: 52,
            render: (row) => (
              <Chip tone={row.outcome === 'exit' ? 'warn' : row.outcome === 'entry' ? 'good' : 'neutral'}>
                {String(row.outcome)}
              </Chip>
            ),
          },
          {
            key: 'symbol', header: 'symbol', width: 66,
            render: (row) => <span style={{ color: 'var(--ink)' }}>{String(row.subject)}</span>,
          },
          {
            key: 'note', header: 'note',
            render: (row) => {
              const detail = row.detail as { note: string; entry_id: string }
              return (
                <span className="flex items-center gap-1" style={{ overflow: 'hidden' }}>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{detail.note || '—'}</span>
                  {detail.entry_id && <Chip tone="neutral">on a trade</Chip>}
                </span>
              )
            },
          },
          {
            key: 'at', header: 'marked', width: 84, align: 'right',
            render: (row) => <span className="num">{String(row.at).slice(0, 10)}</span>,
          },
        ]}
      />
    </PanelBody>
  )
}
