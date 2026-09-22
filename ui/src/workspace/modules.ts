// Spec: Genesis Markdown/60-UI/Workspaces.md · 60-UI/Terminal.md
//
// Every module the workspace can hold, with a name of its own.
//
// This replaces `presets.ts`, and the difference is not cosmetic. Under presets
// a panel had an id and nothing else: its human title lived inside whichever
// preset slot happened to place it, so `coverage` was called "Coverage" on the
// charting page and "Data held" on overview, and a panel no preset mentioned
// (`markup-specs`, `trace`, `capability-map`) had no name at all — the command
// palette de-hyphenated the id and hoped.
//
// A thing you can search for by short code, group by category, and spawn by
// name needs an identity. That is what a `Module` is: id, code, title, home.
//
// **`home` is a hint, not a cage.** It seeds the category's first-run layout
// and it ranks the palette — in Settings, `AP` sorts above `CH`. It forbids
// nothing. Any module opens into any workspace, which is the whole of what
// makes this a terminal rather than eight fixed screens.
//
// Named layout presets are gone. They existed so [[Voice UX]] had something to
// target other than pixel geometry; the target is now a module code plus a
// category (`open CH in charting`), which is still classification rather than
// arithmetic, so the constraint that produced presets survives without them.

import type { PageId } from '@/shell/pages'

/** Every panel component the dock can place. */
export type PanelId =
  // charting
  | 'chart'
  | 'watchlist'
  | 'live-data'
  | 'watchlist-manager'
  | 'candle-ranges'
  | 'coverage'
  | 'symbol-detail'
  | 'markup-specs'
  | 'tradingview'
  | 'heatmap'
  | 'movers'
  | 'performance'
  // trade
  | 'broker-account'
  | 'broker-setup'
  | 'order-ticket'
  | 'trade-ideas'
  // backtest
  | 'backtest-runner'
  | 'backtest-equity'
  | 'backtest-stats'
  | 'backtest-trades'
  | 'backtest-history'
  // research
  | 'company-profile'
  | 'tool-surface'
  | 'research-canvas'
  | 'research-directory'
  | 'research-note'
  | 'screener'
  | 'news'
  | 'browser'
  // journal
  | 'journal-graph'
  | 'journal-entries'
  | 'journal-patterns'
  | 'journal-desk'
  | 'journal-marks'
  | 'notebook'
  | 'notebook-graph'
  // settings
  | 'settings-audio'
  | 'settings-agents'
  | 'settings-data'
  | 'settings-approval'
  | 'settings-models'
  // automation
  | 'workflow-builder'
  | 'cadence'
  // fleet & shared
  | 'body-map'
  | 'event-stream'
  | 'agent-inspector'
  | 'memory-fabric'
  | 'execution-path'
  | 'trace'
  | 'capability-map'
  | 'system-map'
  | 'biology'
  | 'dna'
  // Shipped without their id in this union, so `openPanel('econ-calendar')`
  // was a type error nobody saw while the typecheck was running against a
  // config that checks nothing.
  | 'econ-calendar'
  | 'feed'
  // shared — reachable from any workspace
  | 'ask-genesis'
  | 'task-manager'
  | 'status'
  | 'help'
  // The generic one. Deliberately not a module -- it is opened by *tool* name
  // carrying `params.toolId`, so one entry covers all 131 tools in the
  // catalogue and every one added later.
  | 'tool'

export interface Module {
  id: Exclude<PanelId, 'tool'>
  /** Two or three letters, unique, uppercase. Typed into the palette. */
  code: string
  /** The only place a module's human name lives. */
  title: string
  /** Where it seeds and where it ranks. Never where it is confined. */
  home: PageId
  /** Other things a person might type for it. Matched by prefix, like the code. */
  aliases?: string[]
  hint: string
}

