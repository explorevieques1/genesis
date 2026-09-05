// Spec: Genesis Markdown/60-UI/UI Stack.md §9 What the UI never does
//
// What the panels on a page agree about.
//
// Panels in a dock are siblings, not a tree — the chart cannot pass a prop to
// the instrument panel beside it, because Dockview owns the arrangement and a
// person can move either one anywhere. So the small amount of state they share
// lives here.
//
// **This is not a store of record and must never become one.** `UI Stack §9`:
// *"No Redux slice that owns positions ... a refresh loses nothing because
// there is nothing to lose."* What is held here is strictly *what the operator
// is looking at* — which symbol, which run, which node. Every one of those is a
// question, not an answer; the answers come from the daemon on each read.
//
// The test for whether something belongs here: if the process restarted and
// this value were lost, would anything be *wrong*, or would you just have to
// click again? Only the second kind goes in.

import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from 'react'

export interface WorkspaceSelection {
  /** Canonical symbol id — `EQ:XNAS:AAPL`, not `AAPL`. */
  symbolId: string | null
  timeframe: string
  /** The backtest run currently being read. */
  runId: string | null
  /** A node in the journal graph or research canvas. */
  nodeId: string | null
  /** A ticker the research page is looking up. */
  ticker: string | null
}

interface WorkspaceValue extends WorkspaceSelection {
  select: (patch: Partial<WorkspaceSelection>) => void
  /**
   * The run body, held in memory for the panels that render it together.
   *
   * A backtest result is one document read by four panels — equity, statistics,
   * trades, the header. Re-fetching it per panel would run the same request
   * four times for one user action, so the page that ran it hands it over here.
   * It is not cached across navigations: leaving the page drops it, and coming
   * back re-reads from the store, which is authoritative.
   */
  run: Record<string, unknown> | null
  setRun: (run: Record<string, unknown> | null) => void
}

const Ctx = createContext<WorkspaceValue | null>(null)

export function WorkspaceProvider({
  children,
  initial,
}: {
  children: ReactNode
  initial?: Partial<WorkspaceSelection>
}) {
  const [selection, setSelection] = useState<WorkspaceSelection>({
    symbolId: null,
    timeframe: '1D',
    runId: null,
    nodeId: null,
    ticker: null,
    ...initial,
  })
  const [run, setRun] = useState<Record<string, unknown> | null>(null)

  const select = useCallback((patch: Partial<WorkspaceSelection>) => {
    setSelection((current) => ({ ...current, ...patch }))
  }, [])

  const value = useMemo<WorkspaceValue>(
    () => ({ ...selection, select, run, setRun }),
    [selection, select, run],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/**
 * Select the first held series if nothing is selected yet.
 *
 * A page that opens on "pick a series" when there is exactly one obvious
 * candidate is asking for a click that carries no information. This picks the
 * first and only the first — it never overrides a choice, and it never fires
 * again once something is selected, so switching pages does not reset you.
 */
export function useDefaultSymbol(symbols: { symbol_id: string; timeframe: string }[]) {
  const { symbolId, select } = useWorkspace()
  useEffect(() => {
    if (symbolId === null && symbols.length > 0) {
      select({ symbolId: symbols[0].symbol_id, timeframe: symbols[0].timeframe })
    }
  }, [symbolId, symbols, select])
}

export function useWorkspace(): WorkspaceValue {
  const value = useContext(Ctx)
  if (!value) throw new Error('useWorkspace outside WorkspaceProvider')
  return value
}
