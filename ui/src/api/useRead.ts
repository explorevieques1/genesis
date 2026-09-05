// Spec: Genesis Markdown/60-UI/UI Stack.md §9 What the UI never does
//
// A read hook, in ninety lines, instead of a query library.
//
// The temptation is react-query. It is a good library and it is the wrong
// shape here, because most of what it sells — background refetch, polling
// intervals, stale-while-revalidate, optimistic updates — is behaviour the
// note explicitly forbids:
//
//   - *"renders from pushed state — it never polls"* (`Widget Catalog`). A
//     refetch interval is a poll wearing a different hat.
//   - *"Stale and labelled, or nothing"* (`UI Stack §9`). Stale-while-
//     revalidate serves a stale value **unlabelled**, which is precisely the
//     failure the rule names.
//   - *"No state store of record"* — a global query cache surviving unmount is
//     one, and it is one that nothing in the system can invalidate correctly,
//     because the daemon does not know it exists.
//
// So: fetch on mount, expose the three states honestly, and re-run only when
// asked. Live movement comes from the socket, not from here.

import { useCallback, useEffect, useRef, useState } from 'react'
import type { Envelope } from './client'
import { HTTP, TransportError } from './client'

/**
 * The four states a read can be in, as a discriminated union.
 *
 * `absent` is the one that earns its keep. Without it, a component receives
 * `data: null` for both "still loading" and "the store does not exist", and
 * every call site has to invent the distinction — which in practice means
 * rendering a spinner forever for a database that will never appear.
 */
export type ReadState<T> =
  | { status: 'loading'; data: null; reason: null }
  | { status: 'ready'; data: T; reason: null }
  | { status: 'absent'; data: null; reason: string; spec?: string }
  | { status: 'error'; data: null; reason: string }

export interface Read<T> {
  state: ReadState<T>
  /** Re-run the fetch. Explicit — nothing here refetches on its own. */
  reload: () => void
  /** When the current value arrived. For the "as of" label a stale read needs. */
  fetchedAt: number | null
}

/**
 * What a failed read actually means.
 *
 * The old message was one sentence for every status: *"the daemon answered 404
 * — is `genesis serve` running?"* It was wrong in the most confusing possible
 * way, because a 404 proves the daemon **is** running — something answered.
 * What a 404 on a `/v1` route really means is that the process is older than
 * the route: a daemon started before these endpoints existed serves
 * `/v1/health` happily and 404s everything added since.
 *
 * That is a routine thing to hit during development, and it should diagnose
 * itself rather than send you looking for a server that is already up.
 */
function notRunning(): string {
  return (
    `could not reach the daemon at ${HTTP} — start it with \`genesis serve\`, ` +
    `or point the UI elsewhere with VITE_GENESIS_HTTP.`
  )
}

function describe(error: TransportError): string {
  if (error.status === 404) {
    return (
      `the daemon answered 404 for this route — it is running, but does not ` +
      `know this endpoint. That usually means it started before the route ` +
      `existed: restart it (\`genesis serve\`) to pick up the current code.`
    )
  }
  if (error.status === 503) {
    return 'the daemon is up but a dependency it needs is not available'
  }
  if (error.status >= 500) {
    return `the daemon failed on this route (${error.status}) — check its log`
  }
  return `the daemon rejected this request (${error.status})`
}

/**
 * Run one read and track it.
 *
 * `deps` behaves like a `useEffect` dependency list: the read re-runs when it
 * changes and not otherwise. Pass the parameters the request is built from —
 * a symbol, a timeframe — so changing the symbol refetches and re-rendering
 * for an unrelated reason does not.
 */
export function useRead<T>(
  fetcher: () => Promise<Envelope<T>>,
  deps: readonly unknown[] = [],
): Read<T> {
  const [state, setState] = useState<ReadState<T>>({ status: 'loading', data: null, reason: null })
  const [fetchedAt, setFetchedAt] = useState<number | null>(null)
  const [nonce, setNonce] = useState(0)

  // A read that resolves after the component unmounted, or after a newer read
  // was started, must not write state. Without this a fast symbol switch
  // renders the slower, older response last.
  const generation = useRef(0)

  const run = useCallback(() => {
    const mine = ++generation.current
    setState({ status: 'loading', data: null, reason: null })
    fetcher()
      .then((body) => {
        if (mine !== generation.current) return
        setFetchedAt(Date.now())
        if (body.available) {
          const { available: _available, ...rest } = body as { available: true } & T
          setState({ status: 'ready', data: rest as T, reason: null })
        } else {
          setState({ status: 'absent', data: null, reason: body.reason, spec: body.spec })
        }
      })
      .catch((error: unknown) => {
        if (mine !== generation.current) return
        setFetchedAt(Date.now())
        const reason =
          error instanceof TransportError ? describe(error)
          // `fetch` rejects with a bare TypeError("Failed to fetch") when it
          // cannot open the connection at all. THAT is the case where "is the
          // daemon running?" is the right question -- and the message the user
          // sees should be the one that fits.
          : error instanceof TypeError ? notRunning()
          : error instanceof Error ? error.message
          : String(error)
        setState({ status: 'error', data: null, reason })
      })
    // `fetcher` is intentionally not a dependency: it is almost always an
    // inline arrow and would re-run this on every render. `deps` is the
    // contract, and it is the caller's to get right.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  useEffect(() => {
    run()
    // The ref object itself is captured, not `.current` — reading the field
    // inside the cleanup is the point (it must see the latest generation), and
    // capturing the object is what makes that safe rather than stale.
    const tracker = generation
    return () => {
      // Invalidate any in-flight read so a late resolve cannot set state on an
      // unmounted component.
      tracker.current++
    }
  }, [run])

  return { state, reload: () => setNonce((n) => n + 1), fetchedAt }
}
