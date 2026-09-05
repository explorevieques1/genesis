// Spec: Genesis Markdown/10-Architecture/Orchestrator.md · 20-Agents/Agent Contract.md
//
// Automation: workflows, and what exists in their place today.
//
// The requested feature is a visual workflow builder — a canvas where a person
// wires steps together and Genesis runs the result. There is no backend for it
// (`automation.workflows` probes false), so the builder is not drawn.
//
// But "not built" is not the whole truth here, and rendering only an empty
// state would be its own kind of lie. Genesis already *has* automation: eleven
// agents with real cadences, declared in code — `market-open: 30s`,
// `market-closed: 120s`, `on event: agent.down`. That is a running schedule,
// and it is the thing a workflow builder would eventually author. So this page
// shows the automation that exists, and is explicit that authoring new
// workflows from the UI does not.
//
// The distinction matters for what gets built next. A workflow engine is not a
// greenfield feature — it is a way to declare what `AgentDeclaration.cadence`
// already expresses, and it should extend that rather than sit beside it.

import { api, type AgentRow } from '@/api/client'
import { useRead } from '@/api/useRead'
import { useCapability } from '@/api/capabilities'
import { Absent, Loading, Unbuilt } from '@/components/States'
import { Chip, PanelBody, Section } from '@/components/Primitives'
import { stagger } from '@/lib/motion'

/** The builder itself. Absent, and says which note specifies it. */
export function WorkflowBuilderPanel() {
  const capability = useCapability('automation.workflows')
  if (!capability) return <Loading rows={3} />
  return <Unbuilt capability={capability} />
}

/**
 * The schedule that is actually running: every agent's declared cadence.
 *
 * Grouped by trigger rather than by agent, because the question this answers is
 * "what happens when the market opens", not "what does the watchdog do".
 */
export function CadencePanel() {
  const { state, reload } = useRead(() => api.agents(), [])

  if (state.status === 'loading') return <Loading rows={5} label="cadences" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  const byTrigger = new Map<string, { agent: AgentRow; when: string }[]>()
  for (const agent of state.data.agents) {
    for (const cadence of agent.cadence) {
      const list = byTrigger.get(cadence.type) ?? []
      // `at` is the cron schedule and was being dropped, so the Digest agent's
      // four daily runs rendered as its name four times with nothing beside
      // it -- a list that looked like a bug rather than a schedule.
      const when =
        cadence.at ? cadence.at
        : cadence.interval_sec ? `every ${cadence.interval_sec}s`
        : cadence.on?.length ? cadence.on.join(', ')
        : '—'
      list.push({ agent, when })
      byTrigger.set(cadence.type, list)
    }
  }

  if (!byTrigger.size) {
    return <Absent reason="no agent declares a cadence" />
  }

  return (
    <PanelBody>
      <div className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0, lineHeight: 1.5 }}>
        These are real, running schedules — declared in each agent's
        `AgentDeclaration` and executed by the daemon. Not a mock of what a
        workflow engine would do.
      </div>

      {[...byTrigger.entries()].map(([trigger, entries]) => (
        <Section key={trigger} title={trigger.replace(/-/g, ' ')} dense>
          <div className="flex flex-col" style={{ gap: 2 }}>
            {entries.map(({ agent, when }, index) => (
              <div
                key={`${agent.id}:${trigger}:${when}:${index}`}
                className="flex items-center gap-2 lift"
                style={{ ['--i' as string]: stagger(index, 16), fontSize: 'var(--fs-tiny)' }}
              >
                <span style={{ color: 'var(--ink-dim)', minWidth: 132 }}>
                  {agent.name ?? agent.id}
                </span>
                {agent.reflex && <Chip tone="spinal">reflex</Chip>}
                <span style={{ flex: 1 }} />
                <span className="num" style={{ color: 'var(--ink-faint)' }}>{when}</span>
              </div>
            ))}
          </div>
        </Section>
      ))}
    </PanelBody>
  )
}
