// Spec: Genesis Markdown/60-UI/Automation.md §Visual design
//
// One node on the workflow canvas: the trigger, or a step.
//
// Same anatomy as the research canvas's EntityNode — panel ground, a 3px accent,
// the category as a label — so the two canvases read as one visual system. What
// is added is what a workflow needs and a graph does not: a pass/fail node has
// two exits, a node that writes says so, the node wears its last run's outcome,
// and a node the trigger cannot reach says it will not run rather than looking
// fine.

import { memo } from 'react'
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'

export type RunMark = 'ok' | 'failed' | 'skipped' | null

export interface StepNodeData extends Record<string, unknown> {
  category: string
  title: string
  stepId: string
  summary: string
  selected: boolean
  reachable: boolean
  trigger: boolean
  branches: boolean
  writes: boolean
  run: RunMark
  runReason?: string
}

export type StepFlowNode = Node<StepNodeData, 'step'>

/** Colour and glyph per palette category. Families' tokens, so colours mean the same thing everywhere. */
export const CATEGORY: Record<string, { colour: string; glyph: string }> = {
  triggers: { colour: 'var(--core)', glyph: '⏰' },
  market: { colour: 'var(--family-charting)', glyph: '📈' },
  signals: { colour: 'var(--state-blocked)', glyph: '🎯' },
  news: { colour: 'var(--family-research)', glyph: '📰' },
  fundamentals: { colour: 'var(--family-research)', glyph: '🏛' },
  filings: { colour: 'var(--family-research)', glyph: '📄' },
  calendar: { colour: 'var(--family-core)', glyph: '🗓' },
  screeners: { colour: 'var(--family-charting)', glyph: '🔎' },
  technicals: { colour: 'var(--family-charting)', glyph: '📐' },
  research: { colour: 'var(--family-strategy)', glyph: '🤖' },
  journal: { colour: 'var(--family-journal)', glyph: '📓' },
  watchlist: { colour: 'var(--family-core)', glyph: '👁' },
  logic: { colour: 'var(--state-blocked)', glyph: '⑂' },
  transform: { colour: 'var(--ink-faint)', glyph: '⚙' },
  output: { colour: 'var(--state-degraded)', glyph: '🔔' },
  maintenance: { colour: 'var(--family-journal)', glyph: '🔄' },
  custom: { colour: 'var(--core-flare, var(--core))', glyph: '🧩' },
}

export const styleOf = (category: string) => CATEGORY[category] ?? { colour: 'var(--ink-faint)', glyph: '•' }

const RUN_COLOUR: Record<Exclude<RunMark, null>, string> = {
  ok: 'var(--verdict-pass)',
  failed: 'var(--state-down)',
  skipped: 'var(--ink-ghost)',
}

// global.css hides every handle for the Fleet View, which is read-only. Here a
// handle is the whole gesture, so it is switched back on inline.
const handle = {
  width: 10, height: 10, border: '2px solid var(--bg-panel)', opacity: 1, pointerEvents: 'all' as const,
}

export const StepNode = memo(function StepNode({ data }: NodeProps<StepFlowNode>) {
  const { category, title, stepId, summary, selected, reachable, trigger, branches, writes, run, runReason } = data
  const style = styleOf(category)

  return (
    <div
      title={!reachable ? 'not connected to the trigger — this step will not run' : runReason}
      style={{
        width: 210,
        background: 'var(--bg-panel)',
        border: `1px solid ${selected ? 'var(--core-hot)' : run === 'failed' ? RUN_COLOUR.failed : 'var(--hairline)'}`,
        borderLeft: `3px solid ${style.colour}`,
        borderRadius: trigger ? 14 : 4,
        padding: '6px 9px 7px',
        boxShadow: selected ? 'var(--shadow-lg)' : 'none',
        opacity: reachable ? 1 : 0.45,
      }}
    >
      {!trigger ? (
        <Handle type="target" position={Position.Left} style={{ ...handle, background: 'var(--ink-faint)' }} />
      ) : null}

      <div className="flex items-center gap-1" style={{ marginBottom: 2 }}>
        <span aria-hidden>{style.glyph}</span>
        <span className="label" style={{ color: style.colour, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {trigger ? 'trigger' : category}
        </span>
        {writes ? (
          <span className="label" title="changes something outside the run"
            style={{ color: 'var(--state-degraded)', letterSpacing: 0 }}>· writes</span>
        ) : null}
        <span style={{ flex: 1 }} />
        {run ? (
          <span className="label" aria-label={`last run: ${run}`} style={{ color: RUN_COLOUR[run], letterSpacing: 0 }}>
            {run === 'ok' ? '●' : run === 'failed' ? '✕' : '○'}
          </span>
        ) : null}
      </div>

      <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)', lineHeight: 1.3, paddingRight: branches ? 30 : 0 }}>
        {title}
      </div>
      <div
        className="label"
        style={{
          color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0, marginTop: 2,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', paddingRight: branches ? 30 : 0,
        }}
      >
        {reachable ? summary : 'not connected — won’t run'}
      </div>
      {!trigger ? (
        <div className="num" style={{ fontSize: 9, color: 'var(--ink-ghost)', marginTop: 2 }}>{stepId}</div>
      ) : null}

      {branches ? (
        <>
          <Handle id="next" type="source" position={Position.Right}
            style={{ ...handle, top: '35%', background: 'var(--verdict-pass)' }} />
          <Handle id="on_fail" type="source" position={Position.Right}
            style={{ ...handle, top: '72%', background: 'var(--state-degraded)' }} />
          <div className="label" style={{ position: 'absolute', right: 9, top: 'calc(35% - 7px)', color: 'var(--verdict-pass)', letterSpacing: 0 }}>pass</div>
          <div className="label" style={{ position: 'absolute', right: 9, top: 'calc(72% - 7px)', color: 'var(--state-degraded)', letterSpacing: 0 }}>fail</div>
        </>
      ) : (
        <Handle id="next" type="source" position={Position.Right} style={{ ...handle, background: style.colour }} />
      )}
    </div>
  )
})
