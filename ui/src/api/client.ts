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

// The drawing shapes are defined beside the chart that paints them; this file
// only carries them to the daemon and back.
import type { Drawing, NewDrawing } from '@/components/charts/drawings'

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
/** A marked range of candles, on its way to the journal. Times are epoch seconds. */
export interface JournalMark {
  kind: 'entry' | 'exit' | 'idea'
  symbol: string
  timeframe: string
  start: number
  end: number
  note?: string
  series?: string
  drawing_id?: string
  /** A real trade to hang it on. Empty means it stands on its own. */
  entry_id?: string
}

/** One stored mark: an Observation, `mark.entry` / `mark.exit` / `mark.idea`. */
export interface MarkRow {
  id: string
  at: string
  kind: string
  subject: string
  outcome: string
  detail: {
    symbol: string; timeframe: string; start: number; end: number
    series: string; drawing_id: string; note: string; entry_id: string
  }
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${HTTP}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    // A refusal carries a reason and the operator has to see it: "an agent
    // recorded that link" is an answer, and a bare 400 is a shrug.
    const reason = await response.json().then(
      (b: { reason?: string }) => b?.reason, () => undefined,
    )
    throw new TransportError(response.status, reason ?? `POST ${path} → ${response.status}`)
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

/** A saved drawing, as it comes back from the store. */
export type StoredDrawing = Drawing & { series: string; created: string; updated: string }

export interface CandleRange {
  id: string
  name: string
  /** The vendor ticker as asked for — `ES=F` is Yahoo's continuous ES. */
  ticker: string
  timeframe: string
  /** ISO, UTC. `tz` is the wall clock the window was typed in. */
  start: string
  end: string
  tz: string
  source: string
  tier: number
  bars: number
  created: string
}

export interface NewRange {
  name: string
  ticker: string
  timeframe: string
  /** Local wall clock, `2026-09-08T09:30` — interpreted in `tz`. */
  start: string
  end: string
  tz?: string
}

export interface SymbolRow {
  symbol_id: string
  symbol: string
  timeframe: string
  bars: number
  last_bar_at: string | null
  coverage: Coverage[]
  /** Streamed by the IBKR session: `streaming` only while it is actually live. */
  live?: 'streaming' | 'configured' | null
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
  /** Set when this agent is a compiled workflow — opens it in `WB`. */
  workflow?: string
  timeout_sec: number | null
  max_concurrent: number | null
}

/**
 * One tool as the *server* describes it — arguments included.
 *
 * `McpToolRow` comes from config and is enough to list; this comes from a live
 * MCP handshake and is what a form can be built from. The split is deliberate:
 * listing must never open a session, calling must.
 */
export interface McpToolSchema {
  id: string
  server: string
  name: string
  capability: string
  description: string
  /** JSON Schema, as the server published it. May be empty — some take none. */
  input_schema: {
    type?: string
    properties?: Record<string, JsonSchemaField>
    required?: string[]
  }
  mutating: boolean
  trust: string
  tier: number
  timeout_sec: number
  /** Whether Run may fire at all. `refusal` says why not. */
  callable: boolean
  refusal: string
}

/** The subset of JSON Schema a generated form actually renders. */
export interface JsonSchemaField {
  type?: string | string[]
  description?: string
  enum?: (string | number)[]
  default?: unknown
  title?: string
  items?: JsonSchemaField
}

export interface McpCallResult {
  ok: boolean
  tool?: string
  capability?: string
  reason?: string
  content?: unknown
  structured?: Record<string, unknown> | null
  latency_ms?: number
  /** True when the payload was wrapped on the way out of the gateway. */
  fenced?: boolean
  trust?: string
}

/** `70-Schemas/Workflow Schema.md`. The canvas edits this; the server validates it. */
export interface WorkflowStep {
  id: string
  kind: 'gather' | 'check' | 'refresh' | 'run' | 'action'
  next?: string | null
  on_fail?: string | null
  input?: string | null
  capability?: string | null
  args?: Record<string, unknown>
  predicate?: 'non_empty' | 'min_count' | 'compare' | null
  field?: string | null
  op?: '>' | '<' | '>=' | '<=' | null
  value?: number | null
  target?: 'vault-map' | 'corpus-index' | null
  agent?: string | null
  /** A built-in node from the catalogue, its settings, and repeat-for-each. */
  action?: string | null
  params?: Record<string, unknown>
  each?: boolean
  /** For a tool node repeating per item: the argument each item fills. */
  each_arg?: string | null
}

export interface WorkflowBody {
  id: string
  name: string
  trigger: { type: string; interval_sec?: number | null; at?: string | null; on?: string[] }
  start: string | null
  steps: WorkflowStep[]
  layout: Record<string, { x: number; y: number }>
}

export interface WorkflowVersionRow {
  workflow_id: string
  version: number
  body: WorkflowBody | null
  enabled: boolean
  author: string
  at: string
  note: string
  deleted: boolean
}

export interface WorkflowRun {
  run_id: string
  version: number
  started_at: string
  finished_at: string
  status: 'ok' | 'failed'
  steps: { step: string; status: 'ok' | 'failed' | 'skipped'; reason?: string; output?: unknown }[]
}

/** One setting on a built-in node — `automation/actions.py` `Param`. */
export interface NodeParam {
  name: string
  type: 'text' | 'textarea' | 'number' | 'integer' | 'symbol' | 'symbols' | 'select' | 'multiselect'
    | 'bool' | 'time' | 'workflow' | 'watchlist'
  label: string
  required: boolean
  default: unknown
  options: string[]
  help: string
}

/** One entry in the palette — `automation/catalog.py` `nodes()`. */
export interface PaletteNode {
  id: string
  kind: WorkflowStep['kind']
  category: string
  label: string
  description: string
  preset: Partial<WorkflowStep>
  /** `null` = unknown (no gateway in this process); `false` = not connected. */
  available: boolean | null
  capability?: string
  params?: NodeParam[]
  branches?: boolean
  writes?: boolean
  each?: string | null
  needs_input?: boolean
  process?: string
}

export interface AutomationAlert {
  alert_id: string
  workflow_id: string
  run_id: string
  step_id: string
  at: string
  title: string
  message: string
  urgency: string
}

/** One thing an automation produced — `automation/feed.py`. */
export interface FeedArtifact {
  kind: 'note' | 'brief' | 'observation'
  /** The module that opens it: `notebook`, `news`, `journal-entries`. */
  module: string
  target: string
  label: string
}

export interface FeedItem {
  id: string
  at: string
  workflow: { id: string; name: string; version: number }
  status: string
  title: string
  summary: string
  artifacts: FeedArtifact[]
  new: boolean
}

/** A ready-made workflow — `automation/templates.py`. */
export interface WorkflowTemplate {
  id: string
  job: string
  name: string
  description: string
  setup: string[]
  process: boolean
  body: WorkflowBody
}

export interface AutomationCatalog {
  categories: { id: string; label: string }[]
  nodes: PaletteNode[]
  triggers: string[]
  steps: WorkflowStep['kind'][]
  grant: string[]
  predicates: string[]
  ops: string[]
  refresh_targets: string[]
  agents: { id: string; name: string | null; family: string }[]
}

type Saved = { ok: boolean; workflow: WorkflowVersionRow; scheduled: boolean }

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

/** `/v1/biology` — the organ map, parsed from `Biological Design` §The map. */
export type OrganStatus = 'built' | 'building' | 'spec' | 'missing' | 'n/a'
export interface Organ {
  organ: string
  /** A bold row in the note: built in Phase 1. */
  phase1: boolean
  /** Where it sits in the loop: perception, memory, rhythm, reflex, action, homeostasis, judgement. */
  loop: string
  genesis: string
  status: OrganStatus
  /** What it can do today, one line, from the note's `## Organ status`. */
  summary: string
  parts: { name: string; path: string | null; status: OrganStatus }[]
}

/**
 * `/v1/dna` — the genome: every note with its status, the drift between spec
 * and code, and the prompt inventory. Read-only, and there is no write
 * counterpart anywhere: the genome is edited in a file and committed.
 */
export interface DnaNote {
  name: string
  rel: string
  status: 'spec' | 'building' | 'built' | 'none'
  implemented_by: string[]
  pointing_at_it: string[]
}
export interface DnaFinding {
  kind: string
  glyph: string
  note: string
  detail: string
  files: string[]
}
export interface DnaPrompt {
  name: string
  file: string
  line: number
  chars: number
  lines: number
  est_tokens: number
  opening: string
}
export interface DnaBody {
  counts: { spec: number; building: number; built: number; none: number }
  honest: boolean
  drift: DnaFinding[]
  kinds: Record<string, { glyph: string; why: string }>
  collisions: Record<string, string[]>
  sections: { section: string; notes: DnaNote[] }[]
  prompts: DnaPrompt[]
}

/**
 * `/v1/trade-ideas` — every live idea, ranked, with the risk gate's dry-run
 * size beside it, plus the brief's `watch` items in their own lane.
 *
 * There is no write counterpart. Acting on an idea is `/v1/exec/propose` then
 * `/v1/exec/place`, exactly as it is from the ticket — one order path.
 */
export interface TradeIdeaRow {
  rank: number
  idea_id: string
  symbol: string
  symbol_id: string | null
  direction: 'long' | 'short'
  author: string
  thesis: string
  invalidation: string
  stop_price: number | null
  /** The gate's dry run of this ticket. `null` means it could not be sized. */
  size: number | null
  binding: string | null
  worst_case: string | null
  blocked: boolean
  conflicts: string[]
  confidence: number
  brief_id?: string | null
  brief_title?: string | null
  /** Entry, stop and targets, computed from bars by `research/setup.py`. */
  chart_setup?: ChartSetup | null
  /** Set when the symbol was extracted from the brief's prose, not written as a trade. */
  found_by?: {
    score: number
    why: string[]
    stories: string[]
    tagged: boolean
    conflicted: boolean
  } | null
}
/** The computed half of an idea: `research/setup.py`, from bars. */
export interface ChartSetup {
  spot: number
  atr: number
  entry_zone: [number, number]
  stop: number
  targets: number[]
  stop_basis: 'level' | 'atr'
  stop_why: string
  risk_per_unit: number
  rr: number | null
  trend: string
  swing: string
  bars: number
  source: string
  tier: number | null
  warnings: string[]
  levels: { price: number; label: string; why: string; distance_atr: number; side: string }[]
}

export interface WatchRow {
  id: string
  symbol: string
  symbol_id?: string | null
  idea: string
  rationale: string
  invalidation: string
  brief_title?: string | null
}
export interface TradeIdeasBody {
  as_of: string
  ideas: TradeIdeaRow[]
  watching: WatchRow[]
  desk: string[]
  degraded: string[]
  actionable: number
  news_author: string
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

/** A knowledge-graph entity: a reference to a record, never a copy of it. */
export interface GraphEntity {
  id: string
  type: string
  key: string
  label: string
  /** The record that owns the content — a research note id, a URL, a ticker. */
  ref: string | null
  data: Record<string, unknown>
  namespace: string
  created: string
  updated: string
  superseded_by: string | null
}

export interface CanvasNodeBody extends GraphEntity {
  entity: string
  x: number
  y: number
  pinned: boolean
  added_by: string
  added: string
}

export interface CanvasEdgeBody {
  source: string
  target: string
  kind: string
  weight: number
  namespace: string
  data: Record<string, unknown>
  created: string
}

export interface CanvasBody {
  id: string
  title: string
  query: string
  created_by: string
  created: string
  updated: string
  nodes: CanvasNodeBody[]
  edges: CanvasEdgeBody[]
}

export interface CanvasRow {
  id: string
  title: string
  query: string
  created_by: string
  created: string
  updated: string
  nodes: number
}


export interface ModelTier {
  tier: string
  backend: string
  model: string
  env_var: string | null
  key_present: boolean
  /** Free tier that trains on prompts — the daemon refuses it on a live broker. */
  dev_only: boolean
  local: boolean
  signup: string | null
  /** Why this tier cannot answer, when that is knowable without spending. */
  blocker?: string | null
}

export interface TierUsage {
  tier: string
  backend: string
  model: string
  calls: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  p50_latency_ms: number
  failures: number
  /** null when the model is not in the price table — never rendered as $0. */
  cost_usd: number | null
}

export interface ModelsBody {
  tiers: ModelTier[]
  usage_today: TierUsage[]
  history: { day: string; input_tokens: number; output_tokens: number }[]
  tokens_today: number
  daily_token_budget: number
  live_broker: boolean
}

export interface VaultRef {
  name: string
  path: string
  exists: boolean
}

/** One row of the notebook tree: a folder, a note, or an attachment. */
export interface NotebookEntry {
  path: string
  name: string
  kind: 'folder' | 'note' | 'attachment'
  modified: string | null
  size: number | null
}

export interface NotebookNote {
  path: string
  name: string
  body: string
  modified: string
  size: number
}

/**
 * One `[[link]]` as written, and where it landed.
 *
 * `resolved: null` is an **unresolved link**, which is a normal state and not
 * an error — it is rendered dimmed and clicking it creates the note.
 * `candidates` is non-empty only when several files could have matched, which
 * is surfaced rather than guessed.
 */
export interface NotebookLink {
  target: string
  anchor: string
  alias: string
  embed: boolean
  start: number
  end: number
  resolved: string | null
  candidates: string[]
}

/**
 * A node in `NOD`. Not `GraphNode`: that one's `kind` is the journal's four
 * kinds, and a shared union that has to grow every time a second graph appears
 * is how two unrelated graphs end up type-checking each other's nodes.
 */
export interface NotebookGraphNode {
  id: string
  kind: 'note' | 'unresolved' | 'tag' | 'attachment'
  label: string
  path: string | null
  weight: number
}

export interface NotebookBacklink {
  path: string
  name: string
  context: string
  embed: boolean
}

// -- news — mirrors of `src/genesis/server/news_routes.py` ------------------

export interface TradeIdea {
  idea: string
  symbols: string[]
  bias: 'long' | 'short' | 'watch'
  rationale: string
  invalidation: string
}

export interface NewsAnalysis {
  summary: string
  key_points: string[]
  symbols: string[]
  direction: string
  magnitude: string
  horizon: string
  kind: string
  insights: string[]
  trade_ideas: TradeIdea[]
  risks: string[]
  confidence: number
  read: string
  flags: string[]
  injection: boolean
  model: string
  degraded: boolean
  requested_by: string
}

/** One story. Tier 4 — third-party text, never a number Genesis knows. */
export interface NewsArticle {
  id: string
  url: string
  alt_url: string
  title: string
  publisher: string
  published: string
  summary: string
  symbols: string[]
  thumbnail: string
  source: string
  collected: string
  body_at: string | null
  analysis_at: string | null
  body?: string | null
  analysis?: NewsAnalysis | null
}

export interface NewsStatus {
  source: string
  tier: number
  articles: number
  last_24h: number
  newest: string | null
  last_run: { at: string; ok: boolean; sources: number; fetched: number; new: number; detail: string } | null
  last_ok_at: string | null
}

/** One scheduled print. `at` is UTC; the panel renders it in New York and local. */
export interface EconEvent {
  id: string
  at: string
  country: string
  title: string
  impact: string
  forecast: string
  previous: string
  all_day: boolean
}

export interface NewsBriefRow { id: string; created: string; title: string; hours: number; requested_by: string }

export interface NewsBrief extends NewsBriefRow {
  body: {
    overview: string
    stories: { article_id: string; headline: string; what_happened: string; why_it_matters: string; symbols: string[]; direction: string }[]
    themes: string[]
    watch: string[]
    trade_ideas: TradeIdea[]
    risks: string[]
    confidence: number
    articles: { n: number; id: string; title: string; publisher: string; url: string; published: string; symbols: string[]; why: string; read: boolean }[]
    considered: number
    focus: string
    flags: string[]
    model: string
    degraded: boolean
  }
}

// -- company description (`CO`) — Decimals arrive as strings -----------------

export type HistoryWindow = '1D' | 'YTD' | '1Y' | '5Y'
export interface EpsCell { value: string; actual: boolean; period_end: string | null }
export interface CompanyDescription {
  symbol: string
  name: string | null
  exchange: string | null
  sector: string | null
  industry: string | null
  website: string | null
  summary: string | null
  quote_type: string | null
  currency: string | null
  price: string | null
  change: string | null
  change_pct: string | null
  volume: string | null
  quote_date: string | null
  stats: Record<string, string | null>
  eps: {
    years: number[]
    quarters: { quarter: number; month: string; cells: (EpsCell | null)[] }[]
    annual: (Omit<EpsCell, 'period_end'> | null)[]
  } | null
  holders: { holder: string; value: string | null; shares: string | null; pct_held: string | null; reported: string | null }[]
  news: { title: string; publisher: string; published: string; link: string }[]
  filings: Record<string, string | null>[]
  relations: null
  _sources: string[]
  _missing: string[]
  _market_as_of: string | null
}
export interface PriceHistoryBody {
  symbol: string
  window: HistoryWindow
  interval: string
  source: string
  tier: number
  points: { time: number; close: number; volume: number }[]
}

export const api = {
  capabilities: () => get<CapabilitiesBody>('/v1/capabilities'),
  biology: () => get<{ source: string; organs: Organ[] }>('/v1/biology'),
  dna: () => get<DnaBody>('/v1/dna'),
  tradeIdeas: () => get<TradeIdeasBody>('/v1/trade-ideas'),
  symbols: () => get<{ symbols: SymbolRow[] }>('/v1/market/symbols'),
  bars: (symbol: string, timeframe = '1D', limit = 500) =>
    get<BarsBody>(
      `/v1/market/bars?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&limit=${limit}`,
    ),
  company: (symbol: string) => get<{ symbol: string; profile: Record<string, unknown> }>(
    `/v1/company/${encodeURIComponent(symbol)}`,
  ),
  companies: () => get<{ symbols: string[] }>('/v1/company'),
  /** The `CO` page, shaped server-side. Cached profiles only — never fetches. */
  companyDescription: (symbol: string) => get<CompanyDescription>(
    `/v1/company/${encodeURIComponent(symbol)}/description`,
  ),
  /** Thumbnail closes, tier 3. Fetches yfinance, cached 15 minutes. */
  priceHistory: (symbol: string, window: HistoryWindow) => get<PriceHistoryBody>(
    `/v1/market/history?symbol=${encodeURIComponent(symbol)}&window=${window}`,
  ),
  agents: () => get<{ count: number; families: Record<string, number>; agents: AgentRow[] }>(
    '/v1/fleet/agents',
  ),
  mcpTools: () => get<{ count: number; tools: McpToolRow[] }>('/v1/mcp/tools'),
  mcpServers: () => get<{ servers: McpServerRow[] }>('/v1/mcp/servers'),
  /** Builds the gateway on the daemon's first call — slow once, then instant. */
  mcpTool: (toolId: string) =>
    get<{ tool: McpToolSchema }>(`/v1/mcp/tool/${encodeURIComponent(toolId)}`),
  mcpCall: (tool: string, args: Record<string, unknown>) =>
    post<McpCallResult>('/v1/mcp/call', { tool, args }),
  journalEntries: (limit = 200) =>
    get<{ counts: Record<string, number>; entries: Record<string, unknown>[] }>(
      `/v1/journal/entries?limit=${limit}`,
    ),
  /** The trader's own hand: a range of candles they marked, and what they meant. */
  journalMark: (mark: JournalMark) => post<{ ok: boolean; mark: MarkRow }>('/v1/journal/mark', mark),
  journalMarks: (symbol = '', limit = 200) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (symbol) params.set('symbol', symbol)
    return get<{ marks: MarkRow[] }>(`/v1/journal/marks?${params}`)
  },
  journalGraph: () => get<{ nodes: GraphNode[]; edges: GraphEdge[] }>('/v1/journal/graph'),
  journalPatterns: () => get<{ sample: number; findings: Record<string, unknown>[] }>(
    '/v1/journal/patterns',
  ),
  journalLessons: () =>
    get<{ lessons: Record<string, unknown>[]; hypotheses: Record<string, unknown>[] }>('/v1/journal/lessons'),
  /** Hand a journal agent a task on the daemon's bus — the same door the planner uses. */
  journalRun: (agent: string, args: Record<string, unknown> = {}) =>
    post<{ ok: boolean; task: string | null }>('/v1/journal/run', { agent, args }),
  journalTask: (taskId: string) =>
    get<{ state: string; result: Record<string, unknown> | null; failure: Record<string, unknown> | null }>(
      `/v1/journal/run/${encodeURIComponent(taskId)}`,
    ),
  /**
   * The research directory. The listing omits each note's body — a directory
   * of long notes is a megabyte-scale response otherwise, and nothing in the
   * list view renders it.
   */
  researchNotes: (opts: { kind?: string; q?: string; subject?: string; limit?: number } = {}) => {
    const params = new URLSearchParams()
    if (opts.kind) params.set('kind', opts.kind)
    if (opts.q) params.set('q', opts.q)
    if (opts.subject) params.set('subject', opts.subject)
    if (opts.limit) params.set('limit', String(opts.limit))
    const query = params.toString()
    return get<{ counts: Record<string, number>; notes: Record<string, unknown>[] }>(
      `/v1/research/notes${query ? `?${query}` : ''}`,
    )
  },
  researchNote: (id: string) =>
    get<{ note: Record<string, unknown> }>(`/v1/research/notes/${encodeURIComponent(id)}`),
  /**
   * The research canvas — a view of the knowledge graph with positions.
   *
   * Every mutation returns the whole canvas back, deliberately: a person and
   * Genesis both arrange this thing, so the answer to "I moved a node" has to
   * be the current state rather than an acknowledgement of the state you had.
   */
  canvases: () => get<{ canvases: CanvasRow[]; graph: Record<string, number> }>('/v1/canvas'),
  canvas: (id: string, expand = 0) =>
    get<{ canvas: CanvasBody }>(`/v1/canvas/${encodeURIComponent(id)}?expand=${expand}`),
  canvasEntities: (q = '') =>
    get<{ entities: GraphEntity[] }>(`/v1/canvas/graph?q=${encodeURIComponent(q)}`),
  canvasNew: (body: { query?: string; title?: string; depth?: number }) =>
    post<{ ok: boolean; canvas: CanvasBody }>('/v1/canvas/new', body),
  canvasAdd: (id: string, entities: string[]) =>
    post<{ ok: boolean; canvas: CanvasBody }>(`/v1/canvas/${encodeURIComponent(id)}/add`, { entities }),
  canvasRemove: (id: string, entities: string[]) =>
    post<{ ok: boolean; canvas: CanvasBody }>(`/v1/canvas/${encodeURIComponent(id)}/remove`, { entities }),
  /** Automation. Every write appends a version; nothing edits one in place. */
  workflows: () => get<{ workflows: WorkflowVersionRow[] }>('/v1/automation/workflows'),
  automationCatalog: () => get<AutomationCatalog>('/v1/automation/catalog'),
  workflow: (id: string) =>
    get<{ workflow: WorkflowVersionRow; runs: WorkflowRun[] }>(`/v1/automation/workflows/${encodeURIComponent(id)}`),
  workflowVersions: (id: string) =>
    get<{ versions: WorkflowVersionRow[] }>(`/v1/automation/workflows/${encodeURIComponent(id)}/versions`),
  workflowRuns: (id: string) =>
    get<{ runs: WorkflowRun[] }>(`/v1/automation/workflows/${encodeURIComponent(id)}/runs`),
  workflowSave: (workflow: WorkflowBody, baseVersion: number | null, note = '') =>
    post<Saved>('/v1/automation/workflows/save', { workflow, base_version: baseVersion, note }),
  workflowEnable: (id: string, enabled: boolean) =>
    post<Saved>(`/v1/automation/workflows/${encodeURIComponent(id)}/enable`, { enabled }),
  workflowTemplates: () => get<{ templates: WorkflowTemplate[] }>('/v1/automation/templates'),
  automationFeed: (limit = 50) =>
    get<{ items: FeedItem[]; new: number; new_hours: number; as_of: string }>(
      `/v1/automation/feed?limit=${limit}`),
  automationAlerts: (limit = 30) =>
    get<{ alerts: AutomationAlert[] }>(`/v1/automation/alerts?limit=${limit}`),
  workflowRun: (id: string) =>
    post<{ ok: boolean; task: string | null }>(`/v1/automation/workflows/${encodeURIComponent(id)}/run`, {}),
  workflowDelete: (id: string) =>
    post<{ ok: boolean }>(`/v1/automation/workflows/${encodeURIComponent(id)}/delete`, {}),
  canvasMove: (id: string, entity: string, x: number, y: number) =>
    post<{ ok: boolean }>(`/v1/canvas/${encodeURIComponent(id)}/move`, { entity, x, y }),
  canvasLink: (id: string, source: string, kind: string, target: string) =>
    post<{ ok: boolean; canvas: CanvasBody }>(`/v1/canvas/${encodeURIComponent(id)}/link`, { source, kind, target }),
  canvasUnlink: (id: string, source: string, kind: string, target: string) =>
    post<{ ok: boolean; canvas: CanvasBody }>(`/v1/canvas/${encodeURIComponent(id)}/unlink`, { source, kind, target }),
  canvasDelete: (id: string) =>
    post<{ ok: boolean }>(`/v1/canvas/${encodeURIComponent(id)}/delete`, {}),
  audioDevices: () => get<{ devices: AudioDevice[] }>('/v1/settings/audio'),
  models: () => get<ModelsBody>('/v1/settings/models'),
  setModelTier: (tier: string, backend: string, model: string) =>
    post<{
      ok: boolean; tier: string; backend: string; model: string
      changed: boolean; restart_required: boolean; written_to: string
    }>('/v1/settings/models/set', { tier, backend, model }),
  config: () => get<{ config: Record<string, unknown> }>('/v1/settings/config'),
  command: (text: string, conversation?: string) => post<{
    ok: boolean; heard: string; command: string; spoken: string
    detail?: string | null
    /** `CommandResult.data` — flat strings, command-specific. */
    data?: Record<string, string> | null
    ms: number; trace: string
    /** Echoed back when `conversation` was sent — the id the turn was saved to. */
    conversation?: string
    // `conversation` present (even as '') means "save this to a conversation":
    // '' opens a new one, an id appends. `undefined` — voice, ⌘K — saves nothing.
  }>('/v1/command', conversation === undefined ? { text } : { text, conversation }),