export const MODULES: Module[] = [
  // -- charting ---------------------------------------------------------
  { id: 'chart', code: 'CH', title: 'Chart', home: 'charting', hint: 'Price, with what Genesis has drawn on it' },
  { id: 'watchlist', code: 'SR', title: 'Series', home: 'backtest', hint: 'Every series held, and how many bars of it — what a backtest can run on' },
  // IBKR's contracts only -- the feed, not the store. Kept apart from SR on purpose.
  { id: 'live-data', code: 'LD', title: 'Live data', home: 'charting', aliases: ['live', 'live data'], hint: 'The contracts IBKR streams — click one to chart it' },
  // Your own lists — arbitrary symbols on TradingView's feed, in sections,
  // red/green on the day. Not seeded into any layout: you open it by code.
  { id: 'watchlist-manager', code: 'WL', title: 'Watchlist', home: 'charting', aliases: ['watchlist', 'lists'], hint: 'Your symbol lists — pick one to chart it on TradingView' },
  // A window of price you kept. Not the bar store -- see `panels/ranges.tsx`.
  { id: 'candle-ranges', code: 'CR', title: 'Candle Ranges', home: 'charting', aliases: ['ranges', 'snippet'], hint: 'Capture and keep the bars around one setup' },
  { id: 'symbol-detail', code: 'IN', title: 'Instrument', home: 'charting', hint: 'What this symbol is, and where the data came from' },
  { id: 'coverage', code: 'CV', title: 'Coverage', home: 'charting', aliases: ['DH', 'data held'], hint: 'What is held, from which feed, over what span' },
  { id: 'markup-specs', code: 'MK', title: 'Markup', home: 'charting', hint: 'The markup specs agents have produced for this series' },
  // Not seeded into Charting. `CH` is the chart of record -- bars Genesis
  // holds, with provenance. This one is opened deliberately, because what it
  // shows is somebody else's data.
  // Not seeded anywhere. It is a whole-index picture you open when you want
  // one, which is the canvas-opens-empty rule (`Operating Model` §3).
  { id: 'heatmap', code: 'HM', title: 'Heatmap', home: 'overview', aliases: ['heat map', 'treemap'], hint: 'The Nasdaq-100 on the day — area by market cap, colour by change' },
  { id: 'movers', code: 'MOV', title: 'Index movers', home: 'overview', aliases: ['movers', 'gainers', 'losers', 'market map'], hint: 'Top gainers and losers in S&P 500, Nasdaq-100, Dow or a sector SPDR — pie by weight, click a sector to hone in' },
  { id: 'performance', code: 'PFM', title: 'Performance', home: 'overview', aliases: ['perf', 'sectors'], hint: 'Sectors and futures over 1D/1W/1M/3M — bars or tiles' },
  { id: 'tradingview', code: 'TV', title: 'TradingView', home: 'charting', hint: "Any symbol, on TradingView's own feed — tier 3, not Genesis data" },

  // -- trade ------------------------------------------------------------
  // The order path. Follows the chart's symbol; every order passes the risk engine.
  { id: 'order-ticket', code: 'TRD', title: 'Trade', home: 'trade', aliases: ['order', 'ticket', 'buy', 'sell', 'flatten', 'positions'], hint: 'Order ticket, position and working orders for the charted contract — paper, risk-gated' },
  // The desk's ideas, ranked, with the gate's own size beside each. Reads the
  // same store `genesis idea` and the Session Plan agent use — three authors,
  // one board.
  { id: 'trade-ideas', code: 'TI', title: 'Trade ideas', home: 'trade', aliases: ['ideas', 'desk', 'setups'], hint: 'Every live idea — news, synthesizer and yours — ranked and sized by the risk gate' },
  { id: 'broker-account', code: 'ACC', title: 'Account', home: 'trade', aliases: ['ibkr', 'balance'], hint: 'IBKR connection, balances and positions' },

  // -- backtest ---------------------------------------------------------
  { id: 'backtest-runner', code: 'SG', title: 'Strategy', home: 'backtest', hint: 'Configure and run a strategy over stored bars' },
  { id: 'backtest-equity', code: 'EQ', title: 'Equity', home: 'backtest', hint: 'The equity curve of the run being read' },
  { id: 'backtest-stats', code: 'ST', title: 'Statistics', home: 'backtest', hint: 'Return, drawdown, and the rest of the metrics' },
  { id: 'backtest-trades', code: 'TR', title: 'Trades', home: 'backtest', hint: 'Every fill the run produced' },
  { id: 'backtest-history', code: 'HI', title: 'History', home: 'backtest', aliases: ['RR', 'recent runs'], hint: 'Past runs, newest first' },

  // -- research ---------------------------------------------------------
  { id: 'research-canvas', code: 'CA', title: 'Canvas', home: 'research', hint: 'The knowledge graph, spatially' },
  { id: 'research-directory', code: 'RD', title: 'Research', home: 'research', hint: 'Everything the research agents have saved' },
  { id: 'research-note', code: 'RN', title: 'Note', home: 'research', hint: 'One saved note, with its sources' },
  // Not seeded. Opens when a screen is asked for — in chat, ⌘K or voice — or by `SCR`.
  { id: 'screener', code: 'SCR', title: 'Screener', home: 'research', aliases: ['screen', 'scan', 'stock screener'], hint: 'The S&P 500 screen you are building in chat — criteria, matches, edit by hand' },
  { id: 'news', code: 'NW', title: 'News', home: 'research', aliases: ['news', 'headlines', 'briefs'], hint: 'Headlines to scroll and read, AI summaries, and news briefs' },
  // Not seeded. A calendar that appears on its own is the pre-populated screen
  // Operating Model §3 forbids; the countdown in the status row is the ambient
  // half, and it opens this.
  { id: 'econ-calendar', code: 'EC', title: 'Economic calendar', home: 'research', aliases: ['econ', 'calendar', 'red folder', 'data releases', 'nfp', 'cpi', 'fomc'], hint: 'High-impact prints ahead — day, New York time, forecast vs previous, and how long until it lands' },
  { id: 'company-profile', code: 'CO', title: 'Company', home: 'research', hint: 'Filings and fundamentals for one issuer' },
  // Not seeded into any layout. `Operating Model` §3 -- the canvas opens
  // empty, and a browser nobody asked for is the most unrequested screen
  // there is. You open it by code, and it starts a real Chromium when you do.
  { id: 'browser', code: 'WEB', title: 'Browser', home: 'research', aliases: ['browser', 'internet', 'surf'], hint: 'A real browser in a panel — your logins, any site, streamed from a Chromium beside the daemon' },
  { id: 'tool-surface', code: 'TS', title: 'Tools', home: 'research', hint: 'The MCP catalogue — every tool, callable by hand' },

  // -- journal ----------------------------------------------------------
  { id: 'journal-graph', code: 'JG', title: 'Graph', home: 'journal', hint: 'Entries, lessons and symbols as a force graph' },
  { id: 'journal-entries', code: 'JE', title: 'Entries', home: 'journal', hint: 'The journal itself, entry by entry' },
  { id: 'journal-patterns', code: 'JP', title: 'Patterns', home: 'journal', hint: 'What the insight miner found across entries' },
  { id: 'journal-desk', code: 'JD', title: 'Journal desk', home: 'journal', aliases: ['digest', 'morning brief', 'lessons', 'health check', 'watchdog', 'drift'], hint: 'Run the journal agents by hand, and read the lessons they have drawn' },
  { id: 'journal-marks', code: 'JM', title: 'Marks', home: 'journal', aliases: ['marks', 'marked ranges', 'chart notes'], hint: 'Ranges of candles you marked — entries, exits and ideas, with the note you wrote' },
  // Your own notes, not the system's records. A vault of markdown files with
  // wikilinks -- the same vault the research family writes into, which is why
  // an agent's note and yours sit in one tree.
  { id: 'notebook', code: 'NOT', title: 'Notebook', home: 'journal', aliases: ['notes', 'vault'], hint: 'Your vault — folders, notes, and [[links]] between them' },
  { id: 'notebook-graph', code: 'NOD', title: 'Nodes', home: 'journal', aliases: ['graph view'], hint: 'The notebook as a graph — every note a dot, every link a line' },

  // -- automation -------------------------------------------------------
  { id: 'feed', code: 'FD', title: 'Feed', home: 'automation', aliases: ['feed', 'findings', 'inbox'], hint: 'What the automations have produced — notes, briefs and findings, newest first' },
  { id: 'cadence', code: 'CD', title: 'Running cadences', home: 'automation', hint: 'What is scheduled, and when it last ran' },
  { id: 'workflow-builder', code: 'WB', title: 'Workflow builder', home: 'automation', hint: 'Compose a workflow from agents and tools' },

  // -- fleet ------------------------------------------------------------
  { id: 'body-map', code: 'BM', title: 'Body map', home: 'fleet', hint: 'The organism: organs, families, what is awake' },
  { id: 'agent-inspector', code: 'IS', title: 'Inspector', home: 'fleet', hint: 'One agent — its contract, tier and last work' },
  { id: 'event-stream', code: 'EV', title: 'Events', home: 'fleet', hint: 'The live event stream, unfiltered' },
  { id: 'memory-fabric', code: 'MM', title: 'Memory', home: 'fleet', hint: 'The five layers, and what was written to them' },
  { id: 'execution-path', code: 'XP', title: 'Execution path', home: 'fleet', hint: 'Proposal, gate, approval, fill' },
  { id: 'trace', code: 'TC', title: 'Trace', home: 'fleet', hint: 'One task, end to end — who ran and what they read' },
  // Everything ⌘K reaches, drawn as a graph of what opens, shows and calls what.
  { id: 'system-map', code: 'MAP', title: 'System map', home: 'fleet', aliases: ['system map', 'function map'], hint: 'Every page, module, command, agent and tool, and how they connect — click one to open it' },
  // The organ map from Biological Design, as a tree: loop stage → organ → the notes behind it.
  { id: 'biology', code: 'BIO', title: 'Biology', home: 'fleet', aliases: ['biology', 'organs', 'anatomy'], hint: 'Every organ of the organism, its build status and live health' },
  // The genome: the vault and the prompts every organ was built from, and
  // whether the body map still tells the truth about the code.
  { id: 'dna', code: 'DNA', title: 'DNA', home: 'fleet', aliases: ['genome', 'spec'], hint: 'The spec vault and the prompts — what is built, what drifted, what the map says' },

  // -- overview ---------------------------------------------------------
  { id: 'capability-map', code: 'CM', title: 'Capabilities', home: 'overview', hint: 'What is built, what is spec, what is missing' },
  // The command line as a module: a saved conversation you can dock anywhere.
  // `home: overview` ranks it; it belongs to no category and opens into any.
  { id: 'ask-genesis', code: 'AI', title: 'Ask Genesis', home: 'overview', aliases: ['ask', 'chat'], hint: 'Talk to Genesis — a conversation, saved and yours' },
  // The status readout behind the chrome's status row. `overview` because that
  // is where you go to ask how the platform is, and the row itself opens it.
  { id: 'status', code: 'HLT', title: 'Status', home: 'overview', aliases: ['status', 'health'], hint: 'Daemon, organs, model tiers and data sources — is Genesis healthy' },
  // Work in flight, on any page. Not seeded into a layout -- the canvas opens
  // empty (Operating Model §3), and this is opened when you want to know.
  { id: 'task-manager', code: 'TM', title: 'Tasks', home: 'overview', aliases: ['tasks', 'task manager', 'jobs'], hint: 'What Genesis is working on right now, wherever you are' },
  { id: 'help', code: 'HLP', title: 'Help', home: 'overview', aliases: ['commands'], hint: 'Every command and module code you can use' },

  // -- settings ---------------------------------------------------------
  { id: 'settings-audio', code: 'VO', title: 'Voice', home: 'settings', hint: 'Microphone, wake word, speech out' },
  { id: 'settings-agents', code: 'AG', title: 'Agents', home: 'settings', hint: 'The roster, their tiers and their contracts' },
  { id: 'settings-data', code: 'DA', title: 'Data', home: 'settings', hint: 'Feeds, trust tiers and what each one provides' },
  { id: 'settings-approval', code: 'AP', title: 'Approval', home: 'settings', hint: 'Approval mode and the pre-trade gate' },
  { id: 'broker-setup', code: 'CON', title: 'Connections', home: 'settings', aliases: ['data feeds', 'connect', 'ibkr setup'], hint: 'Connect a data provider — IBKR login, gateway, live contracts, and a test' },
  { id: 'settings-models', code: 'MT', title: 'Model tiers', home: 'settings', aliases: ['models'], hint: 'Which model runs each tier, and what it spent today' },
]

