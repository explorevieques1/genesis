// Spec: Genesis Markdown/60-UI/Automation.md §Visual design · §Node library
//
// WB — the workflow builder. n8n's editor with Obsidian Canvas's feel: a
// palette on the left, a pan-and-zoom canvas of nodes you wire together, and an
// inspector on the right holding the selected node's settings and what it did
// on its last run.
//
// The palette is the server's catalogue (`/v1/automation/catalog`), not a list
// kept here: tool nodes, built-in nodes, the classic step kinds and your own
// processes, grouped by category. A node's settings form comes from its
// definition — built-in nodes declare their settings, tool nodes are built from
// the tool's own JSON Schema — so what the canvas offers is what the runtime runs.
//
// The draft is local until Save, and Save appends a version — unlike the
// research canvas's single-fact writes. That is deliberate: a workflow is run
// as a whole, so a half-wired one must never be what the daemon picks up, and
// the version log is what makes "who changed this and what changed" answerable.
// Positions travel in the same body (`layout`), server-side, never localStorage.

import { useCallback, useEffect, useMemo, useState, type DragEvent, type ReactNode } from 'react'
import {
  Background, BackgroundVariant, Controls, MarkerType, MiniMap, ReactFlow, ReactFlowProvider,
  applyNodeChanges, useReactFlow,
  type Connection, type Edge, type NodeChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  api, type AutomationCatalog, type McpToolRow, type NodeParam, type PaletteNode, type WorkflowBody,
  type WorkflowRun, type WorkflowStep, type WorkflowTemplate, type WorkflowVersionRow,
} from '@/api/client'
import { useRead } from '@/api/useRead'
import { useCapability } from '@/api/capabilities'
import { Empty, Loading, Unbuilt } from '@/components/States'
import { Chip } from '@/components/Primitives'
import { StepNode, styleOf, type RunMark, type StepFlowNode } from '@/graph/nodes/StepNode'
import {
  TRIGGER, ancestors, connect, disconnect, granted, newStep, reachable, refuse, removeStep,
  summary, triggerSummary, type CanBranch, type Handle,
} from '@/components/automation/wiring'
import { kindOf } from '@/workspace/panels/tool'

const nodeTypes = { step: StepNode }
const DRAG_MIME = 'application/x-genesis-node'

export function WorkflowBuilderPanel({ params }: { params?: { workflowId?: string } }) {
  const capability = useCapability('automation.workflows')
  if (!capability) return <Loading rows={3} />
  if (!capability.built) return <Unbuilt capability={capability} />
  return (
    <ReactFlowProvider>
      <Builder initial={params?.workflowId ?? null} />
    </ReactFlowProvider>
  )
}

function slug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'workflow'
}

function blank(name: string, taken: Set<string>, process = false): WorkflowBody {
  let id = slug(name)
  for (let n = 2; taken.has(id); n++) id = `${slug(name)}-${n}`
  return {
    id, name, trigger: process ? { type: 'on-demand' } : { type: 'cron', at: '07:00' }, start: null, steps: [],
    layout: { [TRIGGER]: { x: 0, y: 120 } },
  }
}

/** Which palette entry a saved step came from — for its label, colour, settings and exits. */
function nodeFor(step: WorkflowStep, palette: PaletteNode[]): PaletteNode | undefined {
  if (step.kind === 'action') {
    if (step.action === 'flow.process') {
      return palette.find((n) => n.process && n.process === step.params?.workflow)
        ?? palette.find((n) => n.id === 'flow.process')
    }
    return palette.find((n) => n.kind === 'action' && !n.process && n.preset.action === step.action)
  }
  if (step.kind === 'gather') {
    return palette.find((n) => n.kind === 'gather' && n.capability === step.capability)
      ?? palette.find((n) => n.id === 'classic.gather')
  }
  if (step.kind === 'refresh') return palette.find((n) => n.kind === 'refresh' && n.preset.target === step.target)
  return palette.find((n) => n.kind === step.kind)
}

function defaults(node: PaletteNode): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const p of node.params ?? []) if (p.default !== null && p.default !== undefined && p.default !== '') out[p.name] = p.default
  return out
}

