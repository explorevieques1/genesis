// Spec: Genesis Markdown/60-UI/UI Stack.md §7 Transport · §9 What the UI never does
//
// The read side of the transport. Three rules from the note shape every line:
//
//   1. **Reads over HTTP, pushes over the socket, writes over HTTP.** This file
//      is only the first: `GET /v1/*` against the loopback daemon. Live state
//      arrives on the WebSocket (`transport/live.ts`) and never by polling.
//   2. **No store of record.** Nothing here caches into a global that outlives
//      the component tree. A refresh loses nothing because there is nothing to
//      lose — the daemon holds the truth.
//   3. **Absence is a value, not an error.** Every route answers with
//      `{ available: false, reason }` when a store does not exist, and that is
//      a normal, renderable outcome. A missing journal is a fact about the
//      system, not a failed request, and the surface must be able to say which
//      it is.

/** Where the daemon lives. Loopback only — see `genesis serve`. */
export const HTTP =
  (import.meta.env.VITE_GENESIS_HTTP as string | undefined) ?? 'http://127.0.0.1:8765'

/**
 * Every read answers with this envelope.
 *
 * The discriminant is `available`, and it separates the three states a panel
 * must render differently: data arrived; the thing exists but is empty; the
 * thing does not exist. Collapsing the last two into "empty list" is how a UI
 * ends up claiming a system has no trades when it has no journal.
 */
export type Envelope<T> = ({ available: true } & T) | { available: false; reason: string; spec?: string }

export class TransportError extends Error {
  constructor(readonly status: number, message: string) {
    super(message)
    this.name = 'TransportError'
  }
}

/**
 * One GET. Returns the parsed envelope, or throws for a transport failure.
 *
 * The distinction matters: a 500 or a dead socket is an *error* — the daemon
 * is not answering, and the surface should say so and offer a retry. An
 * `available: false` body is an *answer* — the daemon is fine and is telling
 * you the store is absent. Different pixels, different recovery.
 */
export async function get<T>(path: string, init?: RequestInit): Promise<Envelope<T>> {
  const response = await fetch(`${HTTP}${path}`, {
    ...init,
    headers: { accept: 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    throw new TransportError(response.status, `GET ${path} → ${response.status}`)
  }
  return (await response.json()) as Envelope<T>
}

/**
 * One POST. The only shape that acts.
 *
 * Commands carry a response because `UI Stack §7` requires it: *"commands go
 * over HTTP so they carry a response, an idempotency key and an audit line. A
 * fire-and-forget socket frame is the wrong shape for anything that acts."*
 */
export async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${HTTP}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new TransportError(response.status, `POST ${path} → ${response.status}`)
  }
  return (await response.json()) as T
}

// ---------------------------------------------------------------------------
// route shapes — mirrors of `src/genesis/server/reads.py`
// ---------------------------------------------------------------------------

/**
 * Money and prices are **strings**, everywhere, on purpose.
 *
 * `UI Stack §8`: *"Any number the UI needs to compute is computed by an agent
 * and sent."* A `Decimal` that becomes a JSON number becomes an IEEE double
 * here, and the error surfaces inside a position size rather than at the
 * boundary where it was introduced. These types make the string the only
 * option, so a `parseFloat` becomes a visible, deliberate act at the one place
 * a chart library demands one.
 */
export type Money = string

export interface CapabilityRecord {
  id: string
  label: string
  family: string
  /** The vault note specifying it — shown in the empty state. */
  spec: string
  built: boolean
  detail: string
}

export interface CapabilitiesBody {
  capabilities: Record<string, CapabilityRecord>
  families: Record<string, string[]>
  built: number
  total: number
}

export interface Coverage {
  start: string
  end: string
  source: string
  tier: number
  bar_count: number
}

export interface SymbolRow {
  symbol_id: string
  symbol: string
  timeframe: string
  bars: number
  last_bar_at: string | null
  coverage: Coverage[]
}