  /** The deterministic command table, for the Help module. */
  commandList: () => get<{ commands: { name: string; help: string }[] }>('/v1/commands'),

  /**
   * Saved Ask Genesis conversations. Not a store of record — losing this
   * database costs the trader their scrollback and nothing else; every answer
   * was already emitted to the bus.
   */
  conversations: () => get<{ conversations: ConversationRow[] }>('/v1/conversations'),
  conversation: (id: string) =>
    get<{ conversation: ConversationBody | null }>(`/v1/conversations/${encodeURIComponent(id)}`),
  conversationDelete: (id: string) =>
    post<{ ok: boolean }>(`/v1/conversations/${encodeURIComponent(id)}/delete`, {}),

  /**
   * The trader's own symbol lists. Not a store of record — losing this
   * database costs the trader their lists and nothing else. Every mutation
   * returns the whole set back, like the canvas: a person and Genesis both
   * edit these, so the answer is the current state, not an acknowledgement.
   */
  /**
   * The notebook, and the graph over it — `NOT` and `NOD`.
   *
   * A vault is a directory of markdown files, so unlike every other store here
   * there is no database behind these: the tree is `os.walk`, the graph is one
   * regex over the same files, and both are correct the instant a note changes
   * — including a note changed in Obsidian rather than here.
   *
   * `vault` is optional everywhere and means "the active one".
   */
  vaults: () => get<{ vaults: VaultRef[]; active: string }>('/v1/notebook/vaults'),
  vaultAdd: (name: string, path: string) =>
    post<{ ok: boolean; vault: VaultRef }>('/v1/notebook/vaults/add', { name, path }),
  vaultSelect: (name: string) =>
    post<{ ok: boolean; vault: VaultRef }>('/v1/notebook/vaults/select', { name }),
  vaultForget: (name: string) =>
    post<{ ok: boolean }>('/v1/notebook/vaults/forget', { name }),

