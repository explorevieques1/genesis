// Spec: Genesis Markdown/10-Architecture/Biological Design.md
//
// The activity phase glyph. Each phase gets a distinct SHAPE as well as a colour,
// so the vocabulary survives greyscale and a red-green deficiency — the same
// accessibility rule Genesis Core.md sets for the core's five states.
//
// These are not agent states. `AgentState` is the daemon's five-value vocabulary
// (idle / working / blocked / degraded / down) and the UI does not invent a sixth.
// The phase is the visible *texture* of `working`, derived from the task verb.

import { memo } from 'react'
import type { ActivityPhase } from '@/types/events'

export const PHASE_META: Record<ActivityPhase, { glyph: string; color: string; label: string; why: string }> = {
  idle:       { glyph: '·',  color: 'var(--state-idle)',        label: 'idle',       why: 'No task in flight' },
  perceiving: { glyph: '◇',  color: 'var(--phase-perceiving)',  label: 'perceiving', why: 'Afferent — reading a feed, a store or a retrieval. Cheap, safe, retryable.' },
  thinking:   { glyph: '◈',  color: 'var(--phase-thinking)',    label: 'thinking',   why: 'The LLM organ. Judgement, not arithmetic.' },
  acting:     { glyph: '▲',  color: 'var(--phase-acting)',      label: 'acting',     why: 'Efferent — a write. Authorised, ordered, audited.' },
  verifying:  { glyph: '⊙',  color: 'var(--phase-verifying)',   label: 'verifying',  why: 'Proprioception — confirming the act actually landed.' },
  waiting:    { glyph: '⋯',  color: 'var(--phase-waiting)',     label: 'waiting',    why: 'Blocked on a dependency, not on itself.' },
  blocked:    { glyph: '⊘',  color: 'var(--state-blocked)',     label: 'blocked',    why: 'Cannot proceed.' },
  error:      { glyph: '✕',  color: 'var(--state-down)',        label: 'error',      why: 'The task failed. The marker persists until acknowledged.' },
  complete:   { glyph: '✓',  color: 'var(--verdict-pass)',      label: 'complete',   why: 'The task completed and reported.' },
}

export const PhaseMark = memo(function PhaseMark({
  phase, withLabel = false,
}: { phase: ActivityPhase; withLabel?: boolean }) {
  const m = PHASE_META[phase]
  return (
    <span
      title={`${m.label} — ${m.why}`}
      style={{ color: m.color, display: 'inline-flex', alignItems: 'center', gap: 4, flexShrink: 0 }}
    >
      <span style={{ lineHeight: 1 }}>{m.glyph}</span>
      {withLabel && <span style={{ fontSize: 'var(--fs-micro)' }}>{m.label}</span>}
    </span>
  )
})
