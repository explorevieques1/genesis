// Spec: Genesis Markdown/70-Schemas/Workflow Schema.md
//
// The canvas's connection rules, checked. Run it with:
//
//     npm run check:automation

import assert from 'node:assert/strict'
import type { WorkflowBody } from '../../api/client.ts'
import { ancestors, connect, newStep, reachable, refuse, removeStep, summary, TRIGGER } from './wiring.ts'

const wf: WorkflowBody = {
  id: 'w', name: 'w', trigger: { type: 'cron', at: '07:00' }, layout: {},
  start: 'a',
  steps: [
    { id: 'a', kind: 'gather', capability: 'news.search', next: 'b' },
    { id: 'b', kind: 'check', input: 'a', predicate: 'non_empty', next: 'c', on_fail: 'd' },
    { id: 'c', kind: 'run', agent: 'topic-researcher' },
    { id: 'd', kind: 'run', agent: 'digest' },
    { id: 'e', kind: 'refresh', target: 'vault-map' },
  ],
}

// a branch comes only from a check
assert.match(refuse(wf, 'a', 'on_fail', 'e') ?? '', /only a check/)
// …unless the catalogue says the node branches
assert.equal(refuse(wf, 'a', 'on_fail', 'e', (s) => s.kind === 'gather'), null)
// fan-in is refused
assert.match(refuse(wf, 'c', 'next', 'd') ?? '', /one previous step/)
// a loop is refused
assert.match(refuse(wf, 'c', 'next', 'a') ?? '', /one previous step|loop/)
assert.match(refuse({ ...wf, start: null }, 'c', 'next', 'a') ?? '', /loop/)
// nothing into the trigger, nothing onto itself
assert.ok(refuse(wf, 'c', 'next', TRIGGER))
assert.ok(refuse(wf, 'e', 'next', 'e'))
// a free step may be chained
assert.equal(refuse(wf, 'c', 'next', 'e'), null)

// reachability dims the orphan
assert.deepEqual([...reachable(wf)].sort(), ['a', 'b', 'c', 'd'])
assert.ok(reachable(connect(wf, 'c', 'next', 'e')).has('e'))

// input may only name what came before
assert.deepEqual(ancestors(wf, 'c'), ['b', 'a'])

// removing a step removes its edges and any input that named it
const cut = removeStep(wf, 'a')
assert.equal(cut.start, null)
assert.equal(cut.steps.find((s) => s.id === 'b')?.input, null)

// new steps get readable, unique ids from their preset
const a1 = newStep(wf, { kind: 'action', action: 'signal.price', params: { symbol: 'NVDA' } })
assert.equal(a1.id, 'price-1')
assert.equal(newStep({ ...wf, steps: [...wf.steps, a1] }, { kind: 'action', action: 'signal.price' }).id, 'price-2')
assert.equal(newStep(wf, { kind: 'gather', capability: 'news.company' }).id, 'company-1')
assert.equal(summary({ ...a1, params: { symbol: 'NVDA', direction: 'above', level: 250 } }), 'NVDA · above · 250')

console.log('automation wiring: ok')