function Builder({ initial }: { initial: string | null }) {
  const flow = useReactFlow()
  const list = useRead(() => api.workflows(), [])
  const catalog = useRead(() => api.automationCatalog(), [])
  const templates = useRead(() => api.workflowTemplates(), [])

  const [openId, setOpenId] = useState<string | null>(initial)
  const [current, setCurrent] = useState<WorkflowVersionRow | null>(null)
  const [draft, setDraft] = useState<WorkflowBody | null>(null)
  const [dirty, setDirty] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [runs, setRuns] = useState<WorkflowRun[]>([])
  const [shownRun, setShownRun] = useState<WorkflowRun | null>(null)
  const [drawer, setDrawer] = useState<'history' | 'runs' | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const cat = catalog.state.status === 'ready' ? catalog.state.data : null
  const palette = useMemo(() => cat?.nodes ?? [], [cat])
  const canBranch = useCallback<CanBranch>(
    (step) => step.kind === 'check' || Boolean(step.kind === 'action' && nodeFor(step, palette)?.branches),
    [palette],
  )

  const say = (exc: unknown) => setError(exc instanceof Error ? exc.message : String(exc))

  const load = useCallback(async (id: string) => {
    setError(null); setNotice(null); setSelected(null); setDrawer(null)
    try {
      const [one, history] = await Promise.all([api.workflow(id), api.workflowRuns(id)])
      if (one.available === false) { setError(one.reason); return }
      setCurrent(one.workflow)
      setDraft(one.workflow.body)
      setDirty(false)
      const all = history.available === false ? [] : history.runs
      setRuns(all)
      setShownRun(all[0] ?? null)
    } catch (exc) { say(exc) }
  }, [])

  useEffect(() => { if (openId) void load(openId) }, [openId, load])

  // Edits go through one door so "unsaved" can never be wrong.
  const edit = useCallback((fn: (wf: WorkflowBody) => WorkflowBody) => {
    setDraft((wf) => (wf ? fn(wf) : wf))
    setDirty(true)
  }, [])

  const editStep = useCallback((id: string, patch: Partial<WorkflowStep>) => {
    edit((wf) => ({ ...wf, steps: wf.steps.map((s) => (s.id === id ? { ...s, ...patch } : s)) }))
  }, [edit])

  // -- the graph, derived from the draft ----------------------------------

  const live = useMemo(() => (draft ? reachable(draft) : new Set<string>()), [draft])
  const marks = useMemo(() => {
    const m = new Map<string, { status: RunMark; reason?: string }>()
    for (const s of shownRun?.steps ?? []) m.set(s.step, { status: s.status, reason: s.reason })
    return m
  }, [shownRun])

  const nodes = useMemo<StepFlowNode[]>(() => {
    if (!draft) return []
    const at = (id: string, i: number) => draft.layout[id] ?? { x: 270 * (i + 1), y: 120 }
    return [
      {
        id: TRIGGER, type: 'step', position: at(TRIGGER, -1), selected: selected === TRIGGER,
        deletable: false,
        data: {
          category: 'triggers', title: draft.trigger.type === 'on-demand' ? 'Process input' : 'Trigger',
          stepId: '', summary: triggerSummary(draft.trigger), selected: selected === TRIGGER, reachable: true,
          trigger: true, branches: false, writes: false,
          run: shownRun ? (shownRun.status === 'ok' ? 'ok' : 'failed') : null,
        },
      },
      ...draft.steps.map((s, i) => {
        const node = nodeFor(s, palette)
        return {
          id: s.id, type: 'step' as const, position: at(s.id, i), selected: selected === s.id,
          data: {
            category: node?.category ?? 'custom', title: node?.label ?? s.kind, stepId: s.id,
            summary: summary(s), selected: selected === s.id, reachable: live.has(s.id), trigger: false,
            branches: canBranch(s), writes: Boolean(node?.writes),
            run: marks.get(s.id)?.status ?? null, runReason: marks.get(s.id)?.reason,
          },
        }
      }),
    ]
  }, [draft, selected, live, marks, shownRun, palette, canBranch])

  const edges = useMemo<Edge[]>(() => {
    if (!draft) return []
    const out: Edge[] = []
    const line = (source: string, handle: Handle, target: string) => {
      const fail = handle === 'on_fail'
      const colour = fail ? 'var(--state-degraded)' : 'var(--hairline-bright)'
      out.push({
        id: `${source}|${handle}|${target}`, source, target, sourceHandle: handle,
        type: 'smoothstep', animated: live.has(target) && !dirty && Boolean(current?.enabled),
        label: fail ? 'fail' : undefined,
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: colour },
        style: { stroke: colour, strokeWidth: 1.4 },
        labelStyle: { fill: 'var(--state-degraded)', fontSize: 9 },
        labelBgStyle: { fill: 'var(--bg-panel)' },
      })
    }
    if (draft.start) line(TRIGGER, 'next', draft.start)
    for (const s of draft.steps) {
      if (s.next) line(s.id, 'next', s.next)
      if (s.on_fail) line(s.id, 'on_fail', s.on_fail)
    }
    return out
  }, [draft, live, dirty, current])

  // -- gestures -----------------------------------------------------------

  const onNodesChange = useCallback((changes: NodeChange<StepFlowNode>[]) => {
    for (const c of changes) {
      if (c.type !== 'select') continue
      if (c.selected) setSelected(c.id)
      else setSelected((s) => (s === c.id ? null : s))
    }
    const moved = applyNodeChanges(changes.filter((c) => c.type === 'position'), nodes)
    const positions = changes.filter((c) => c.type === 'position' && c.position)
    if (positions.length) {
      edit((wf) => {
        const layout = { ...wf.layout }
        for (const n of moved) layout[n.id] = { x: Math.round(n.position.x), y: Math.round(n.position.y) }
        return { ...wf, layout }
      })
    }
  }, [nodes, edit])

  const onConnect = useCallback((c: Connection) => {
    if (!draft || !c.source || !c.target) return
    const handle = (c.sourceHandle ?? 'next') as Handle
    const reason = refuse(draft, c.source, handle, c.target, canBranch)
    if (reason) { setError(reason); return }
    setError(null)
    edit((wf) => connect(wf, c.source, handle, c.target))
  }, [draft, edit, canBranch])

  const onEdgesDelete = useCallback((removed: Edge[]) => {
    edit((wf) => removed.reduce<WorkflowBody>((acc, e) => disconnect(acc, e.source, (e.sourceHandle ?? 'next') as Handle), wf))
  }, [edit])

  const onNodesDelete = useCallback((removed: { id: string }[]) => {
    edit((wf) => removed.filter((n) => n.id !== TRIGGER).reduce<WorkflowBody>((acc, n) => removeStep(acc, n.id), wf))
    setSelected(null)
  }, [edit])

  const addNode = useCallback((node: PaletteNode, position?: { x: number; y: number }) => {
    if (!draft) return
    const preset = node.kind === 'action'
      ? { ...node.preset, params: { ...defaults(node), ...(node.preset.params ?? {}) } }
      : node.preset
    const created = newStep(draft, preset)
    // A click appends to the chain, n8n-style: placed after the last step on
    // the trigger's path and wired to it. A drop lands where it was dropped,
    // unwired — the person is placing it deliberately.
    let tail = TRIGGER
    for (let at = draft.start; at; at = draft.steps.find((s) => s.id === at)?.next ?? null) tail = at
    const after = draft.layout[tail] ?? { x: 0, y: 120 }
    const x = position?.x ?? after.x + 270
    const y = position?.y ?? after.y
    // Wired after a step, a node that reads data takes that step's output;
    // wired straight after the trigger, one that needs input takes the trigger's.
    const reads = created.kind === 'check' || created.kind === 'run' || created.kind === 'action'
    const input = !position && reads
      ? (tail !== TRIGGER ? tail : node.needs_input || created.kind === 'check' ? TRIGGER : null)
      : null
    const step = input ? { ...created, input } : created
    const next = { ...draft, steps: [...draft.steps, step], layout: { ...draft.layout, [step.id]: { x, y } } }
    setDraft(!position && refuse(next, tail, 'next', step.id, canBranch) === null ? connect(next, tail, 'next', step.id) : next)
    setDirty(true)
    setSelected(step.id)
  }, [draft, canBranch])

  const onDrop = useCallback((event: DragEvent) => {
    event.preventDefault()
    const node = palette.find((n) => n.id === event.dataTransfer.getData(DRAG_MIME))
    if (node) addNode(node, flow.screenToFlowPosition({ x: event.clientX, y: event.clientY }))
  }, [addNode, flow, palette])

  // -- writes -------------------------------------------------------------

  const act = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true); setError(null); setNotice(null)
    try { await fn() } catch (exc) { say(exc) } finally { setBusy(false) }
  }, [])

  const save = () => act(async () => {
    if (!draft) return
    const reply = await api.workflowSave(draft, current?.version ?? null)
    setCurrent(reply.workflow); setDirty(false); setOpenId(draft.id)
    setNotice(reply.scheduled || !reply.workflow.enabled
      ? `saved v${reply.workflow.version}`
      : `saved v${reply.workflow.version} — no daemon in this process; it schedules at the next boot`)
    list.reload()
    catalog.reload()
  })

  const toggle = () => act(async () => {
    if (!current) return
    const reply = await api.workflowEnable(current.workflow_id, !current.enabled)
    setCurrent(reply.workflow)
    setNotice(reply.workflow.enabled
      ? (reply.scheduled ? 'enabled — the daemon has it' : 'enabled — schedules at the next daemon boot')
      : 'disabled')
    list.reload()
  })

  const runNow = () => act(async () => {
    if (!current) return
    const reply = await api.workflowRun(current.workflow_id)
    setNotice(`queued ${reply.task ?? ''} — open Runs to see it land`)
  })

  const remove = () => act(async () => {
    if (!current || !window.confirm(`Delete “${current.body?.name}”? Its history is kept.`)) return
    await api.workflowDelete(current.workflow_id)
    setCurrent(null); setDraft(null); setOpenId(null); setDirty(false)
    list.reload()
    catalog.reload()
  })

  const create = (process: boolean) => {
    if (dirty && !window.confirm('Discard unsaved changes?')) return
    const name = window.prompt(
      process ? 'Name this process — a reusable block other workflows can run as one step'
        : 'Name this workflow',
      process ? 'Scan my watchlist' : 'Tesla news synopsis',
    )
    if (!name) return
    const taken = new Set(list.state.status === 'ready' ? list.state.data.workflows.map((w) => w.workflow_id) : [])
    setCurrent(null); setRuns([]); setShownRun(null); setOpenId(null)
    setDraft(blank(name, taken, process)); setDirty(true); setSelected(TRIGGER)
  }

  /** A template opens as an unsaved, disabled copy with its own id — never over your workflow. */
  const openTemplate = (template: WorkflowTemplate) => {
    const taken = new Set(list.state.status === 'ready' ? list.state.data.workflows.map((w) => w.workflow_id) : [])
    let id = template.body.id
    for (let n = 2; taken.has(id); n++) id = `${template.body.id}-${n}`
    setCurrent(null); setRuns([]); setShownRun(null); setOpenId(null); setDrawer(null)
    setDraft({ ...structuredClone(template.body), id })
    setDirty(true); setSelected(null); setError(null)
    setNotice(`Template “${template.name}” — ${template.description}${template.setup.length ? ` Check: ${template.setup.join(' ')}` : ''} Save to keep it, then enable.`)
  }

  const refreshRuns = useCallback(async () => {
    if (!current) return
    const r = await api.workflowRuns(current.workflow_id)
    if (r.available !== false) { setRuns(r.runs); setShownRun(r.runs[0] ?? null) }
  }, [current])

  // -- render -------------------------------------------------------------

  const workflows = list.state.status === 'ready' ? list.state.data.workflows : []
  const templateList = templates.state.status === 'ready' ? templates.state.data.templates : []
  const draftedByGenesis = current?.author === 'orchestrator' && !current.enabled

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 hairline-b" style={{ padding: '5px 8px', flexWrap: 'wrap' }}>
        <select
          className="field" value={openId ?? ''} aria-label="open workflow"
          onChange={(e) => {
            const value = e.target.value
            if (dirty && !window.confirm('Discard unsaved changes?')) return
            if (value.startsWith('template:')) {
              const template = templateList.find((t) => `template:${t.id}` === value)
              if (template) openTemplate(template)
              return
            }
            setOpenId(value || null)
          }}
        >
          <option value="">{workflows.length ? 'open a workflow or template…' : 'open a template…'}</option>
          {workflows.length ? (
            <optgroup label="Your workflows">
              {workflows.map((w) => (
                <option key={w.workflow_id} value={w.workflow_id}>
                  {w.body?.name ?? w.workflow_id}{w.body?.trigger.type === 'on-demand' ? ' (process)' : ''}
                </option>
              ))}
            </optgroup>
          ) : null}
          {[...new Set(templateList.map((t) => t.job))].map((job) => (
            <optgroup key={job} label={`Templates · ${job}`}>
              {templateList.filter((t) => t.job === job).map((t) => (
                <option key={t.id} value={`template:${t.id}`}>{t.name}</option>
              ))}
            </optgroup>
          ))}
        </select>
        <button className="btn-ghost" onClick={() => create(false)}>+ workflow</button>
        <button className="btn-ghost" onClick={() => create(true)} title="A reusable block you can drop into other workflows">+ process</button>

        {draft ? (
          <>
            <input
              className="field" aria-label="workflow name" value={draft.name} style={{ minWidth: 160 }}
              onChange={(e) => edit((wf) => ({ ...wf, name: e.target.value }))}
            />
            <span className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}>
              {current ? `v${current.version} · ${current.author} · ${current.at.replace('T', ' ').slice(0, 16)}` : 'not saved yet'}
              {dirty ? ' · unsaved' : ''}
            </span>
            <span style={{ flex: 1 }} />
            <button
              className="btn" onClick={toggle} disabled={busy || !current || dirty}
              data-active={current?.enabled ? 'true' : 'false'}
              title={dirty ? 'save first — enabling applies to a saved version' : undefined}
            >
              {current?.enabled ? '● enabled' : '○ disabled'}
            </button>
            <button className="btn-ghost" onClick={runNow} disabled={busy || !current?.enabled || dirty}>▶ run now</button>
            <button className="btn-ghost" data-active={drawer === 'history' ? 'true' : 'false'}
              onClick={() => setDrawer((d) => (d === 'history' ? null : 'history'))} disabled={!current}>history</button>
            <button className="btn-ghost" data-active={drawer === 'runs' ? 'true' : 'false'}
              onClick={() => { setDrawer((d) => (d === 'runs' ? null : 'runs')); void refreshRuns() }} disabled={!current}>runs</button>
            <button className="btn-ghost" onClick={remove} disabled={busy || !current}>delete</button>
            <button className="btn" onClick={save} disabled={busy || !dirty}>save</button>
          </>
        ) : null}
      </div>

      {draftedByGenesis ? (
        <div className="label hairline-b" style={{ padding: '4px 8px', color: 'var(--core)', textTransform: 'none', letterSpacing: 0 }}>
          Genesis drafted this{current?.note ? ` from: “${current.note}”` : ''}. Review it, then enable it yourself.
        </div>
      ) : null}
      {error ? (
        <div className="label hairline-b" role="alert" style={{ padding: '4px 8px', color: 'var(--state-degraded)', textTransform: 'none', letterSpacing: 0 }}>
          {error}
        </div>
      ) : notice ? (
        <div className="label hairline-b" style={{ padding: '4px 8px', color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0 }}>
          {notice}
        </div>
      ) : null}

      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {draft ? (
          cat ? <Palette catalog={cat} current={draft.id} onAdd={(n) => addNode(n)} />
            : <aside style={{ width: 230, borderRight: '1px solid var(--hairline)' }}><Loading rows={6} label="nodes" /></aside>
        ) : null}

        <div style={{ flex: 1, minWidth: 0, position: 'relative' }}
          onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy' }}
          onDrop={onDrop}
        >
          {!draft ? (
            <Empty hint="Start with + workflow, build a reusable + process, or tell Genesis what to automate.">
              {openId ? 'loading…' : 'no workflow open'}
            </Empty>
          ) : (
            <ReactFlow<StepFlowNode>
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onConnect={onConnect}
              onEdgesDelete={onEdgesDelete}
              onNodesDelete={onNodesDelete}
              onPaneClick={() => setSelected(null)}
              deleteKeyCode={['Delete', 'Backspace']}
              snapToGrid
              snapGrid={[8, 8]}
              connectionRadius={34}
              connectionLineStyle={{ stroke: 'var(--core-hot)', strokeWidth: 1.5 }}
              proOptions={{ hideAttribution: true }}
              minZoom={0.2}
              maxZoom={2}
              fitView
              fitViewOptions={{ padding: 0.3, maxZoom: 1.1 }}
            >
              <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="var(--hairline)" />
              <Controls showInteractive={false} position="bottom-right" />
              {/* Worth its corner only once a workflow outgrows the viewport. */}
              {draft.steps.length > 8 ? (
                <MiniMap
                  pannable zoomable position="bottom-left"
                  style={{ width: 132, height: 88, background: 'var(--bg-panel)' }}
                  maskColor="rgba(0,0,0,0.55)" nodeStrokeWidth={0} nodeColor="#6b829e"
                />
              ) : null}
            </ReactFlow>
          )}
        </div>

        {draft && drawer === 'history' && current ? (
          <History id={current.workflow_id} onRestore={(body) => { setDraft(body); setDirty(true); setDrawer(null) }} />
        ) : draft && drawer === 'runs' ? (
          <Runs runs={runs} shown={shownRun} onShow={setShownRun} onRefresh={refreshRuns} />
        ) : draft && selected ? (
          <Inspector
            draft={draft} selected={selected} catalog={cat} run={shownRun}
            onTrigger={(t) => edit((wf) => ({ ...wf, trigger: t }))}
            onStep={editStep}
            onRemove={(id) => onNodesDelete([{ id }])}
          />
        ) : null}
      </div>
    </div>
  )
}

