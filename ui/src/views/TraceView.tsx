// Spec: Genesis Markdown/60-UI/Fleet View.md §Trace mode · Genesis Markdown/10-Architecture/Observability.md
//
// The centrepiece. Select any event and the surface filters to a single
// `trace_id`: the causal chain from the words you said to every task, tool call,
// memory write and event that descended from them, replayable on a scrub bar.
//
// The reconstruction is by `parent_task_id` alone. Without it the graph can show
// activity but not causation, which is half the value — so a task whose parent is
// missing is shown as an orphan at the root rather than silently reparented onto
// the orchestrator. Inventing a parent would be inventing causation.
//
// This is the same data the Episodic Log holds permanently, so trace mode works
// on a question from three weeks ago exactly as it works on the live one. Live is
// just the trace whose end has not been written yet.

import { memo, useMemo } from 'react'
import { useGenesis } from '@/store/useGenesis'
import { AGENTS_BY_ID, ORCHESTRATOR_ID } from '@/data/roster'
import type { TaskRecord } from '@/types/fleet'
import { clock, elapsed, money } from '@/lib/format'

interface TreeNode { task: TaskRecord; depth: number; orphan: boolean }

/** Depth-first flatten by parent_task_id, preserving dispatch order. */
function buildTree(tasks: TaskRecord[]): TreeNode[] {
  const byId = new Map(tasks.map((t) => [t.id, t]))
  const children = new Map<string | null, TaskRecord[]>()
  const out: TreeNode[] = []

  for (const t of tasks) {
    // A parent outside this trace's window is not a root — it is an orphan, and
    // it is labelled as one. The chain is incomplete and the operator is told.
    const key = t.parentId && byId.has(t.parentId) ? t.parentId : null
    const list = children.get(key) ?? []
    list.push(t)
    children.set(key, list)
  }
  for (const list of children.values()) list.sort((a, b) => a.dispatchedAt - b.dispatchedAt)

  const walk = (parent: string | null, depth: number) => {
    for (const t of children.get(parent) ?? []) {
      out.push({ task: t, depth, orphan: parent === null && t.parentId !== null })
      walk(t.id, depth + 1)
    }
  }
  walk(null, 0)
  return out
}

