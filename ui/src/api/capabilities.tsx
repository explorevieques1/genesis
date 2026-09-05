// Spec: Genesis Markdown/10-Architecture/Biological Design.md §3 Proprioception
//
// The UI asks the system what it can do, and believes the answer.
//
// This is the mechanism behind "no dummy data". Not a convention, not a code
// review habit — a structure. A page that wants to render a backtest report
// must first obtain `useCapability('backtest.engine')`, and if that says
// `built: false` the only thing it can render is the `<Unbuilt/>` state, which
// names the missing module and the vault note that specifies it.
//
// The alternative is what every dashboard does by default: ship the page with
// placeholder numbers "until the backend lands". Those numbers then survive
// three demos and a screenshot, and everyone who saw them now believes the
// system has a backtest engine. `Biological Design` §3 calls that
// proprioceptive drift — *"the system will then reason confidently about
// itself and be wrong"* — and it ranks it with reconciliation, which is the
// company-ending one.
//
// So capability state is loaded once, at the shell, and passed down. A page
// cannot opt out of asking.

import { createContext, useContext, type ReactNode } from 'react'
import { api, type CapabilitiesBody, type CapabilityRecord } from './client'
import { useRead, type Read } from './useRead'

const CapabilityContext = createContext<Read<CapabilitiesBody> | null>(null)

export function CapabilityProvider({ children }: { children: ReactNode }) {
  // Read once for the life of the shell. Capabilities change when code
  // changes, which means a reload — there is nothing to poll for.
  const read = useRead(() => api.capabilities(), [])
  return <CapabilityContext.Provider value={read}>{children}</CapabilityContext.Provider>
}

export function useCapabilities(): Read<CapabilitiesBody> {
  const value = useContext(CapabilityContext)
  if (!value) throw new Error('useCapabilities outside CapabilityProvider')
  return value
}

/**
 * One capability, or `null` while the probe is still in flight.
 *
 * Returning `null` rather than a default of `built: false` is deliberate:
 * "not yet known" and "known to be missing" produce different screens. The
 * first is a brief skeleton; the second is a permanent, explanatory empty
 * state. Defaulting to `false` would flash the second at every page load.
 */
export function useCapability(id: string): CapabilityRecord | null {
  const { state } = useCapabilities()
  if (state.status !== 'ready') return null
  return state.data.capabilities[id] ?? null
}

/** True only when the probe has answered and answered yes. */
export function useIsBuilt(id: string): boolean {
  return useCapability(id)?.built === true
}