// -- palette ----------------------------------------------------------------

function Palette({ catalog, current, onAdd }: { catalog: AutomationCatalog; current: string; onAdd: (n: PaletteNode) => void }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<Set<string>>(() => new Set(['signals', 'logic', 'output']))
  const q = query.trim().toLowerCase()
  const shown = catalog.nodes.filter((n) => n.process !== current && (!q
    || `${n.label} ${n.description} ${n.capability ?? ''} ${n.category}`.toLowerCase().includes(q)))

  return (
    <aside className="scroll-y" style={{ width: 230, flexShrink: 0, borderRight: '1px solid var(--hairline)', padding: 8 }}>
      <input
        className="field" placeholder={`search ${catalog.nodes.length} nodes…`} value={query}
        onChange={(e) => setQuery(e.target.value)} style={{ width: '100%', marginBottom: 6 }}
        aria-label="search nodes"
      />
      {catalog.categories.map((c) => {
        const inCat = shown.filter((n) => n.category === c.id)
        if (!inCat.length) return null
        const expanded = Boolean(q) || open.has(c.id)
        const style = styleOf(c.id)
        return (
          <section key={c.id} style={{ marginBottom: 4 }}>
            <button
              className="btn-ghost" aria-expanded={expanded}
              onClick={() => setOpen((s) => { const n = new Set(s); if (n.has(c.id)) n.delete(c.id); else n.add(c.id); return n })}
              style={{ width: '100%', textAlign: 'left', display: 'flex', gap: 6, alignItems: 'center', padding: '4px 4px' }}
            >
              <span aria-hidden>{style.glyph}</span>
              <span className="label" style={{ color: style.colour }}>{c.label}</span>
              <span style={{ flex: 1 }} />
              <span className="num" style={{ fontSize: 10, color: 'var(--ink-ghost)' }}>{inCat.length} {expanded ? '▾' : '▸'}</span>
            </button>
            {expanded ? (
              <div className="flex flex-col" style={{ gap: 3, margin: '3px 0 6px' }}>
                {inCat.map((n) => (
                  <button
                    key={n.id} draggable className="btn-ghost"
                    onDragStart={(e) => { e.dataTransfer.setData(DRAG_MIME, n.id); e.dataTransfer.effectAllowed = 'copy' }}
                    onClick={() => onAdd(n)}
                    title={n.available === false ? `${n.description} — this tool is not connected right now` : n.description}
                    style={{
                      textAlign: 'left', borderLeft: `3px solid ${style.colour}`, padding: '4px 7px',
                      opacity: n.available === false ? 0.5 : 1,
                    }}
                  >
                    <div style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink)', textTransform: 'none', letterSpacing: 0 }}>
                      {n.label}
                      {n.branches ? <span style={{ color: 'var(--ink-ghost)' }}> · pass/fail</span> : null}
                      {n.writes ? <span style={{ color: 'var(--state-degraded)' }}> · writes</span> : null}
                    </div>
                    <div className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0, marginTop: 1, lineHeight: 1.35 }}>
                      {n.available === false ? 'not connected' : n.description}
                    </div>
                  </button>
                ))}
              </div>
            ) : null}
          </section>
        )
      })}
      <div className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0, marginTop: 8, lineHeight: 1.5 }}>
        Click to append to the chain, or drag onto the canvas. Wire right handle → left handle. Delete removes.
      </div>
    </aside>
  )
}