export const MODULE_BY_ID = Object.fromEntries(
  MODULES.map((m) => [m.id, m]),
) as Record<Module['id'], Module>

/**
 * A short code that is not unique is a search that opens the wrong thing.
 *
 * Checked at module scope so a collision introduced by an edit fails on the
 * next page load rather than the next time someone types those two letters.
 * Codes and aliases share one namespace, because the palette matches both.
 */
{
  const seen = new Map<string, string>()
  for (const m of MODULES) {
    for (const token of [m.code, ...(m.aliases ?? [])]) {
      const key = token.toLowerCase()
      const owner = seen.get(key)
      if (owner) throw new Error(`module code collision: "${token}" on both ${owner} and ${m.id}`)
      seen.set(key, m.id)
    }
  }
}

export function modulesFor(page: PageId): Module[] {
  return MODULES.filter((m) => m.home === page)
}

// ---------------------------------------------------------------------------
// seeds — what a category looks like the first time you open it
// ---------------------------------------------------------------------------

export interface Slot {
  id: Module['id']
  position?: {
    /** Another slot in the same seed, by module id. */
    referencePanel?: Module['id']
    direction?: 'left' | 'right' | 'above' | 'below' | 'within'
  }
  /** Fraction of the container, applied after every slot exists. */
  size?: number
}

