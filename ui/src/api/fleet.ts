// Spec: Genesis Markdown/10-Architecture/Biological Design.md §3 Proprioception
//
// Reconcile the vault's roster against the fleet that actually exists.
//
// `data/roster.ts` is the *intended* organism — 31 agents in 5 families,
// transcribed from `20-Agents/Agent Index.md`. That is worth keeping: the body
// map is more useful showing the whole animal than showing only the limbs that
// have grown, and the note reference on each entry is the return path back to
// the spec.
//
// What it cannot be is the authority on what is *built*. Its `build` field was
// hand-copied from note frontmatter on a particular day, and the body map
// rendered every agent — real or not — as `idle`. Eighteen phantom agents,
// visually identical to eighteen real quiet ones. `Biological Design` §3 calls
// that proprioceptive drift, and rates it with reconciliation, which is the one
// that loses money quietly.
//
// So this module overwrites `build` from `/v1/fleet/agents`, which discovers
// agents by importing their modules. The vault says what the organism should
// be; the daemon says what it is; where they disagree the daemon wins and the
// disagreement is reported rather than smoothed over.

import { useMemo } from 'react'
import { api, type AgentRow } from './client'
import { useRead } from './useRead'
import { AGENTS } from '@/data/roster'
import type { AgentSpec } from '@/types/fleet'

export interface FleetReconciliation {
  /** The roster, with `build` replaced by what the daemon found. */
  specs: AgentSpec[]
  /** Ids the daemon confirmed exist as code. */
  built: Set<string>
  /**
   * Agents the daemon found that the roster does not list.
   *
   * Drift in the direction nobody expects — code that no note describes. Worth
   * surfacing loudly, because `CLAUDE.md` #6 makes an undocumented organ the
   * same class of error as a documented phantom one.
   */
  undocumented: AgentRow[]
  /** True once the daemon has answered; until then `build` is the roster's. */
  reconciled: boolean
  reason: string | null
}

/**
 * Normalise ids for comparison.
 *
 * The roster uses the vault's kebab ids (`chart-markup`); declarations use the
 * same, but a family prefix or an underscore has crept in before. Comparing
 * loosely here beats a body map that shows an agent twice because two files
 * spell it differently.
 */
function key(id: string): string {
  return id.toLowerCase().replace(/[_\s]+/g, '-')
}

export function useFleetReconciliation(): FleetReconciliation {
  const { state } = useRead(() => api.agents(), [])

  return useMemo(() => {
    if (state.status !== 'ready') {
      return {
        specs: AGENTS,
        built: new Set<string>(),
        undocumented: [],
        reconciled: false,
        reason: state.status === 'loading' ? null : state.reason,
      }
    }

    const discovered = new Map(state.data.agents.map((a) => [key(a.id), a]))
    const built = new Set<string>()
    const specs = AGENTS.map((spec) => {
      const match = discovered.get(key(spec.id))
      if (match?.built) built.add(spec.id)
      return {
        ...spec,
        // `built` when the module imports, `spec` when it does not. The
        // roster's own value is discarded rather than merged: a hand-kept
        // field that disagrees with an import is simply wrong.
        build: match?.built ? ('built' as const) : ('spec' as const),
      }
    })

    const known = new Set(AGENTS.map((s) => key(s.id)))
    const undocumented = state.data.agents.filter((a) => !known.has(key(a.id)))

    return { specs, built, undocumented, reconciled: true, reason: null }
  }, [state])
}
