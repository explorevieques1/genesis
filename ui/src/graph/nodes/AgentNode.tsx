// Spec: Genesis Markdown/60-UI/Fleet View.md §Nodes
//
// One node per agent. Node visual weight tracks ACTIVITY, not importance — with
// thirty agents the screen has to answer "where is the work" pre-attentively, so
// an idle agent recedes and a working one is lit.
//
// The `tier: none` badge is not decoration. Per Biological Design §1 a spinal
// component is not a lesser agent, and the operator must be able to see at a
// glance which parts of the fleet cannot hallucinate.

import { memo } from 'react'
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react'
import type { ActivityPhase, AgentState } from '@/types/events'
import type { AgentSpec } from '@/types/fleet'
import { PhaseMark } from '@/components/PhaseMark'
import { elapsed } from '@/lib/format'

export interface AgentNodeData extends Record<string, unknown> {
  spec: AgentSpec
  state: AgentState
  phase: ActivityPhase
  taskType: string | null
  startedAt: number | null
  costToday: string
  failed: boolean
  selected: boolean
  dimmed: boolean
  /** No runtime event has ever named this agent — it is roster, not evidence. */
  unseen: boolean
  /**
   * Specified in the vault; no module on disk. Distinct from `unseen`, which
   * means "built, but has never done anything".
   *
   * These two used to render identically, so eighteen agents that did not exist
   * looked exactly like eighteen that were merely quiet — proprioceptive drift
   * on the surface whose job is proprioception.
   */
  unbuilt: boolean
  now: number
}

export type AgentFlowNode = Node<AgentNodeData, 'agent'>

const STATE_COLOR: Record<AgentState, string> = {
  idle: 'var(--state-idle)',
  working: 'var(--state-working)',
  blocked: 'var(--state-blocked)',
  degraded: 'var(--state-degraded)',
  down: 'var(--state-down)',
}

export const AgentNode = memo(function AgentNode({ data }: NodeProps<AgentFlowNode>) {
  const { spec, state, phase, taskType, startedAt, failed, selected, dimmed, unseen, unbuilt, now } = data
  const spinal = spec.tier === 'none'
  const live = state === 'working'
  const accent = failed ? 'var(--state-down)' : STATE_COLOR[state]
  const edge = selected ? 'var(--core-hot)' : live ? accent : 'var(--hairline)'

  return (
    <div
      className="relative select-none"
      style={{
        width: 176,
        // Recession, from the token layer rather than from literals here.
        // These compounded with the ink ramp -- `--ink-dim` at 0.34 on this
        // ground is not dim, it is gone -- and the fleet is *mostly* unbuilt
        // agents today, so the view read as empty when it was full.
        opacity: dimmed
          ? 'var(--dim-out)'
          : unbuilt ? 'var(--dim-unbuilt)' : unseen ? 'var(--dim-unseen)' : 1,
        transition: 'opacity 200ms linear',
      }}
    >
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />

      <div
        className="flex flex-col gap-[3px] px-2 py-[6px]"
        style={{
          background: live ? 'color-mix(in oklab, var(--state-working) 11%, var(--bg-raised))' : 'var(--bg-panel)',
          // Longhand per side, deliberately: mixing the `border` shorthand with a
          // `borderLeft` override lets React clobber the family stripe on a
          // re-render, and the stripe is how the operator reads family at a glance.
          // Dashed for an agent that does not exist. A shape difference, not a
          // colour one, so it survives greyscale — the same rule the REFLEX
          // badge follows.
          borderTop: `1px ${unbuilt ? 'dashed' : 'solid'} ${edge}`,
          borderRight: `1px ${unbuilt ? 'dashed' : 'solid'} ${edge}`,
          borderBottom: `1px ${unbuilt ? 'dashed' : 'solid'} ${edge}`,
          borderLeft: `2px ${unbuilt ? 'dashed' : 'solid'} ${spinal ? 'var(--spinal)' : `var(--family-${spec.family})`}`,
          borderRadius: 'var(--r-sm)',
          boxShadow: live
            ? `0 0 0 1px color-mix(in oklab, ${accent} 30%, transparent), 0 0 18px -6px ${accent}`
            : selected ? '0 0 0 1px var(--core-hot)' : 'none',
        }}
      >
        <div className="flex items-center gap-[5px] min-w-0">
          <span
            className={live ? 'anim-pulse' : ''}
            style={{
              width: 5, height: 5, borderRadius: 999, flexShrink: 0,
              // Hollow when there is nothing reporting behind it. Neither an
              // unbuilt agent nor a built-but-silent one may present the filled
              // dot that means "idle and ready" — that is the online/offline tell.
              background: unbuilt || unseen ? 'transparent' : accent,
              border: unbuilt
                ? '1px solid var(--ink-ghost)'
                : unseen ? '1px solid var(--state-idle)' : 'none',
            }}
          />
          <span
            className="truncate"
            style={{ fontSize: 'var(--fs-sm)', color: live ? 'var(--ink)' : 'var(--ink-dim)', fontWeight: live ? 600 : 500 }}
          >
            {spec.name}
          </span>
          {unbuilt && (
            <span
              title="Specified in the vault; no module imports. This organ does not exist yet."
              style={{
                marginLeft: 'auto', flexShrink: 0, fontSize: 'var(--fs-micro)',
                letterSpacing: '0.08em', color: 'var(--ink-faint)',
                border: '1px dashed var(--ink-faint)', borderRadius: 2,
                padding: '0 3px', lineHeight: '12px',
              }}
            >
              SPEC
            </span>
          )}
          {spinal && !unbuilt && (
            // Reflexes look different from judgement. Not a colour alone — a
            // labelled badge, so it survives greyscale and colour deficiency.
            <span
              title="tier: none — spinal. Deterministic; no model in this path."
              style={{
                marginLeft: 'auto', flexShrink: 0, fontSize: 'var(--fs-micro)',
                letterSpacing: '0.08em', color: 'var(--spinal)',
                border: '1px solid var(--spinal-dim)', borderRadius: 2,
                padding: '0 3px', lineHeight: '12px',
              }}
            >
              REFLEX
            </span>
          )}
        </div>

        <div className="flex items-center gap-[5px] min-w-0" style={{ fontSize: 'var(--fs-micro)' }}>
          <PhaseMark phase={failed ? 'error' : phase} />
          <span className="num truncate" style={{ color: 'var(--ink-faint)' }}>
            {failed ? 'failed' : taskType ?? (unseen ? 'offline' : 'idle')}
          </span>
          {startedAt !== null && (
            <span className="num ml-auto" style={{ color: 'var(--ink-dim)' }}>
              {elapsed(now - startedAt)}
            </span>
          )}
        </div>
      </div>

      {failed && (
        // Fleet View: a failed task leaves a visible marker until acknowledged.
        // A silent absence is the one thing this view must never render.
        <div
          style={{
            position: 'absolute', top: -4, right: -4, width: 9, height: 9,
            background: 'var(--state-down)', borderRadius: 1,
            transform: 'rotate(45deg)', border: '1px solid var(--bg-void)',
          }}
          title="Task failed — marker persists until acknowledged"
        />
      )}
    </div>
  )
})