  notebookTree: (path = '', vault?: string) =>
    get<{ vault: string; root: string; path: string; entries: NotebookEntry[] }>(
      `/v1/notebook/tree?path=${encodeURIComponent(path)}${vault ? `&vault=${encodeURIComponent(vault)}` : ''}`,
    ),
  notebookNote: (path: string, vault?: string) =>
    get<{
      vault: string; note: NotebookNote
      links: NotebookLink[]; backlinks: NotebookBacklink[]
    }>(
      `/v1/notebook/note?path=${encodeURIComponent(path)}${vault ? `&vault=${encodeURIComponent(vault)}` : ''}`,
    ),
  notebookSearch: (q: string, vault?: string) =>
    get<{ vault: string; results: { path: string; name: string; excerpt: string }[] }>(
      `/v1/notebook/search?q=${encodeURIComponent(q)}${vault ? `&vault=${encodeURIComponent(vault)}` : ''}`,
    ),
  notebookGraph: (params: Record<string, string> = {}) =>
    get<{ vault: string; notes: number; nodes: NotebookGraphNode[]; edges: GraphEdge[] }>(
      `/v1/notebook/graph?${new URLSearchParams(params).toString()}`,
    ),
  notebookRenamePreview: (from: string, to: string) =>
    get<{ changes: { path: string; name: string; count: number; to: string }[] }>(
      `/v1/notebook/rename/preview?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`,
    ),

