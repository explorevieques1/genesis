// Spec: Genesis Markdown/10-Architecture/Orchestrator.md · 10-Architecture/Agent Contract.md
//
// Automation: the schedule that is running.
//
// Declared agents and enabled workflows side by side, with no structural
// distinction — a workflow compiles to an AgentDeclaration and runs on the same
// scheduler (Automation.md). A workflow row opens itself in WB.

import { api, type AgentRow } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Loading } from '@/components/States'
import { Chip, PanelBody, Section } from '@/components/Primitives'
import { stagger } from '@/lib/motion'
import { openPanel } from '@/workspace/dock'

/**
 * The schedule that is actually running: every agent's declared cadence.
 *
 * Grouped by trigger rather than by agent, because the question this answers is
 * "what happens when the market opens", not "what does the watchdog do".
 */
export function CadencePanel() {
  const { state, reload } = useRead(() => api.agents(), [])
  const alerts = useRead(() => api.automationAlerts(12), [])

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
        Real, running schedules — declared in an agent's code or saved from the
        workflow builder, and executed by the same daemon. Click a workflow to
        open it.
      </div>

      {alerts.state.status === 'ready' && alerts.state.data.alerts.length ? (
        <Section title="recent alerts" dense actions={<button className="btn-ghost" onClick={alerts.reload}>refresh</button>}>
          <div className="flex flex-col" style={{ gap: 4 }}>
            {alerts.state.data.alerts.map((a) => (
              <div key={a.alert_id} style={{ fontSize: 'var(--fs-tiny)', borderLeft: `2px solid ${a.urgency === 'always' ? 'var(--state-down)' : 'var(--state-degraded)'}`, paddingLeft: 6 }}>
                <div className="flex items-center gap-2">
                  <span style={{ color: 'var(--ink)' }}>{a.title}</span>
                  <span style={{ flex: 1 }} />
                  <span className="num" style={{ color: 'var(--ink-ghost)' }}>{a.at.replace('T', ' ').slice(5, 16)}</span>
                </div>
                {a.message ? <div style={{ color: 'var(--ink-faint)', whiteSpace: 'pre-wrap' }}>{a.message.slice(0, 280)}</div> : null}
              </div>
            ))}
          </div>
        </Section>
      ) : null}

      {[...byTrigger.entries()].map(([trigger, entries]) => (
        <Section key={trigger} title={trigger.replace(/-/g, ' ')} dense>
          <div className="flex flex-col" style={{ gap: 2 }}>
            {entries.map(({ agent, when }, index) => (
              <div
                key={`${agent.id}:${trigger}:${when}:${index}`}
                className="flex items-center gap-2 lift"
                style={{ ['--i' as string]: stagger(index, 16), fontSize: 'var(--fs-tiny)' }}
              >
                {agent.workflow ? (
                  <button
                    className="btn-ghost"
                    style={{ minWidth: 132, textAlign: 'left', padding: 0, border: 0 }}
                    onClick={() => openPanel('workflow-builder', {
                      id: `workflow-builder:${agent.workflow}`,
                      title: agent.name ?? agent.id,
                      params: { workflowId: agent.workflow },
                    })}
                  >
                    {agent.name ?? agent.id}
                  </button>
                ) : (
                  <span style={{ color: 'var(--ink-dim)', minWidth: 132 }}>
                    {agent.name ?? agent.id}
                  </span>
                )}
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
