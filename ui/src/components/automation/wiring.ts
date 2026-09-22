// Spec: Genesis Markdown/70-Schemas/Workflow Schema.md
//
// The wiring rules, as pure functions over a workflow body. The canvas asks
// these before it draws an edge, so a refused connection is refused with a
// reason in the browser — and the server's validator says the same thing again,
// because the canvas is a convenience and the server is the rule.
//
// A chain: one `next` per step, a check also has `on_fail`, nothing has two
// parents, nothing loops.

import type { WorkflowBody, WorkflowStep } from '@/api/client'

export const TRIGGER = 'trigger'
export type Handle = 'next' | 'on_fail'

/** Who points at `id` — the trigger, or a step's `next` / `on_fail`. */
export function parentOf(wf: WorkflowBody, id: string): string | null {
  if (wf.start === id) return TRIGGER
  const p = wf.steps.find((s) => s.next === id || s.on_fail === id)
  return p ? p.id : null
}

/** Does a step have a fail exit? Checks always; built-in nodes when the catalogue says so. */
export type CanBranch = (step: WorkflowStep) => boolean
const checksOnly: CanBranch = (step) => step.kind === 'check'

/** Null when the connection is allowed; otherwise the reason it is not. */
export function refuse(
  wf: WorkflowBody, source: string, handle: Handle, target: string, canBranch: CanBranch = checksOnly,
): string | null {
  if (target === TRIGGER) return 'nothing connects into the trigger'
  if (source === target) return 'a step cannot follow itself'
  if (source !== TRIGGER) {
    const step = wf.steps.find((s) => s.id === source)
    if (!step) return `unknown step ${source}`
    if (handle === 'on_fail' && !canBranch(step)) return 'only a check or a pass/fail node has a fail branch'
  }
  const owner = parentOf(wf, target)
  if (owner !== null && owner !== source) return 'a step has one previous step — use a check for a branch'
  // Walk forward from the target: reaching the source means a loop.
  const seen = new Set<string>()
  const stack = [target]
  while (stack.length) {
    const at = stack.pop() as string
    if (at === source) return 'that would make a loop'
    if (seen.has(at)) continue
    seen.add(at)
    const s = wf.steps.find((x) => x.id === at)
    if (s?.next) stack.push(s.next)
    if (s?.on_fail) stack.push(s.on_fail)
  }
  return null
}

/** Connect, replacing whatever that handle pointed at before. */
export function connect(wf: WorkflowBody, source: string, handle: Handle, target: string): WorkflowBody {
  const cleared = disconnectInto(wf, target)
  if (source === TRIGGER) return { ...cleared, start: target }
  return {
    ...cleared,
    steps: cleared.steps.map((s) => (s.id === source ? { ...s, [handle]: target } : s)),
  }
}

/** Remove the edge leaving `source` through `handle`. */
export function disconnect(wf: WorkflowBody, source: string, handle: Handle): WorkflowBody {
  if (source === TRIGGER) return { ...wf, start: null }
  return { ...wf, steps: wf.steps.map((s) => (s.id === source ? { ...s, [handle]: null } : s)) }
}

function disconnectInto(wf: WorkflowBody, target: string): WorkflowBody {
  return {
    ...wf,
    start: wf.start === target ? null : wf.start,
    steps: wf.steps.map((s) => ({
      ...s,
      next: s.next === target ? null : s.next,
      on_fail: s.on_fail === target ? null : s.on_fail,
    })),
  }
}

/** Steps the trigger can reach. The rest render dimmed: they will not run. */
export function reachable(wf: WorkflowBody): Set<string> {
  const out = new Set<string>()
  let frontier = wf.start ? [wf.start] : []
  while (frontier.length) {
    const next: string[] = []
    for (const id of frontier) {
      if (out.has(id)) continue
      out.add(id)
      const s = wf.steps.find((x) => x.id === id)
      if (s?.next) next.push(s.next)
      if (s?.on_fail) next.push(s.on_fail)
    }
    frontier = next
  }
  return out
}

/** Earlier steps on this step's path — what its `input` may name. */
export function ancestors(wf: WorkflowBody, id: string): string[] {
  const out: string[] = []
  let at = parentOf(wf, id)
  while (at && at !== TRIGGER && !out.includes(at)) {
    out.push(at)
    at = parentOf(wf, at)
  }
  return out
}

/** Remove a step and every edge that touched it. */
export function removeStep(wf: WorkflowBody, id: string): WorkflowBody {
  const cleared = disconnectInto(wf, id)
  const layout = { ...cleared.layout }
  delete layout[id]
  return {
    ...cleared,
    layout,
    steps: cleared.steps
      .filter((s) => s.id !== id)
      .map((s) => (s.input === id ? { ...s, input: null } : s)),
  }
}

/** A fresh step from a palette preset, with a readable unique id. */
export function newStep(wf: WorkflowBody, preset: Partial<WorkflowStep>): WorkflowStep {
  const kind = preset.kind ?? 'action'
  const stem = (preset.action ?? preset.capability ?? kind).split('.').pop() ?? kind
  const base = stem.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || kind
  let n = 1
  while (wf.steps.some((s) => s.id === `${base}-${n}`) || `${base}-${n}` === TRIGGER) n++
  const step: WorkflowStep = { ...preset, id: `${base}-${n}`, kind }
  if (kind === 'check' && !step.predicate) step.predicate = 'non_empty'
  if (kind === 'refresh' && !step.target) step.target = 'vault-map'
  if (kind === 'action') step.params = { ...(preset.params ?? {}) }
  return step
}

/** One line under the node's label. */
export function summary(step: WorkflowStep): string {
  const show = (v: unknown) => (Array.isArray(v) ? v.join(',') : typeof v === 'boolean' ? (v ? 'yes' : 'no') : String(v))
  switch (step.kind) {
    case 'gather': {
      const q = step.args && Object.values(step.args)[0]
      return `${step.capability ?? 'choose a tool'}${q !== undefined ? ` · ${show(q)}` : ''}`
    }
    case 'check':
      if (step.predicate === 'min_count') return `at least ${step.value ?? '?'}`
      if (step.predicate === 'compare') return `${step.field ?? '?'} ${step.op ?? '?'} ${step.value ?? '?'}`
      return 'not empty'
    case 'refresh':
      return step.target ?? 'choose a target'
    case 'run':
      return step.agent ?? 'choose an agent'
    case 'action': {
      const values = Object.values(step.params ?? {}).filter((v) => v !== '' && v !== null && v !== undefined)
      const text = values.slice(0, 3).map(show).join(' · ')
      return `${step.each ? 'each · ' : ''}${text || 'no settings'}`
    }
  }
}

export function triggerSummary(t: WorkflowBody['trigger']): string {
  if (t.type === 'cron') return `daily at ${t.at ?? '?'} ET`
  if (t.type === 'market-open') return `market hours · every ${Math.round((t.interval_sec ?? 0) / 60)} min`
  if (t.type === 'market-closed') return `market closed · every ${Math.round((t.interval_sec ?? 0) / 60)} min`
  if (t.type === 'event') return `on ${(t.on ?? []).join(', ') || '?'}`
  return 'when run by hand'
}

/** Does a grant pattern (`news.*` or exact) cover a capability? Mirrors `allowlist.matches`. */
export function granted(grant: string[], capability: string): boolean {
  return grant.some((p) => (p.endsWith('.*') ? capability.startsWith(p.slice(0, -1)) : p === capability))
}