  notebookSave: (path: string, body: string, vault?: string) =>
    post<{ ok: boolean; note: NotebookNote }>('/v1/notebook/save', { path, body, vault }),
  /** What clicking an unresolved `[[link]]` calls. Refuses to clobber. */
  notebookCreate: (path: string, body = '', vault?: string) =>
    post<{ ok: boolean; note: NotebookNote }>('/v1/notebook/create', { path, body, vault }),
  notebookAppend: (text: string, path?: string, vault?: string) =>
    post<{ ok: boolean; note: NotebookNote }>('/v1/notebook/append', { text, path, vault }),
  notebookFolder: (path: string, vault?: string) =>
    post<{ ok: boolean; entry: NotebookEntry }>('/v1/notebook/folder', { path, vault }),
  /** Moves the file, then repoints every link — the preview is shown first. */
  notebookRename: (from: string, to: string, rewrite = true, vault?: string) =>
    post<{ ok: boolean; path: string; rewritten: number }>(
      '/v1/notebook/rename', { from, to, rewrite, vault },
    ),
  notebookDelete: (path: string, vault?: string) =>
    post<{ ok: boolean; path: string }>('/v1/notebook/delete', { path, vault }),

  /**
   * Candle ranges — a named window of price, downloaded once and kept.
   *
   * Creating one reaches Yahoo, so it is the one slow call on this object.
   * Reading one back goes through `bars('CR:<id>')` like any other series.
   */
  /**
   * What the trader drew on one series, and the writes that change it.
   *
   * `series` is `<symbol_id>|<timeframe>` — the same key a chart is opened
   * with, so a drawing follows the chart it belongs to and appears on no
   * other. Saved on the daemon rather than in this browser: a box round a
   * setup is the point of having drawn it, and it has to still be there on
   * another machine next month.
   */
  drawings: (series: string) =>
    get<{ series: string; drawings: StoredDrawing[] }>(
      `/v1/charting/drawings?series=${encodeURIComponent(series)}`,
    ),
  drawingSave: (series: string, drawing: NewDrawing | Drawing) =>
    post<{ ok: boolean; id: string; drawings: StoredDrawing[] }>(
      '/v1/charting/drawings/save', { series, ...drawing },
    ),
  drawingDelete: (series: string, id: string) =>
    post<{ ok: boolean; drawings: StoredDrawing[] }>(
      `/v1/charting/drawings/${encodeURIComponent(id)}/delete`, { series },
    ),
  drawingsClear: (series: string) =>
    post<{ ok: boolean; removed: number; drawings: StoredDrawing[] }>(
      '/v1/charting/drawings/clear', { series },
    ),