/**
 * One arrangement per category, used once.
 *
 * Out of the box a category opens with its own modules already running — you
 * land on Charting and there is a chart. After that the layout is *yours*: the
 * moment anything is dragged, split or closed, Dockview's serialised state is
 * saved against the page id and the seed is never consulted again.
 *
 * `home` has no seed and no dock. It is the command line, and it stays empty —
 * [[Operating Model]] §3.
 */
export const SEEDS: Record<PageId, Slot[]> = {
  home: [],

  overview: [
    { id: 'capability-map' },
    { id: 'coverage', position: { referencePanel: 'capability-map', direction: 'right' }, size: 0.34 },
    { id: 'backtest-history', position: { referencePanel: 'coverage', direction: 'below' } },
    { id: 'event-stream', position: { referencePanel: 'capability-map', direction: 'below' }, size: 0.3 },
  ],

  charting: [
    { id: 'chart' },
    // Live data is where symbols get picked. Series is the bar store, which is
    // what a backtest reads -- it is seeded on Backtest, not here.
    { id: 'live-data', position: { referencePanel: 'chart', direction: 'left' }, size: 0.19 },
    { id: 'symbol-detail', position: { referencePanel: 'chart', direction: 'right' }, size: 0.22 },
    { id: 'coverage', position: { referencePanel: 'symbol-detail', direction: 'below' } },
    { id: 'markup-specs', position: { referencePanel: 'coverage', direction: 'within' } },
  ],

  // Trade opens on the execution path and a chart. Seeded with what exists
  // rather than left blank: a category you can reach and that shows nothing is
  // the dead end Operating Model §3 is written against. It grows as the desk
  // modules get built.
  trade: [
    { id: 'chart' },
    { id: 'execution-path', position: { referencePanel: 'chart', direction: 'below' }, size: 0.4 },
    { id: 'order-ticket', position: { referencePanel: 'chart', direction: 'right' }, size: 0.3 },
    { id: 'trade-ideas', position: { referencePanel: 'order-ticket', direction: 'within' } },
    { id: 'broker-account', position: { referencePanel: 'order-ticket', direction: 'within' } },
    { id: 'live-data', position: { referencePanel: 'order-ticket', direction: 'below' }, size: 0.3 },
    { id: 'watchlist-manager', position: { referencePanel: 'chart', direction: 'left' }, size: 0.2 },
  ],

  research: [
    { id: 'research-directory' },
    { id: 'research-note', position: { referencePanel: 'research-directory', direction: 'right' }, size: 0.62 },
  ],

  backtest: [
    { id: 'backtest-equity' },
    { id: 'backtest-runner', position: { referencePanel: 'backtest-equity', direction: 'left' }, size: 0.24 },
    { id: 'backtest-stats', position: { referencePanel: 'backtest-equity', direction: 'right' }, size: 0.26 },
    { id: 'backtest-trades', position: { referencePanel: 'backtest-equity', direction: 'below' }, size: 0.34 },
    { id: 'backtest-history', position: { referencePanel: 'backtest-runner', direction: 'below' }, size: 0.4 },
    { id: 'watchlist', position: { referencePanel: 'backtest-history', direction: 'within' } },
  ],

  // The notebook is the thing you actually open Journal for, so it takes the
  // main area and the graph sits beside it -- clicking a dot there opens the
  // note here, which is the loop the two modules exist to make.
  journal: [
    { id: 'notebook' },
    { id: 'notebook-graph', position: { referencePanel: 'notebook', direction: 'right' }, size: 0.34 },
    { id: 'journal-entries', position: { referencePanel: 'notebook-graph', direction: 'below' } },
    { id: 'journal-graph', position: { referencePanel: 'journal-entries', direction: 'within' } },
    { id: 'journal-patterns', position: { referencePanel: 'journal-entries', direction: 'within' } },
    { id: 'journal-desk', position: { referencePanel: 'journal-entries', direction: 'within' } },
  ],

  automation: [
    { id: 'cadence' },
    { id: 'workflow-builder', position: { referencePanel: 'cadence', direction: 'right' }, size: 0.46 },
  ],

  fleet: [
    { id: 'body-map' },
    { id: 'agent-inspector', position: { referencePanel: 'body-map', direction: 'right' }, size: 0.24 },
    { id: 'event-stream', position: { referencePanel: 'agent-inspector', direction: 'below' } },
  ],

  settings: [
    { id: 'settings-agents' },
    { id: 'settings-audio', position: { referencePanel: 'settings-agents', direction: 'left' }, size: 0.3 },
    { id: 'settings-approval', position: { referencePanel: 'settings-audio', direction: 'below' } },
    { id: 'tool-surface', position: { referencePanel: 'settings-agents', direction: 'below' }, size: 0.42 },
  ],
}

// ---------------------------------------------------------------------------
// persistence
// ---------------------------------------------------------------------------

const STORAGE_PREFIX = 'genesis.workspace.'

/**
 * Save the arrangement a person dragged into place, per category.
 *
 * `localStorage`, wrapped, because every accessor here can throw — a private
 * window, cleared site data, or a browser told to block storage. A layout is a
 * convenience; losing it must never take the surface down, so a failed read
 * returns nothing and the seed is used.
 *
 * Deliberately per-viewer and local. A layout is not fleet state and has no
 * business on the daemon.
 */
export function saveLayout(page: PageId, layout: unknown): void {
  try {
    localStorage.setItem(STORAGE_PREFIX + page, JSON.stringify(layout))
  } catch {
    /* storage unavailable — the seed still works */
  }
}

export function loadLayout(page: PageId): unknown | null {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + page)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}