// -- inspector --------------------------------------------------------------

function Inspector({
  draft, selected, catalog, run, onTrigger, onStep, onRemove,
}: {
  draft: WorkflowBody
  selected: string
  catalog: AutomationCatalog | null
  run: WorkflowRun | null
  onTrigger: (t: WorkflowBody['trigger']) => void
  onStep: (id: string, patch: Partial<WorkflowStep>) => void
  onRemove: (id: string) => void
}) {
  const step = draft.steps.find((s) => s.id === selected)
  const node = step ? nodeFor(step, catalog?.nodes ?? []) : undefined
  const outcome = run?.steps.find((s) => s.step === selected)
  const style = styleOf(node?.category ?? 'triggers')

  return (
    <aside className="scroll-y flex flex-col" style={{ width: 290, flexShrink: 0, borderLeft: '1px solid var(--hairline)', padding: 10, gap: 10 }}>
      {selected === TRIGGER ? (
        <TriggerForm trigger={draft.trigger} onChange={onTrigger} />
      ) : step ? (
        <>
          <div className="flex items-center gap-2">
            <span aria-hidden>{style.glyph}</span>
            <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)' }}>{node?.label ?? step.kind}</span>
            <span style={{ flex: 1 }} />
            <button className="btn-ghost" onClick={() => onRemove(step.id)}>remove</button>
          </div>
          <div className="label" style={{ color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0, lineHeight: 1.5, marginTop: -6 }}>
            <span className="num" style={{ color: 'var(--ink-ghost)' }}>{step.id}</span> · {node?.description}
            {node?.writes ? <span style={{ color: 'var(--state-degraded)' }}> · changes something outside the run</span> : null}
          </div>
          <StepForm draft={draft} step={step} node={node} catalog={catalog} onChange={(p) => onStep(step.id, p)} />
          {step.kind === 'check' || node?.branches ? (
            <div className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0, lineHeight: 1.5 }}>
              Green handle runs on pass. Amber handle runs on fail; leave it unwired and a failure stops the run.
            </div>
          ) : null}
        </>
      ) : null}

      {outcome ? (
        <div className="flex flex-col" style={{ gap: 4, borderTop: '1px solid var(--hairline)', paddingTop: 8 }}>
          <div className="flex items-center gap-2">
            <span className="label">last run</span>
            <Chip tone={outcome.status === 'ok' ? 'good' : outcome.status === 'failed' ? 'bad' : 'neutral'}>{outcome.status}</Chip>
          </div>
          {outcome.reason ? <div className="num" style={{ fontSize: 'var(--fs-tiny)', color: 'var(--state-degraded)' }}>{outcome.reason}</div> : null}
          {outcome.output !== undefined ? (
            <pre className="num scroll-y" style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-faint)', maxHeight: 240, whiteSpace: 'pre-wrap', margin: 0 }}>
              {JSON.stringify(outcome.output, null, 2)}
            </pre>
          ) : null}
        </div>
      ) : null}
    </aside>
  )
}