  ranges: () => get<{ ranges: CandleRange[] }>('/v1/market/ranges'),
  rangeNew: (body: NewRange) =>
    post<{ ok: boolean; range_id: string; ranges: CandleRange[] }>('/v1/market/ranges/new', body),
  rangeRename: (id: string, name: string) =>
    post<{ ok: boolean; ranges: CandleRange[] }>(`/v1/market/ranges/${encodeURIComponent(id)}/rename`, { name }),
  rangeDelete: (id: string) =>
    post<{ ok: boolean; ranges: CandleRange[] }>(`/v1/market/ranges/${encodeURIComponent(id)}/delete`, {}),

  news: (opts: { hours?: number; symbols?: string; q?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(opts)) if (v !== undefined && v !== '') qs.set(k, String(v))
    return get<{ tier: number; articles: NewsArticle[] }>(`/v1/news?${qs}`)
  },
  newsStatus: () => get<NewsStatus>('/v1/news/status'),
  econ: (opts: { impacts?: string; countries?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(opts)) if (v !== undefined && v !== '') qs.set(k, String(v))
    return get<{ source: string; tier: number; fetched_at: string | null; events: EconEvent[] }>(
      `/v1/news/econ?${qs}`,
    )
  },
  econRefresh: () =>
    post<{ ok: boolean; skipped: boolean; events: number; new: number; errors: string[] }>(
      '/v1/news/econ/refresh', {},
    ),
  newsArticle: (id: string) => get<{ article: NewsArticle }>(`/v1/news/article/${encodeURIComponent(id)}`),
  newsBriefs: () => get<{ briefs: NewsBriefRow[] }>('/v1/news/briefs'),
  newsBrief: (id: string) => get<{ brief: NewsBrief }>(`/v1/news/briefs/${encodeURIComponent(id)}`),
  newsCollect: () =>
    post<{ ok: boolean; sources: number; fetched: number; new: number; errors: string[] }>('/v1/news/collect', {}),
  newsSummarise: (id: string) =>
    post<{ ok: boolean; analysis: NewsAnalysis }>(`/v1/news/article/${encodeURIComponent(id)}/summarise`, {}),
  newsBriefNow: (body: { hours: number; symbols?: string; focus?: string; max_articles?: number; refresh?: boolean }) =>
    post<{ ok: boolean; brief: NewsBrief }>('/v1/news/brief', body),

