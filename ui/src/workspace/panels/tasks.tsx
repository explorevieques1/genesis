// Spec: Genesis Markdown/60-UI/Task Manager.md
//
// TM — what Genesis is working on, right now, from wherever you are standing.
//
// The bug this exists for: a question asked on Home looked like it *stopped*
// when you changed pages. It never stopped. The dock rebuilds its panels per
// page (`Workspace.tsx`), so the panel holding the in-flight turn unmounted and
// took the only evidence of the work with it. The daemon kept running, the
// answer was still written — the surface simply forgot to be looking.
//
// So this panel holds no state of its own. Every row comes from the store's
// task ledger, which is fed by the WebSocket at app level and therefore
// outlives any page. That is the actual fix: work in flight has a home that is
// not a page.
//
// It reads. There is no cancel button, because there is no cancel path on the
// bus — a button that appeared to stop a task it cannot reach would be a
// proprioceptive lie (Biological Design §3), and a worse bug than the one this
// panel closes.

import { useMemo } from 'react'
import { Empty } from '@/components/States'
import { Chip, PanelBody, Table, type Column } from '@/components/Primitives'
import { ago, elapsed, money } from '@/lib/format'
import { useGenesis } from '@/store/useGenesis'
import type { TaskRecord } from '@/types/fleet'

const STATE_TONE = {
  dispatched: 'neutral',
  running: 'good',
  done: 'neutral',
  failed: 'bad',
} as const

export function TaskManagerPanel() {
  const tasks = useGenesis((s) => s.tasks)
  const taskOrder = useGenesis((s) => s.taskOrder)
  const selected = useGenesis((s) => s.selection.taskId)
  const select = useGenesis((s) => s.select)
  const now = Date.now()

  // Newest first, in flight above finished. The question this panel answers is
  // "what is happening", and a completed task is history the moment it lands.
  const rows = useMemo(() => {
    const all = taskOrder.map((id) => tasks[id]).filter(Boolean) as TaskRecord[]
    const live = (t: TaskRecord) => t.state === 'dispatched' || t.state === 'running'
    return [...all].sort((a, b) =>
      Number(live(b)) - Number(live(a)) || b.dispatchedAt - a.dispatchedAt,
    )
  }, [tasks, taskOrder])

  const inFlight = rows.filter((t) => t.state === 'dispatched' || t.state === 'running').length

  const columns: Column<TaskRecord>[] = [
    {
      key: 'state', header: 'state', width: 84,
      render: (t) => <Chip tone={STATE_TONE[t.state]}>{t.state}</Chip>,
    },
    { key: 'agent', header: 'agent', render: (t) => t.agent },
    { key: 'type', header: 'task', render: (t) => t.type },
    {
      key: 'took', header: 'took', align: 'right', width: 72,
      // A running task shows how long it has been running, not a blank. The
      // blank is what made a working system look like a stalled one.
      render: (t) =>
        t.wallMs !== null
          ? elapsed(t.wallMs)
          : t.startedAt !== null
            ? elapsed(now - t.startedAt)
            : '—',
    },
    {
      key: 'cost', header: 'cost', align: 'right', width: 72,
      render: (t) => (t.costUsd ? money(t.costUsd, { prefix: '$' }) : '—'),
    },
    { key: 'when', header: 'dispatched', align: 'right', width: 84, render: (t) => ago(now - t.dispatchedAt) },
    {
      key: 'why', header: 'result',
      // A failure says why, here, rather than only in the event stream. The
      // whole point of the panel is that you do not have to have been watching.
      render: (t) => t.failure ? `${t.failure.failureClass}: ${t.failure.code}` : (t.summary ?? '—'),
    },
  ]

  return (
    <PanelBody>
      <div className="label" style={{ padding: '0 2px 6px', color: 'var(--ink-faint)' }}>
        {inFlight ? `${inFlight} in flight` : 'nothing in flight'} · {rows.length} this session
      </div>
      <Table
        rows={rows}
        columns={columns}
        keyOf={(t) => t.id}
        selectedKey={selected}
        // Selecting a task selects its trace too, so TR opens on the right one.
        onSelect={(t) => select({ taskId: t.id, traceId: t.traceId, agentId: t.agent })}
        empty={
          <Empty hint="Ask Genesis something — every task it dispatches shows up here, on any page.">
            No task has been dispatched this session.
          </Empty>
        }
      />
    </PanelBody>
  )
}
