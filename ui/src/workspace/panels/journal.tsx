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

import { api, type GraphEdge, type GraphNode } from '@/api/client'
import { useRead } from '@/api/useRead'
import { useCapability } from '@/api/capabilities'
import { Absent, Empty, Loading, RequiresCapability } from '@/components/States'
import { Caveats, Chip, Num, PanelBody, Section, Table } from '@/components/Primitives'
import { ForceGraph } from '@/components/graph/ForceGraph'
import { useWorkspace } from '@/workspace/context'

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
              keyOf={(row, i) => `entry:${row.entry_id ?? i}`}
              selectedKey={nodeId}
              onSelect={(row) => select({ nodeId: `entry:${row.entry_id}` })}
              columns={[
                {
                  key: 'when', header: 'opened', width: 84,
                  render: (row) => (
                    <span className="num">{String(row.opened_at ?? '').slice(0, 10)}</span>
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
                    const outcome = String(row.outcome ?? '')
                    return outcome ? (
                      <Chip tone={outcome === 'WIN' ? 'good' : outcome === 'LOSS' ? 'bad' : 'neutral'}>
                        {outcome}
                      </Chip>
                    ) : null
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