export const TraceView = memo(function TraceView({ now }: { now: number }) {
  const traceId = useGenesis((s) => s.selection.traceId)
  const selectedTaskId = useGenesis((s) => s.selection.taskId)
  const tasks = useGenesis((s) => s.tasks)
  const events = useGenesis((s) => s.events)
  const replayAt = useGenesis((s) => s.replayAt)
  const setReplayAt = useGenesis((s) => s.setReplayAt)
  const select = useGenesis((s) => s.select)

  const traceTasks = useMemo(
    () => Object.values(tasks).filter((t) => t.traceId === traceId),
    [tasks, traceId],
  )
  const traceEvents = useMemo(
    () => events.filter((e) => e.trace_id === traceId).slice().reverse(),
    [events, traceId],
  )

  const tree = useMemo(() => buildTree(traceTasks), [traceTasks])

  const span = useMemo(() => {
    if (traceTasks.length === 0) return null
    const t0 = Math.min(...traceTasks.map((t) => t.dispatchedAt))
    const ends = traceTasks.map((t) => t.endedAt ?? now)
    return { t0, t1: Math.max(...ends), open: traceTasks.some((t) => t.endedAt === null) }
  }, [traceTasks, now])

  if (!traceId) {
    return (
      <div style={{ padding: 14, fontSize: 'var(--fs-tiny)', color: 'var(--ink-faint)', maxWidth: 520 }}>
        <div className="label" style={{ marginBottom: 6 }}>trace mode</div>
        Select any line in the event stream — or any task in the inspector — to reconstruct exactly
        how it moved through the fleet.
        <div style={{ marginTop: 8, color: 'var(--ink-ghost)' }}>
          The chain is rebuilt from <span className="num">parent_task_id</span> alone. A task whose
          parent is outside the window is shown as an orphan rather than reparented — inventing a
          parent would be inventing causation.
        </div>
      </div>
    )
  }

  const cursor = replayAt ?? span?.t1 ?? now
  const total = span ? Math.max(1, span.t1 - span.t0) : 1

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 px-3 py-[6px] hairline-b" style={{ flexShrink: 0 }}>
        <span className="label">trace</span>
        <span className="num" style={{ fontSize: 'var(--fs-sm)', color: 'var(--core-hot)' }}>{traceId}</span>
        <span className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)' }}>
          {traceTasks.length} tasks · {traceEvents.length} events
          {span?.open && ' · still open'}
        </span>
        <button
          onClick={() => { select({ traceId: null }); setReplayAt(null) }}
          className="ml-auto"
          style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)' }}
        >
          exit trace
        </button>
      </div>

      {span && (
        <div className="flex items-center gap-2 px-3 py-[5px] hairline-b" style={{ flexShrink: 0 }}>
          <button
            onClick={() => setReplayAt(replayAt === null ? span.t0 : null)}
            style={{
              fontSize: 'var(--fs-micro)', letterSpacing: '0.08em',
              border: '1px solid var(--hairline-bright)', borderRadius: 'var(--r-sm)',
              padding: '1px 8px', color: replayAt === null ? 'var(--ink-dim)' : 'var(--core-hot)',
            }}
          >
            {replayAt === null ? 'REPLAY' : 'LIVE'}
          </button>
          <input
            type="range"
            min={span.t0}
            max={span.t1}
            value={cursor}
            onChange={(e) => setReplayAt(Number(e.target.value))}
            style={{ flex: 1, accentColor: 'var(--core)' }}
            aria-label="Trace replay position"
          />
          <span className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', width: 92 }}>
            +{elapsed(cursor - span.t0)}
          </span>
        </div>
      )}

      <div className="scroll-y flex-1 min-h-0">
        {tree.length === 0 && (
          <div style={{ padding: 12, fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)' }}>
            No task lifecycle events retained for this trace. The Episodic Log holds it permanently;
            this window does not.
          </div>
        )}
        {tree.map(({ task, depth, orphan }) => {
          const spec = AGENTS_BY_ID.get(task.agent)
          const started = task.startedAt ?? task.dispatchedAt
          const ended = task.endedAt ?? (replayAt === null ? now : cursor)
          // Under replay, a task that had not been dispatched yet is not drawn as
          // faint — it is not drawn as complete either. It is drawn as pending.
          const pending = task.dispatchedAt > cursor
          const running = !pending && task.endedAt === null
          const left = span ? ((started - span.t0) / total) * 100 : 0
          const width = span ? Math.max(0.6, ((Math.min(ended, cursor) - started) / total) * 100) : 0
          return (
            <button
              key={task.id}
              onClick={() => select({ taskId: task.id, agentId: task.agent })}
              className="w-full text-left flex items-center gap-2 px-3"
              style={{
                padding: '2px 12px',
                opacity: pending ? 0.28 : 1,
                background: selectedTaskId === task.id ? 'color-mix(in oklab, var(--core) 12%, transparent)' : undefined,
              }}
              title={`${task.type} · lane ${task.lane} · ${task.id}`}
            >
              <span
                className="num truncate"
                style={{
                  width: 250, flexShrink: 0, fontSize: 'var(--fs-micro)',
                  paddingLeft: depth * 12,
                  color: task.state === 'failed' ? 'var(--state-down)' : 'var(--ink-dim)',
                }}
              >
                <span style={{ color: spec ? `var(--family-${spec.family})` : 'var(--family-core)' }}>
                  {depth > 0 ? '└ ' : ''}
                </span>
                {task.agent === ORCHESTRATOR_ID ? 'orchestrator' : spec?.name ?? task.agent}
                <span style={{ color: 'var(--ink-ghost)' }}> · {task.type}</span>
                {orphan && <span style={{ color: 'var(--state-blocked)' }}> ⟂ orphan</span>}
              </span>

              <span className="relative flex-1" style={{ height: 10, background: 'var(--bg-inset)' }}>
                <span
                  className={running ? 'anim-pulse' : ''}
                  style={{
                    position: 'absolute', top: 2, height: 6,
                    left: `${left}%`, width: `${width}%`,
                    background: task.state === 'failed' ? 'var(--state-down)'
                      : running ? 'var(--state-working)' : 'var(--verdict-pass)',
                    borderRadius: 1,
                  }}
                />
              </span>

              <span className="num" style={{ width: 62, flexShrink: 0, fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)', textAlign: 'right' }}>
                {task.wallMs !== null ? elapsed(task.wallMs) : pending ? 'pending' : 'running'}
              </span>
              <span className="num" style={{ width: 54, flexShrink: 0, fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)', textAlign: 'right' }}>
                {task.costUsd ? money(task.costUsd, { prefix: '$' }) : '—'}
              </span>
            </button>
          )
        })}
      </div>

      <div className="hairline-t scroll-y" style={{ flexShrink: 0, maxHeight: 150 }}>
        <div className="label" style={{ padding: '5px 12px 2px' }}>events in this trace</div>
        {traceEvents.map((e) => (
          <div key={e.id} className="flex gap-2 px-3" style={{ fontSize: 'var(--fs-micro)', opacity: Date.parse(e.ts) > cursor ? 0.45 : 1 }}>
            <span className="num" style={{ color: 'var(--ink-ghost)' }}>{clock(e.ts).slice(0, 12)}</span>
            <span className="num" style={{ color: 'var(--ink-faint)' }}>{e.event}</span>
            <span className="num truncate" style={{ color: 'var(--ink-ghost)' }}>{e.source}</span>
          </div>
        ))}
      </div>
    </div>
  )
})