  watchlists: () => get<{ watchlists: WatchlistBody[] }>('/v1/watchlists'),
  watchlistNew: (name: string) =>
    post<{ ok: boolean; watchlists: WatchlistBody[] }>('/v1/watchlists/new', { name }),
  watchlistRename: (id: string, name: string) =>
    post<{ ok: boolean; watchlists: WatchlistBody[] }>(`/v1/watchlists/${encodeURIComponent(id)}/rename`, { name }),
  watchlistDelete: (id: string) =>
    post<{ ok: boolean; watchlists: WatchlistBody[] }>(`/v1/watchlists/${encodeURIComponent(id)}/delete`, {}),
  watchlistAdd: (id: string, symbol: string, group = '') =>
    post<{ ok: boolean; watchlists: WatchlistBody[] }>(`/v1/watchlists/${encodeURIComponent(id)}/add`, { symbol, group }),
  watchlistRemove: (id: string, symbol: string) =>
    post<{ ok: boolean; watchlists: WatchlistBody[] }>(`/v1/watchlists/${encodeURIComponent(id)}/remove`, { symbol }),
  watchlistGroup: (id: string, symbol: string, group: string) =>
    post<{ ok: boolean; watchlists: WatchlistBody[] }>(`/v1/watchlists/${encodeURIComponent(id)}/group`, { symbol, group }),

  /**
   * Day change for arbitrary tickers — a public, **tier 3** feed. Research and
   * closed-market scaffolding only; never a number Genesis reports as its own.
   * The keys are the symbols as passed in.
   *
   * These are **settled daily closes**, not a live price: the last completed
   * close against the one before it, carrying the session date. No realtime
   * feed is wired to Genesis, and a delayed last-trade dressed up as a quote
   * would disagree with every chart on the surface.
   */
  quotes: (symbols: string[]) =>
    get<{ tier: number; quotes: Record<string, QuoteRow> }>(
      `/v1/market/quotes?symbols=${encodeURIComponent(symbols.join(','))}`,
    ),

  /**
   * The Nasdaq-100 on the day — area by market cap, colour by change. The
   * same **tier 3** public feed `quotes` uses, and the same settled-session
   * stance: `market_state` says whether these are the close or a delayed last
   * trade, and the panel labels it either way.
   */
  heatmap: () => get<HeatmapBody>('/v1/market/heatmap'),
  /** One index's members by weight and session change — the `MOV` board. Tier 3. */
  movers: (index: string) => get<MoversBody>(`/v1/market/movers?index=${encodeURIComponent(index)}`),
  /** The current S&P 500 screen and the snapshot under it — the `SCR` module. Tier 3. */
  screener: () => get<ScreenerBody>('/v1/screener'),

  /** The IBKR session: connection state, balances, positions. Read-only. */
  brokerAccount: () => get<BrokerAccountBody>('/v1/broker/account'),
  brokerSettings: () => get<BrokerSettingsBody>('/v1/broker/settings'),
  brokerLogin: (body: { userid: string; password?: string; trading_mode: 'paper' | 'live' }) =>
    post<{ ok: boolean }>('/v1/broker/login', body),
  brokerFeed: (body: BrokerSettingsBody['feed']) =>
    post<{ ok: boolean; live: LiveSeries[] }>('/v1/broker/feed', body),
  brokerGateway: (action: 'start' | 'stop') =>
    post<{ ok: boolean; output: string } & GatewayState>('/v1/broker/gateway', { action }),
  brokerRefresh: () =>
    post<{ ok: boolean; steps: { step: string; ok: boolean; detail: string }[] }>('/v1/broker/refresh', {}),
  brokerTest: () =>
    post<{ ok: boolean; steps: { step: string; ok: boolean; detail: string }[] }>('/v1/broker/test', {}),