export interface BarRow {
  /** Epoch seconds — what Lightweight Charts wants. */
  time: number
  ts: string
  open: Money
  high: Money
  low: Money
  close: Money
  volume: Money
  source: string
  /** Market Data Sources trust tier. Lower is more trusted; 1 is the venue. */
  tier: number
  adjusted: boolean
}

export interface BarsBody {
  symbol_id: string
  symbol: string
  timeframe: string
  count: number
  bars: BarRow[]
  coverage: Coverage[]
  last_bar_at: string | null
}

export interface AgentRow {
  id: string
  name: string
  family: string
  module: string
  built: boolean
  error?: string
  model_tier: string
  /** `tier: none` — spinal cord. Deterministic, cannot hallucinate. */
  reflex: boolean
  vision: boolean
  cadence: {
    type: string
    interval_sec?: number | null
    /** `HH:MM` in the daemon's market timezone, for `cron`. */
    at?: string | null
    on?: string[]
  }[]
  tools: string[]
  memory: { read?: string[]; write?: string[] }
  timeout_sec: number | null
  max_concurrent: number | null
}

export interface McpToolRow {
  id: string
  server: string
  name: string
  capability: string
  /** `null` means undeclared — believe the server's hint. A real third state. */
  mutating: boolean | null
  trust: string
  tier: number | null
  timeout_sec: number | null
  keywords: string[]
  enabled: boolean
}

export interface McpServerRow {
  id: string
  enabled: boolean
  transport: string
  command: string | null
  url: string | null
  read_only: boolean
  trust: string
  tier: number
  namespace: string | null
  env_keys: string[]
  tool_count: number
}

export interface GraphNode {
  id: string
  kind: 'entry' | 'lesson' | 'symbol' | 'hypothesis'
  label: string
  symbol?: string | null
  outcome?: string | null
  r_multiple?: number | null
  confidence?: number | null
  weight?: number
}

export interface GraphEdge {
  source: string
  target: string
  kind: 'symbol' | 'evidence'
}

export interface AudioDevice {
  index: number
  name: string
  channels: number
  sample_rate: number
  default: boolean
}

export const api = {
  capabilities: () => get<CapabilitiesBody>('/v1/capabilities'),
  symbols: () => get<{ symbols: SymbolRow[] }>('/v1/market/symbols'),
  bars: (symbol: string, timeframe = '1D', limit = 500) =>
    get<BarsBody>(
      `/v1/market/bars?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&limit=${limit}`,
    ),
  company: (symbol: string) => get<{ symbol: string; profile: Record<string, unknown> }>(
    `/v1/company/${encodeURIComponent(symbol)}`,
  ),
  companies: () => get<{ symbols: string[] }>('/v1/company'),
  agents: () => get<{ count: number; families: Record<string, number>; agents: AgentRow[] }>(
    '/v1/fleet/agents',
  ),
  mcpTools: () => get<{ count: number; tools: McpToolRow[] }>('/v1/mcp/tools'),
  mcpServers: () => get<{ servers: McpServerRow[] }>('/v1/mcp/servers'),
  journalEntries: (limit = 200) =>
    get<{ counts: Record<string, number>; entries: Record<string, unknown>[] }>(
      `/v1/journal/entries?limit=${limit}`,
    ),
  journalGraph: () => get<{ nodes: GraphNode[]; edges: GraphEdge[] }>('/v1/journal/graph'),
  journalPatterns: () => get<{ sample: number; findings: Record<string, unknown>[] }>(
    '/v1/journal/patterns',
  ),
  audioDevices: () => get<{ devices: AudioDevice[] }>('/v1/settings/audio'),
  config: () => get<{ config: Record<string, unknown> }>('/v1/settings/config'),
  command: (text: string) => post<{
    ok: boolean; heard: string; command: string; spoken: string
    detail?: string | null; data?: unknown; ms: number; trace: string
  }>('/v1/command', { text }),
}
