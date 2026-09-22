// Spec: Genesis Markdown/20-Agents/Execution/Agent — Order Manager.md · 60-UI/Dashboard.md §Positions
//
// The order path's live state: positions, working orders, mode, halt.
//
// Loaded once, then replaced wholesale by every `execution.state` push — the
// order manager publishes on change, so this never polls. One hook, so the
// trade panel and the chart's order lines can never show two different books.

import { useEffect, useState } from 'react'
import { api, type ExecState } from '@/api/client'
import { useGenesis } from '@/store/useGenesis'

export type ExecRead =
  | { status: 'loading' }
  | { status: 'off'; reason: string }
  | { status: 'error'; reason: string }
  | { status: 'ready'; state: ExecState }

export function useExecState(): { read: ExecRead; reload: () => void } {
  const [read, setRead] = useState<ExecRead>({ status: 'loading' })
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let live = true
    api.execState().then(
      (body) => {
        if (!live) return
        if (body.available) setRead({ status: 'ready', state: body as unknown as ExecState })
        else setRead({ status: 'off', reason: body.reason })
      },
      (err) => live && setRead({ status: 'error', reason: String(err?.message ?? err) }),
    )
    return () => { live = false }
  }, [nonce])

  useEffect(() => useGenesis.subscribe((s, prev) => {
    const e = s.events[0] as { event: string; data: unknown } | undefined
    if (!e || e === prev.events[0]) return
    if (e.event === 'execution.state') setRead({ status: 'ready', state: e.data as ExecState })
  }), [])

  return { read, reload: () => setNonce((n) => n + 1) }
}