  // -- the order path (`/v1/exec/*`) — every placement spends a risk-engine approval --
  execState: () => get<ExecState>('/v1/exec/state'),
  execQuality: (date?: string) =>
    get<ExecQualityBody>(`/v1/exec/quality${date ? `?date=${encodeURIComponent(date)}` : ''}`),
  /** Risk-check a ticket. Places nothing; an approval comes back if it passed. */
  execPropose: (ticket: OrderTicket) => post<ProposeResult>('/v1/exec/propose', ticket),
  /** Spend an approval. `confirmation` must name the contract and size in confirm mode. */
  execPlace: (approval_id: string, confirmation: { symbol: string; qty: number } | null) =>
    post<PlaceResult>('/v1/exec/place', { approval_id, confirmation }),
  /** One click: propose and place — refused unless the mode is auto-within-limits. */
  execSubmit: (ticket: OrderTicket) => post<ProposeResult & Partial<PlaceResult> & { placed: boolean }>('/v1/exec/submit', ticket),
  execModify: (ref: string, changes: { limit_price?: Money; stop_price?: Money; trail_amount?: Money; breakeven?: boolean }) =>
    post<{ ok: boolean; summary: string }>('/v1/exec/modify', { ref, changes }),
  execCancel: (ref: string) => post<{ ok: boolean; summary: string }>('/v1/exec/cancel', { ref }),
  execFlatten: (symbol_id: string, qty?: number) =>
    post<{ ok: boolean; summary?: string; reason?: string }>('/v1/exec/flatten', { symbol_id, qty }),
  execMode: (mode: 'advisory' | 'confirm' | 'auto-within-limits') =>
    post<{ ok: boolean; mode: string; previous: string }>('/v1/exec/mode', { mode }),
  execResume: (resolution: string) => post<{ ok: boolean; mode: string }>('/v1/exec/resume', { resolution }),
  execAdopt: () => post<{ ok: boolean; adopted: string[]; summary: string }>('/v1/exec/adopt', {}),

  /** IBKR's contract directory, each match with its canonical symbol id. */
  symbolSearch: (q: string) =>
    get<{ results: SearchResult[] }>(`/v1/market/search?q=${encodeURIComponent(q)}`),
  /** Fill one series into the bar store — the same fetch `genesis chart` runs. */
  load: (symbol_id: string, timeframe: string) =>
    post<LoadResult>('/v1/market/load', { symbol_id, timeframe }),