function StepForm({
  draft, step, node, catalog, onChange,
}: {
  draft: WorkflowBody
  step: WorkflowStep
  node: PaletteNode | undefined
  catalog: AutomationCatalog | null
  onChange: (patch: Partial<WorkflowStep>) => void
}) {
  const earlier = ancestors(draft, step.id)
  const inputField = (
    <Field label="input — data this step works on">
      <select className="field" value={step.input ?? ''} onChange={(e) => onChange({ input: e.target.value || null })}>
        <option value="">— none —</option>
        <option value={TRIGGER}>
          {draft.trigger.type === 'on-demand' ? 'process input (from the caller)' : 'trigger (event or run data)'}
        </option>
        {earlier.map((id) => <option key={id} value={id}>{id}</option>)}
      </select>
    </Field>
  )

  if (step.kind === 'action') {
    const params = node?.params ?? catalog?.nodes.find((n) => n.preset.action === step.action && !n.process)?.params ?? []
    return (
      <div className="flex flex-col" style={{ gap: 8 }}>
        {inputField}
        {node?.each ? (
          <label className="flex items-center gap-2" style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)' }}>
            <input type="checkbox" checked={Boolean(step.each)} onChange={(e) => onChange({ each: e.target.checked })} />
            Repeat for each item of the input (fills <span className="num">{node.each}</span>)
          </label>
        ) : null}
        <ParamForm
          params={params} values={step.params ?? {}} skip={step.each ? node?.each ?? null : null}
          processes={(catalog?.nodes ?? []).filter((n) => n.process && n.process !== draft.id)}
          onChange={(values) => onChange({ params: values })}
        />
      </div>
    )
  }

  if (step.kind === 'gather') {
    return (
      <div className="flex flex-col" style={{ gap: 8 }}>
        {node?.id === 'classic.gather' || !step.capability
          ? <CapabilityPicker step={step} grant={catalog?.grant ?? []} onChange={onChange} />
          : null}
        {inputField}
        {step.capability ? (
          <SchemaArgs
            key={step.capability} capability={step.capability} value={step.args}
            eachArg={step.each ? step.each_arg ?? null : null}
            onEach={(arg) => onChange({ each: Boolean(arg), each_arg: arg })}
            onChange={(args) => onChange({ args })}
          />
        ) : null}
      </div>
    )
  }

  if (step.kind === 'check') {
    return (
      <div className="flex flex-col" style={{ gap: 8 }}>
        {inputField}
        <Field label="passes when">
          <select className="field" value={step.predicate ?? 'non_empty'} onChange={(e) => onChange({ predicate: e.target.value as WorkflowStep['predicate'] })}>
            <option value="non_empty">it returned something</option>
            <option value="min_count">it returned at least N items</option>
            <option value="compare">a field compares to a value</option>
          </select>
        </Field>
        {step.predicate === 'compare' ? (
          <div className="flex gap-2">
            <input className="field" placeholder="field" value={step.field ?? ''} style={{ width: 110 }} onChange={(e) => onChange({ field: e.target.value || null })} />
            <select className="field" value={step.op ?? '>'} onChange={(e) => onChange({ op: e.target.value as WorkflowStep['op'] })}>
              {['>', '<', '>=', '<='].map((o) => <option key={o}>{o}</option>)}
            </select>
          </div>
        ) : null}
        {step.predicate !== 'non_empty' ? (
          <Field label="value">
            <input className="field" type="number" value={step.value ?? ''} onChange={(e) => onChange({ value: e.target.value === '' ? null : Number(e.target.value) })} />
          </Field>
        ) : null}
      </div>
    )
  }

  if (step.kind === 'refresh') {
    return (
      <Field label="rebuild">
        <select className="field" value={step.target ?? 'vault-map'} onChange={(e) => onChange({ target: e.target.value as WorkflowStep['target'] })}>
          {(catalog?.refresh_targets ?? ['vault-map', 'corpus-index']).map((t) => <option key={t}>{t}</option>)}
        </select>
      </Field>
    )
  }

  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <Field label="agent">
        <select className="field" value={step.agent ?? ''} onChange={(e) => onChange({ agent: e.target.value || null })}>
          <option value="">choose an agent…</option>
          {(catalog?.agents ?? []).map((a) => <option key={a.id} value={a.id}>{a.name ?? a.id} · {a.family}</option>)}
        </select>
      </Field>
      {inputField}
      <Field label="args (JSON)">
        <JsonArgs key={step.id} value={step.args} onChange={(args) => onChange({ args })} />
      </Field>
    </div>
  )
}

