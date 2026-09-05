// Spec: Genesis Markdown/60-UI/UI Stack.md §7 Transport
//
// One socket, read-mostly, carrying Event Schema envelopes off the Task Bus.
//
// Rules this interface enforces by shape:
//   - There is no `send`. The socket is read-only here; commands go over HTTP so
//     they carry a response, an idempotency key and an audit line. A
//     fire-and-forget socket frame is the wrong shape for anything that acts.
//   - `snapshot()` is separate from the stream. On reconnect the UI asks for a
//     snapshot by watermark and replays forward; it never assumes continuity
//     across a gap.

import type { GenesisEvent } from '@/types/events'
import type { SafetyFloor, SystemHealth } from '@/types/fleet'

/** What a reconnect resolves to. A gap it cannot close puts the surface in `degraded`. */
export interface Snapshot {
  /** Last event id the server holds — the watermark to replay forward from. */
  watermark: string
  safety: SafetyFloor
  health: SystemHealth
}

export type EventHandler = (e: GenesisEvent) => void
export type StatusHandler = (s: 'connecting' | 'open' | 'closed', gap: boolean) => void

export interface Transport {
  /** `mock` must be visually unmistakable from `live` — see the connection chip. */
  readonly kind: 'mock' | 'live'
  start(onEvent: EventHandler, onStatus: StatusHandler): void
  stop(): void
  /** Requested on connect and on every reconnect. */
  snapshot(): Promise<Snapshot>
}