  /**
   * Sector-ETF or futures performance over 1D/1W/1M/3M — the `PFM` board.
   * Tier 3, and `settled` says whether the last bar is finished: on a Monday
   * holiday the sectors carry Friday's close while the futures carry a Globex
   * session still trading, and the panel labels each for what it is.
   */
  performance: (asset: 'stocks' | 'futures') =>
    get<PerformanceBody>(`/v1/market/performance?asset=${asset}`),
}

/** One instrument's returns. A window longer than the instrument's history is
 *  `null` for that window only — a new contract has a 1D and no 3M. */
export interface PerformanceRow {
  symbol: string
  name: string
  group: string
  /** `etf` | `future` | `index`. A cash index does not settle; a future does. */
  kind: string
  last: number
  returns: Record<string, number | null>
}

export interface PerformanceBody {
  asset: 'stocks' | 'futures'
  tier: number
  /** The session the closes belong to, `YYYY-MM-DD`. */
  as_of: string
  /** False when that session is still trading. */
  settled: boolean
  windows: string[]
  /** Board order for the groups present, so rows never reshuffle between reads. */
  groups: string[]
  rows: PerformanceRow[]
  missing: string[]
}

/** One issuer's tile. Area needs a cap and colour needs a change, so a row
 *  missing either never arrives — it is named in `missing` instead. */
export interface HeatmapRow {
  symbol: string
  name: string
  sector: string
  market_cap: number
  close: number
  prev_close: number
  change_pct: number
}

export interface MoverRow {
  symbol: string
  name: string
  sector: string
  /** Percent of the index — holdings weight, or market-cap share for NDX. */
  weight: number
  close: number
  change_pct: number
  /** Null when the feed has no figure; such a row cannot be sized by it. */
  market_cap: number | null
  volume: number | null
  /** close × session volume, computed server-side. */
  dollar_volume: number | null
}

export interface MoverGroup {
  count: number
  weight: number
  /** Weight-averaged member change. Close to the ETF's print, not equal. */
  change_pct: number | null
  advancers: number
  decliners: number
  gainers: MoverRow[]
  losers: MoverRow[]
}

/** One scan result, as `genesis.screener.chat` saves it — chat, ⌘K, voice and SCR all write this. */
export interface ScreenPayload {
  scan: { criteria: { field: string; op: string; value: unknown }[]; sort: { field: string; direction: string } | null; limit: number } | null
  asked?: string
  understood?: string | null
  described?: string
  expression?: string
  terms?: string[]
  readings: { phrase?: string; as?: string; why?: string }[]
  unsupported: { phrase?: string; why?: string }[]
  question: string | null
  choices: string[]
  via?: 'model' | 'typed'
  count?: number
  universe?: number
  columns?: string[]
  matches?: Record<string, string | number | null>[]
  missing?: Record<string, number>
  as_of?: string | null
  degraded?: boolean
  saved_at?: string
}

export interface ScreenerField { name: string; unit: string; meaning: string }

export interface ScreenerBody {
  tier: number
  current: ScreenPayload | null
  snapshot: { as_of: string | null; rows: number; failed: string[]; stale: boolean }
  fields: ScreenerField[]
  text_fields: ScreenerField[]
  sectors: string[]
}

export interface MoversBody {
  code: string
  index: string
  tier: number
  weight_basis: string
  holdings_as_of: string | null
  as_of: string
  market_state: string
  rows: MoverRow[]
  total: MoverGroup
  sectors: Record<string, MoverGroup>
  missing: string[]
  universes: { code: string; name: string }[]
}

export interface HeatmapBody {
  index: string
  tier: number
  as_of: string
  /** Yahoo's session: `REGULAR` is still moving, `CLOSED`/`POST` is settled. */
  market_state: string
  rows: HeatmapRow[]
  /** Index members the feed could not price — usually one that has left it. */
  missing: string[]
}

export interface WatchlistMember {
  symbol: string
  /** Section within the list. `''` is the unsectioned default. */
  group: string
  added: string
}

export interface WatchlistBody {
  id: string
  name: string
  created: string
  members: WatchlistMember[]
}

/** One row's day change off settled closes, or why there isn't one. */
export type QuoteRow =
  | {
      /** The last *completed* daily close. Not a live price. */
      close: number
      prev_close: number
      change: number
      change_pct: number | null
      /** The session `close` belongs to, `YYYY-MM-DD`. */
      as_of: string
      error?: undefined
    }
  | { error: string }

export interface ConversationRow {
  id: string
  title: string
  updated: string
  turns: number
}

export interface ConversationTurn {
  ts: string
  role: 'operator' | 'genesis'
  text: string
  ok: boolean | null
  command: string | null
  detail: string | null
  data: Record<string, string> | null
  trace: string | null
}

export interface ConversationBody {
  id: string
  title: string
  created: string
  updated: string
  turns: ConversationTurn[]
}

export interface BrokerAccount {
  as_of: string
  /** From the account id the broker returned — `DU…` is paper. */
  mode: 'paper' | 'live'
  accounts: string[]
  /** account → tag (NetLiquidation, BuyingPower, …) → value. */
  values: Record<string, Record<string, { value: string; currency: string }>>
  positions: {
    account: string
    symbol: string
    sec_type: string
    position: number
    market_price: number
    market_value: number
    average_cost: number
    unrealized_pnl: number
    realized_pnl: number
  }[]
}

export interface BrokerAccountBody {
  gateway: string
  client_id: number
  market_data_type: 'delayed' | 'realtime'
  series: { symbol_id: string; timeframe: string }[]
  state: 'starting' | 'connecting' | 'syncing' | 'live' | 'quiet' | 'down'
  detail: string
  since: string
  login: string | null
  account: BrokerAccount | null
}

export interface LiveSeries { symbol_id: string; timeframe: string }

export interface SearchResult {
  symbol_id: string
  symbol: string
  /** IBKR's secType: STK, FUT, IND, CASH, CRYPTO. */
  sec_type: string
  exchange: string
  currency: string
  description: string
  derivatives: string[]
}

export interface LoadResult {
  ok: boolean
  symbol_id: string
  timeframe: string
  bars: number
  source: string
  tier: number
  last_bar_at: string | null
  skipped: { adapter: string; reason: string }[]
}

export interface GatewayState { status: string; health: string; detail: string }

export interface BrokerSettingsBody {
  login: { userid: string; password_saved: boolean; trading_mode: 'paper' | 'live'; env_file: string }
  gateway: GatewayState
  feed: { enabled: boolean; market_data_type: 'delayed' | 'realtime'; port: number; live: LiveSeries[] }
}


// ---------------------------------------------------------------------------
// the order path — mirrors of `src/genesis/execution/order_manager.py`
// ---------------------------------------------------------------------------

export interface OrderTicket {
  symbol_id: string
  side: 'buy' | 'sell'
  qty: number
  order_type: 'market' | 'limit'
  limit_price?: Money | null
  /** Offsets are points from entry; exactly one of offset or price for a fixed stop. */
  stop?: { kind: 'fixed' | 'trail' | 'none'; offset?: Money; price?: Money; trail?: Money }
  target?: { offset?: Money; price?: Money } | null
  tif?: 'GTC' | 'DAY'
  intent?: 'open' | 'close'
}

export interface ExecCheck { id: string; result: 'pass' | 'fail' | 'resize' | 'not_built'; detail: string }

export interface ExecDecision {
  proposal_id: string
  decision: 'approve' | 'resize' | 'reject'
  original_qty: number
  approved_qty: number
  binding_check: string | null
  worst_case_loss: Money | null
  requires_confirmation: boolean
  checks: ExecCheck[]
  elapsed_ms: number
  spoken_summary: string
}

export interface ProposeResult {
  ok: boolean
  reason?: string
  proposal: Record<string, unknown> & { arrival_mid: Money | null; arrival_source: string | null; local_symbol: string }
  decision: ExecDecision
  approval?: {
    approval_id: string
    approved_qty: number
    local_symbol: string
    worst_case_loss: Money | null
    requires_confirmation: boolean
    expires_at: string
  }
}

export interface PlaceResult { ok: boolean; client_order_id: string; summary: string }

export interface ExecOrder {
  client_order_id: string
  ref: string
  role: 'entry' | 'stop' | 'target' | 'close' | 'external' | 'unknown'
  symbol_id: string
  local_symbol: string
  con_id: number
  side: 'buy' | 'sell'
  qty: number
  filled: number
  remaining: number
  type: 'market' | 'limit' | 'stop' | 'trail' | string
  limit: Money | null
  stop: Money | null
  trail: Money | null
  status: string
  state: string
  working: boolean
  parent_id: number
  order_id: number
  bracket_group: string | null
  ours: boolean
  error: string | null
}

export interface ExecPosition {
  symbol_id: string
  local_symbol: string
  con_id: number
  qty: number
  avg_price: Money
  multiplier: Money
  unrealized_pnl: Money | null
  realized_pnl: Money | null
  daily_pnl: Money | null
  protected: boolean
  stop_cover: number
}

export interface ExecState {
  connection: { state: string; detail: string; since: string }
  account: string | null
  mode: 'advisory' | 'confirm' | 'auto-within-limits' | 'halt'
  one_click: boolean
  halt: { engaged: boolean; level?: string; trigger?: string; detail?: string; at?: string }
  reconciliation: { matched: boolean | null; detail: string; at: string | null; problems?: string[] }
  killswitch: { healthy: boolean; port: number }
  daily_pnl: Money | null
  available_funds: Money | null
  positions: ExecPosition[]
  orders: ExecOrder[]
  limits: { max_contracts_per_symbol: number; max_daily_loss_usd: Money; symbol_allowlist: string[] } | null
  as_of: string
}

export interface FillQualityRow {
  fill_id: string
  order: string
  symbol: string
  side: 'buy' | 'sell'
  qty: number
  fill_price: Money
  arrival_mid: Money | null
  arrival_source: string | null
  arrival_bps: Money | null
  slippage_dollars: Money | null
  time_to_fill_ms: number | null
  fees: Money
  adverse_selection_30s_bps: Money | null
  verdict: 'good' | 'normal' | 'poor' | 'pathological' | 'unmeasured'
  why: string
  ts: string
}

export interface ExecQualityBody {
  aggregate: {
    date: string
    fills: number
    measured_fills: number
    unmeasured_fills: number
    median_arrival_slippage_bps: Money | null
    limit_fill_rate: number | null
    total_fees: Money
    fees_per_contract: Money | null
    note: string | null
  }
  fills: FillQualityRow[]
}