/** A built-in node's settings, from its declared params. Only known settings are ever written. */
function ParamForm({
  params, values, skip, processes, onChange,
}: {
  params: NodeParam[]
  values: Record<string, unknown>
  skip: string | null
  processes: PaletteNode[]
  onChange: (values: Record<string, unknown>) => void
}) {
  const set = (name: string, value: unknown) => {
    const next = { ...values }
    if (value === '' || value === null || value === undefined || (Array.isArray(value) && !value.length)) delete next[name]
    else next[name] = value
    onChange(next)
  }

  if (!params.length) {
    return <div className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}>No settings — it works on its input.</div>
  }

  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      {params.map((p) => {
        if (p.name === skip) {
          return <Field key={p.name} label={p.label}><span className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}>from each input item</span></Field>
        }
        const v = values[p.name]
        const label = `${p.label}${p.required ? ' *' : ''}`
        let control: ReactNode
        switch (p.type) {
          case 'textarea':
            control = <textarea className="field" rows={3} value={String(v ?? '')} onChange={(e) => set(p.name, e.target.value)} />
            break
          case 'number':
          case 'integer':
            control = <input className="field" type="number" step={p.type === 'integer' ? 1 : 'any'} value={v === undefined ? '' : String(v)}
              onChange={(e) => set(p.name, e.target.value === '' ? '' : Number(e.target.value))} />
            break
          case 'select':
            control = (
              <select className="field" value={String(v ?? '')} onChange={(e) => set(p.name, e.target.value)}>
                {!p.required ? <option value="">—</option> : null}
                {p.options.filter((o) => o !== '').map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            )
            break
          case 'multiselect': {
            const chosen = Array.isArray(v) ? (v as string[]) : []
            control = (
              <div className="flex" style={{ flexWrap: 'wrap', gap: 6 }}>
                {p.options.map((o) => (
                  <label key={o} className="flex items-center gap-1" style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)' }}>
                    <input type="checkbox" checked={chosen.includes(o)}
                      onChange={(e) => set(p.name, e.target.checked ? [...chosen, o] : chosen.filter((x) => x !== o))} />
                    {o}
                  </label>
                ))}
              </div>
            )
            break
          }
          case 'bool':
            control = <input type="checkbox" checked={Boolean(v)} onChange={(e) => set(p.name, e.target.checked)} />
            break
          case 'time':
            control = <input className="field" type="time" value={String(v ?? '')} onChange={(e) => set(p.name, e.target.value)} />
            break
          case 'workflow':
            control = (
              <select className="field" value={String(v ?? '')} onChange={(e) => set(p.name, e.target.value)}>
                <option value="">{processes.length ? 'choose a process…' : 'no processes yet — make one with + process'}</option>
                {processes.map((n) => <option key={n.process} value={n.process}>{n.label}</option>)}
              </select>
            )
            break
          case 'watchlist':
            control = <WatchlistSelect value={String(v ?? '')} onChange={(name) => set(p.name, name)} />
            break
          case 'symbol':
            control = <input className="field" placeholder="NVDA" value={String(v ?? '')} onChange={(e) => set(p.name, e.target.value.toUpperCase())} />
            break
          case 'symbols':
            control = <input className="field" placeholder="NVDA, AMD, TSLA" value={Array.isArray(v) ? (v as string[]).join(', ') : String(v ?? '')}
              onChange={(e) => set(p.name, e.target.value.toUpperCase())} />
            break
          default:
            control = <input className="field" value={String(v ?? '')} onChange={(e) => set(p.name, e.target.value)} />
        }
        return (
          <Field key={p.name} label={label}>
            {control}
            {p.help ? <span className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}>{p.help}</span> : null}
          </Field>
        )
      })}
    </div>
  )
}

/** Your watchlists by name; free text if the store cannot be read. */
function WatchlistSelect({ value, onChange }: { value: string; onChange: (name: string) => void }) {
  const lists = useRead(() => api.watchlists(), [])
  if (lists.state.status !== 'ready' || !lists.state.data.watchlists.length) {
    return <input className="field" placeholder="watchlist name" value={value} onChange={(e) => onChange(e.target.value)} />
  }
  return (
    <select className="field" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">choose a watchlist…</option>
      {lists.state.data.watchlists.map((w) => <option key={w.id} value={w.name}>{w.name} ({w.members.length})</option>)}
    </select>
  )
}

