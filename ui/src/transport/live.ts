// Spec: Genesis Markdown/60-UI/UI Stack.md §7 Transport
//
// The real transport. Not wired yet — the daemon has no socket surface as of
// 2026-09-04 (there is no HTTP/WS server under `src/genesis/`). It is written now
// so that the swap is a config change rather than a refactor, and so the reconnect
// and gap semantics the note requires are specified in code rather than deferred.
//
// When the daemon grows the endpoint, the only thing that should need to change
// is `VITE_GENESIS_WS` / `VITE_GENESIS_HTTP`.

import type { GenesisEvent } from '@/types/events'
import type { EventHandler, Snapshot, StatusHandler, Transport } from './transport'
import { MockTransport } from './mock'

const RECONNECT_BASE_MS = 500
const RECONNECT_CAP_MS = 15_000

export class LiveTransport implements Transport {
  readonly kind = 'live' as const
  private ws: WebSocket | null = null
  private stopped = false
  private attempt = 0
  private timer: number | null = null
  /** Last event id seen. On reconnect we replay forward from here. */
  private watermark: string | null = null

  constructor(
    private readonly wsUrl: string,
    private readonly httpUrl: string,
  ) {}

  start(onEvent: EventHandler, onStatus: StatusHandler): void {
    this.stopped = false
    const connect = () => {
      if (this.stopped) return
      onStatus('connecting', this.attempt > 0)
      const url = this.watermark
        ? `${this.wsUrl}?since=${encodeURIComponent(this.watermark)}`
        : this.wsUrl
      const ws = new WebSocket(url)
      this.ws = ws

      ws.onopen = () => {
        this.attempt = 0
        onStatus('open', false)
      }
      ws.onmessage = (msg) => {
        let parsed: unknown
        try {
          parsed = JSON.parse(msg.data as string)
        } catch {
          // A frame we cannot parse is a gap, not a shrug. Never silently drop.
          onStatus('open', true)
          return
        }
        const e = parsed as GenesisEvent
        if (!e || typeof e.event !== 'string' || typeof e.id !== 'string') {
          onStatus('open', true)
          return
        }
        this.watermark = e.id
        onEvent(e)
      }
      ws.onclose = () => {
        if (this.stopped) return
        // A gap the UI cannot close puts the surface in `degraded` — the caller
        // decides, but it is told, which is the part that matters.
        onStatus('closed', true)
        const delay = Math.min(RECONNECT_BASE_MS * 2 ** this.attempt++, RECONNECT_CAP_MS)
        this.timer = window.setTimeout(connect, delay * (1 + Math.random() * 0.25))
      }
      ws.onerror = () => ws.close()
    }
    connect()
  }

  stop(): void {
    this.stopped = true
    if (this.timer !== null) clearTimeout(this.timer)
    this.ws?.close()
    this.ws = null
  }

  async snapshot(): Promise<Snapshot> {
    const res = await fetch(`${this.httpUrl}/v1/snapshot`, { headers: { accept: 'application/json' } })
    if (!res.ok) throw new Error(`snapshot ${res.status}`)
    const snap = (await res.json()) as Snapshot
    this.watermark = snap.watermark
    return snap
  }
}

/**
 * Transport selection. **Live by default**, and the choice is surfaced in the
 * chrome — a mock feed that looks live is the one thing this surface must
 * never do.
 *
 * The default was mock, which made the whole surface a demo: it opened onto a
 * busy simulated fleet whether or not anything was running. Defaulting to the
 * local server inverts that. If `genesis serve` is not up the socket simply
 * fails to connect and the connection chip says so — an honestly disconnected
 * surface, which is far more useful than a convincing fake one.
 *
 * Mock is still reachable, for UI work without a backend, but you have to ask:
 * `VITE_GENESIS_MOCK=1 npm run dev`.
 */
export function makeTransport(): Transport {
  if (import.meta.env.VITE_GENESIS_MOCK) return new MockTransport()
  const ws = (import.meta.env.VITE_GENESIS_WS as string | undefined)
    ?? 'ws://127.0.0.1:8765/v1/events'
  const http = (import.meta.env.VITE_GENESIS_HTTP as string | undefined)
    ?? 'http://127.0.0.1:8765'
  return new LiveTransport(ws, http)
}