/**
 * A tool node's arguments, from the tool's own JSON Schema — the same source
 * the hand-driven tool panel builds its form from, so no argument name is
 * guessed. Falls back to raw JSON when the schema cannot be read.
 */
function SchemaArgs({ capability, value, eachArg, onEach, onChange }: {
  capability: string; value: Record<string, unknown> | undefined
  eachArg: string | null; onEach: (arg: string | null) => void
  onChange: (v: Record<string, unknown>) => void
}) {
  const schema = useRead(() => api.mcpTool(capability), [capability])
  if (schema.state.status === 'loading') return <Loading rows={2} label="tool form — the first call starts the gateway" />
  const ready = schema.state.status === 'ready' ? schema.state.data.tool : null
  const properties = ready?.input_schema?.properties ?? {}
  if (!ready || !Object.keys(properties).length) {
    return (
      <Field label={ready ? 'this tool takes no arguments' : 'args (JSON) — the tool form is unavailable'}>
        {ready ? null : <JsonArgs value={value} onChange={onChange} />}
      </Field>
    )
  }
  const required = new Set(ready.input_schema.required ?? [])
  const set = (name: string, v: unknown) => {
    const next = { ...(value ?? {}) }
    if (v === '' || v === undefined) delete next[name]
    else next[name] = v
    onChange(next)
  }
  const textArgs = Object.entries(properties).filter(([, f]) => kindOf(f) === 'text').map(([n]) => n)
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      {textArgs.length ? (
        <Field label="repeat for each input item">
          <select className="field" value={eachArg ?? ''} onChange={(e) => onEach(e.target.value || null)}>
            <option value="">no — call once</option>
            {textArgs.map((n) => <option key={n} value={n}>yes, filling {n}</option>)}
          </select>
        </Field>
      ) : null}
      {Object.entries(properties).map(([name, field]) => {
        if (name === eachArg) {
          return <Field key={name} label={field.title ?? name}><span className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}>from each input item</span></Field>
        }
        const current = value?.[name]
        const label = `${field.title ?? name}${required.has(name) ? ' *' : ''}`
        const kind = kindOf(field)
        return (
          <Field key={name} label={label}>
            {kind === 'enum' ? (
              <select className="field" value={String(current ?? '')} onChange={(e) => set(name, e.target.value)}>
                <option value="">—</option>
                {field.enum!.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
              </select>
            ) : kind === 'boolean' ? (
              <input type="checkbox" checked={Boolean(current)} onChange={(e) => set(name, e.target.checked)} />
            ) : kind === 'number' ? (
              <input className="field" type="number" value={current === undefined ? '' : String(current)}
                onChange={(e) => set(name, e.target.value === '' ? '' : Number(e.target.value))} />
            ) : kind === 'json' ? (
              <textarea className="field num" rows={2} defaultValue={current === undefined ? '' : JSON.stringify(current)}
                onBlur={(e) => { try { set(name, e.target.value ? JSON.parse(e.target.value) : '') } catch { /* left as typed */ } }} />
            ) : (
              <input className="field" value={String(current ?? '')} placeholder={field.default !== undefined && field.default !== null ? String(field.default) : ''}
                onChange={(e) => set(name, e.target.value)} />
            )}
            {field.description ? <span className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0, lineHeight: 1.4 }}>{field.description.slice(0, 160)}</span> : null}
          </Field>
        )
      })}
    </div>
  )
}

function CapabilityPicker({ step, grant, onChange }: { step: WorkflowStep; grant: string[]; onChange: (p: Partial<WorkflowStep>) => void }) {
  // Only read here, when "call any tool" is selected: the first tool listing
  // builds the gateway on the daemon, and a canvas should not pay that for opening.
  const tools = useRead(() => api.mcpTools(), [])
  const usable = useMemo(() => {
    if (tools.state.status !== 'ready') return [] as string[]
    const caps = tools.state.data.tools
      .filter((t: McpToolRow) => t.enabled && t.mutating !== true && granted(grant, t.capability))
      .map((t) => t.capability)
    return [...new Set(caps)].sort()
  }, [tools.state, grant])

  return (
    <Field label="tool (read-only, within the workflow grant)">
      {tools.state.status === 'loading' ? (
        <Loading rows={1} label="tools — the first listing starts the gateway" />
      ) : (
        <select className="field" value={step.capability ?? ''} onChange={(e) => onChange({ capability: e.target.value || null, args: {} })}>
          <option value="">{usable.length ? 'choose a tool…' : 'no granted tools are connected'}</option>
          {step.capability && !usable.includes(step.capability) ? <option value={step.capability}>{step.capability} (not connected)</option> : null}
          {usable.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      )}
    </Field>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col" style={{ gap: 3 }}>
      <span className="label">{label}</span>
      {children}
    </label>
  )
}

function JsonArgs({ value, onChange }: { value: Record<string, unknown> | undefined; onChange: (v: Record<string, unknown>) => void }) {
  const [text, setText] = useState(() => JSON.stringify(value ?? {}, null, 2))
  const [bad, setBad] = useState(false)
  // ponytail: raw JSON args. A form generated from the tool's JSON Schema (as
  // `panels/tool.tsx` builds) is the upgrade once people stop typing braces.
  return (
    <textarea
      className="field num" rows={4} value={text} aria-invalid={bad}
      style={{ fontSize: 'var(--fs-tiny)', borderColor: bad ? 'var(--state-degraded)' : undefined }}
      onChange={(e) => {
        setText(e.target.value)
        try { onChange(JSON.parse(e.target.value || '{}')); setBad(false) } catch { setBad(true) }
      }}
    />
  )
}

function TriggerForm({ trigger, onChange }: { trigger: WorkflowBody['trigger']; onChange: (t: WorkflowBody['trigger']) => void }) {
  const minutes = Math.max(1, Math.round((trigger.interval_sec ?? 900) / 60))
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <span className="label" style={{ color: 'var(--core)' }}>⏰ trigger</span>
      <Field label="when">
        <select className="field" value={trigger.type} onChange={(e) => {
          const type = e.target.value
          if (type === 'cron') onChange({ type, at: trigger.at ?? '07:00' })
          else if (type === 'market-open' || type === 'market-closed') onChange({ type, interval_sec: minutes * 60 })
          else if (type === 'event') onChange({ type, on: trigger.on?.length ? trigger.on : ['market.open'] })
          else onChange({ type })
        }}>
          <option value="cron">every day at a time</option>
          <option value="market-open">during market hours, every N min</option>
          <option value="market-closed">while the market is closed, every N min</option>
          <option value="event">when an event fires</option>
          <option value="on-demand">only when I run it</option>
        </select>
      </Field>
      {trigger.type === 'cron' ? (
        <Field label="time (ET)">
          <input className="field" type="time" value={trigger.at ?? '07:00'} onChange={(e) => onChange({ type: 'cron', at: e.target.value })} />
        </Field>
      ) : null}
      {trigger.type === 'market-open' || trigger.type === 'market-closed' ? (
        <Field label="every (minutes)">
          <input className="field" type="number" min={1} value={minutes}
            onChange={(e) => onChange({ type: trigger.type, interval_sec: Math.max(1, Number(e.target.value)) * 60 })} />
        </Field>
      ) : null}
      {trigger.type === 'event' ? (
        <Field label="events (comma separated)">
          <input className="field" value={(trigger.on ?? []).join(', ')}
            onChange={(e) => onChange({ type: 'event', on: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })} />
        </Field>
      ) : null}
    </div>
  )
}

// -- drawers ----------------------------------------------------------------

function Runs({ runs, shown, onShow, onRefresh }: {
  runs: WorkflowRun[]; shown: WorkflowRun | null; onShow: (r: WorkflowRun) => void; onRefresh: () => void
}) {
  return (
    <aside className="scroll-y flex flex-col" style={{ width: 270, flexShrink: 0, borderLeft: '1px solid var(--hairline)', padding: 10, gap: 6 }}>
      <div className="flex items-center gap-2">
        <span className="label">runs</span><span style={{ flex: 1 }} />
        <button className="btn-ghost" onClick={onRefresh}>refresh</button>
      </div>
      {runs.length === 0 ? (
        <div className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}>Has not run yet.</div>
      ) : runs.map((r) => (
        <button key={r.run_id} className="btn-ghost" data-active={shown?.run_id === r.run_id ? 'true' : 'false'}
          onClick={() => onShow(r)} style={{ textAlign: 'left' }}>
          <Chip tone={r.status === 'ok' ? 'good' : 'bad'}>{r.status}</Chip>{' '}
          <span className="num" style={{ fontSize: 'var(--fs-tiny)' }}>{r.started_at.replace('T', ' ').slice(0, 16)} · v{r.version}</span>
        </button>
      ))}
      <div className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0, lineHeight: 1.5 }}>
        Pick a run to paint its outcome onto the nodes.
      </div>
    </aside>
  )
}

function History({ id, onRestore }: { id: string; onRestore: (body: WorkflowBody) => void }) {
  const versions = useRead(() => api.workflowVersions(id), [id])
  const [pair, setPair] = useState<number[]>([])
  if (versions.state.status !== 'ready') {
    return <aside style={{ width: 300, borderLeft: '1px solid var(--hairline)' }}><Loading rows={3} label="history" /></aside>
  }
  const rows = versions.state.data.versions
  const picked = pair.map((v) => rows.find((r) => r.version === v)).filter(Boolean) as WorkflowVersionRow[]

  return (
    <aside className="scroll-y flex flex-col" style={{ width: 300, flexShrink: 0, borderLeft: '1px solid var(--hairline)', padding: 10, gap: 6 }}>
      <span className="label">history — pick two to compare</span>
      {rows.map((v) => (
        <div key={v.version} className="flex items-center gap-2" style={{ fontSize: 'var(--fs-tiny)' }}>
          <input type="checkbox" aria-label={`compare v${v.version}`} checked={pair.includes(v.version)}
            onChange={(e) => setPair((p) => (e.target.checked ? [...p, v.version].slice(-2) : p.filter((x) => x !== v.version)))} />
          <span className="num">v{v.version}</span>
          <span style={{ color: 'var(--ink-faint)' }}>{v.author} · {v.at.replace('T', ' ').slice(5, 16)}</span>
          <span style={{ color: 'var(--ink-ghost)' }}>{v.deleted ? 'deleted' : v.note || (v.enabled ? 'on' : 'off')}</span>
          <span style={{ flex: 1 }} />
          {v.body ? <button className="btn-ghost" onClick={() => onRestore(v.body as WorkflowBody)}>restore</button> : null}
        </div>
      ))}
      {picked.length === 2 ? <Diff older={picked[1]} newer={picked[0]} /> : null}
    </aside>
  )
}

/** Line-by-line, layout left out — a moved node is not a change in behaviour. */
function Diff({ older, newer }: { older: WorkflowVersionRow; newer: WorkflowVersionRow }) {
  const lines = (v: WorkflowVersionRow) => {
    if (!v.body) return ['(deleted)']
    const { layout: _layout, ...rest } = v.body
    return JSON.stringify(rest, null, 2).split('\n')
  }
  const a = lines(older)
  const b = lines(newer)
  const inA = new Set(a)
  const inB = new Set(b)
  // ponytail: set-membership diff, not LCS. Enough to see what changed in a
  // 20-step body; a real diff if bodies grow repetitive enough to mislead.
  return (
    <pre className="num" style={{ fontSize: 'var(--fs-tiny)', margin: 0, whiteSpace: 'pre-wrap' }}>
      {a.filter((l) => !inB.has(l)).map((l, i) => <div key={`-${i}`} style={{ color: 'var(--state-down)' }}>- {l.trim()}</div>)}
      {b.filter((l) => !inA.has(l)).map((l, i) => <div key={`+${i}`} style={{ color: 'var(--verdict-pass)' }}>+ {l.trim()}</div>)}
      {a.join() === b.join() ? <div style={{ color: 'var(--ink-ghost)' }}>no behavioural change (layout or enable only)</div> : null}
    </pre>
  )
}
