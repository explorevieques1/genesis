// Spec: Genesis Markdown/60-UI/UI Stack.md §3 Layout
//
// Named layouts, as data.
//
// The note is specific about why this shape and not another:
//
//   "Layouts serialise to JSON, which gives Voice UX something to target:
//    *'put the chart next to the risk gate'* resolves to a named layout preset
//    ... Presets live in config; the voice path selects among them and may
//    create one, **never computes pixel geometry**."
//
// That last clause is the design. A voice path that computed geometry would be
// a language model doing arithmetic about pixels, and it would fail in the
// specific way models fail — plausibly, producing a layout that is almost
// right and unusable. Selecting from a named set is a classification problem,
// which is the thing it is actually good at.
//
// So a preset is a name plus a list of panels. The *arrangement* is Dockview's
// serialised state, captured after a human has dragged things where they want
// them — geometry authored by a person, recalled by name.

import type { PageId } from '@/shell/pages'

/** Every panel the workspace system can place. */
export type PanelId =
  // charting
  | 'chart'
  | 'watchlist'
  | 'coverage'
  | 'symbol-detail'
  | 'markup-specs'
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
  // journal
  | 'journal-graph'
  | 'journal-entries'
  | 'journal-patterns'
  // settings
  | 'settings-audio'
  | 'settings-agents'
  | 'settings-data'
  | 'settings-approval'
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

export interface PanelSlot {
  id: PanelId
  title: string
  /**
   * Where it goes on a fresh layout. Dockview takes over once a person moves
   * anything, so this is a starting arrangement rather than a constraint.
   */
  position?: {
    referencePanel?: PanelId
    direction?: 'left' | 'right' | 'above' | 'below' | 'within'
  }
  /** Fraction of the container, applied on first placement only. */
  size?: number
}

export interface Preset {
  id: string
  label: string
  /** What this arrangement is for. Shown in the workspace menu. */
  hint: string
  page: PageId
  panels: PanelSlot[]
}

/**
 * The built-in presets, one or more per page.
 *
 * Deliberately few. A workspace switcher with twenty entries is a menu nobody
 * reads; these are the three or four arrangements that correspond to actual
 * activities — looking at a chart, reading a backtest, watching the fleet.
 */
export const PRESETS: Preset[] = [
  // -- charting ---------------------------------------------------------
  {
    id: 'chart.focus',
    label: 'Focus',
    hint: 'One chart, as large as the window allows',
    page: 'charting',
    panels: [
      { id: 'chart', title: 'Chart' },
      { id: 'watchlist', title: 'Series', position: { referencePanel: 'chart', direction: 'left' }, size: 0.2 },
    ],
  },
  {
    id: 'chart.analysis',
    label: 'Analysis',
    hint: 'Chart, the series list, provenance and what Genesis has drawn',
    page: 'charting',
    panels: [
      { id: 'chart', title: 'Chart' },
      { id: 'watchlist', title: 'Series', position: { referencePanel: 'chart', direction: 'left' }, size: 0.19 },
      { id: 'symbol-detail', title: 'Instrument', position: { referencePanel: 'chart', direction: 'right' }, size: 0.22 },
      { id: 'coverage', title: 'Coverage', position: { referencePanel: 'symbol-detail', direction: 'below' } },
      { id: 'markup-specs', title: 'Markup', position: { referencePanel: 'coverage', direction: 'within' } },
    ],
  },

  // -- backtest ---------------------------------------------------------
  {
    id: 'backtest.report',
    label: 'Report',
    hint: 'Equity curve, statistics and every trade the run produced',
    page: 'backtest',
    panels: [
      { id: 'backtest-equity', title: 'Equity' },
      { id: 'backtest-runner', title: 'Strategy', position: { referencePanel: 'backtest-equity', direction: 'left' }, size: 0.24 },
      { id: 'backtest-stats', title: 'Statistics', position: { referencePanel: 'backtest-equity', direction: 'right' }, size: 0.26 },
      { id: 'backtest-trades', title: 'Trades', position: { referencePanel: 'backtest-equity', direction: 'below' }, size: 0.34 },
      { id: 'backtest-history', title: 'History', position: { referencePanel: 'backtest-runner', direction: 'below' }, size: 0.4 },
    ],
  },
  {
    id: 'backtest.compare',
    label: 'Compare',
    hint: 'Past runs beside the current one',
    page: 'backtest',
    panels: [
      { id: 'backtest-history', title: 'History' },
      { id: 'backtest-equity', title: 'Equity', position: { referencePanel: 'backtest-history', direction: 'right' }, size: 0.62 },
      { id: 'backtest-stats', title: 'Statistics', position: { referencePanel: 'backtest-equity', direction: 'below' }, size: 0.42 },
    ],
  },

  // -- research ---------------------------------------------------------
  {
    id: 'research.company',
    label: 'Company',
    hint: 'Filings and fundamentals for one issuer',
    page: 'research',
    panels: [
      { id: 'company-profile', title: 'Company' },
      { id: 'tool-surface', title: 'Tools', position: { referencePanel: 'company-profile', direction: 'right' }, size: 0.3 },
    ],
  },
  {
    id: 'research.canvas',
    label: 'Canvas',
    hint: 'The node canvas, with the tool surface beside it',
    page: 'research',
    panels: [
      { id: 'research-canvas', title: 'Canvas' },
      { id: 'company-profile', title: 'Company', position: { referencePanel: 'research-canvas', direction: 'right' }, size: 0.28 },
    ],
  },

  // -- journal ----------------------------------------------------------
  {
    id: 'journal.graph',
    label: 'Graph',
    hint: 'Entries, lessons and symbols as a force graph',
    page: 'journal',
    panels: [
      { id: 'journal-graph', title: 'Graph' },
      { id: 'journal-entries', title: 'Entries', position: { referencePanel: 'journal-graph', direction: 'right' }, size: 0.28 },
      { id: 'journal-patterns', title: 'Patterns', position: { referencePanel: 'journal-entries', direction: 'below' } },
    ],
  },
  {
    id: 'journal.ledger',
    label: 'Ledger',
    hint: 'The entries themselves, with detected patterns beside them',
    page: 'journal',
    panels: [
      { id: 'journal-entries', title: 'Entries' },
      { id: 'journal-patterns', title: 'Patterns', position: { referencePanel: 'journal-entries', direction: 'right' }, size: 0.38 },
    ],
  },

  // -- fleet ------------------------------------------------------------
  {
    id: 'fleet.organism',
    label: 'Organism',
    hint: 'The body map, with the inspector and the event stream',
    page: 'fleet',
    panels: [
      { id: 'body-map', title: 'Body map' },
      { id: 'agent-inspector', title: 'Inspector', position: { referencePanel: 'body-map', direction: 'right' }, size: 0.24 },
      { id: 'event-stream', title: 'Events', position: { referencePanel: 'agent-inspector', direction: 'below' } },
    ],
  },
  {
    id: 'fleet.forensics',
    label: 'Forensics',
    hint: 'Trace one task, and see what it read and wrote',
    page: 'fleet',
    panels: [
      { id: 'trace', title: 'Trace' },
      { id: 'memory-fabric', title: 'Memory', position: { referencePanel: 'trace', direction: 'right' }, size: 0.4 },
      { id: 'execution-path', title: 'Execution', position: { referencePanel: 'memory-fabric', direction: 'below' } },
      { id: 'event-stream', title: 'Events', position: { referencePanel: 'trace', direction: 'below' }, size: 0.3 },
    ],
  },

  // -- settings ---------------------------------------------------------
  {
    id: 'settings.system',
    label: 'System',
    hint: 'Microphone, data feeds, agents and the tool surface',
    page: 'settings',
    panels: [
      { id: 'settings-agents', title: 'Agents' },
      { id: 'settings-audio', title: 'Voice', position: { referencePanel: 'settings-agents', direction: 'left' }, size: 0.3 },
      { id: 'settings-approval', title: 'Approval', position: { referencePanel: 'settings-audio', direction: 'below' } },
      { id: 'tool-surface', title: 'Tools', position: { referencePanel: 'settings-agents', direction: 'below' }, size: 0.42 },
    ],
  },
  {
    id: 'settings.data',
    label: 'Data',
    hint: 'What is held, from which feed, at what trust tier',
    page: 'settings',
    panels: [
      { id: 'settings-data', title: 'Data' },
      { id: 'coverage', title: 'Coverage', position: { referencePanel: 'settings-data', direction: 'right' }, size: 0.5 },
    ],
  },

  // -- automation -------------------------------------------------------
  {
    id: 'automation.schedule',
    label: 'Schedule',
    hint: 'The cadences actually running, and the builder that is not built',
    page: 'automation',
    panels: [
      { id: 'cadence', title: 'Running cadences' },
      { id: 'workflow-builder', title: 'Workflow builder', position: { referencePanel: 'cadence', direction: 'right' }, size: 0.46 },
    ],
  },

  // -- overview ---------------------------------------------------------
  {
    id: 'overview.system',
    label: 'System',
    hint: 'What exists, what holds data, and what is happening',
    page: 'overview',
    panels: [
      { id: 'capability-map', title: 'Capabilities' },
      { id: 'coverage', title: 'Data held', position: { referencePanel: 'capability-map', direction: 'right' }, size: 0.34 },
      { id: 'backtest-history', title: 'Recent runs', position: { referencePanel: 'coverage', direction: 'below' } },
      { id: 'event-stream', title: 'Events', position: { referencePanel: 'capability-map', direction: 'below' }, size: 0.3 },
    ],
  },
]

export function presetsFor(page: PageId): Preset[] {
  return PRESETS.filter((p) => p.page === page)
}

export function defaultPreset(page: PageId): Preset | undefined {
  return presetsFor(page)[0]
}

// ---------------------------------------------------------------------------
// persistence
// ---------------------------------------------------------------------------

const STORAGE_PREFIX = 'genesis.workspace.'

/**
 * Save the arrangement a person dragged into place.
 *
 * `localStorage`, wrapped, because every accessor here can throw — a private
 * window, cleared site data, or a browser told to block storage. A layout is a
 * convenience; losing it must never take the surface down with it, so a failed
 * read returns nothing and the preset's default arrangement is used.
 *
 * Deliberately per-viewer and local. A layout is not fleet state and has no
 * business on the daemon.
 */
export function saveLayout(presetId: string, layout: unknown): void {
  try {
    localStorage.setItem(STORAGE_PREFIX + presetId, JSON.stringify(layout))
  } catch {
    /* storage unavailable — the preset default still works */
  }
}

export function loadLayout(presetId: string): unknown | null {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + presetId)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function clearLayout(presetId: string): void {
  try {
    localStorage.removeItem(STORAGE_PREFIX + presetId)
  } catch {
    /* nothing to do */
  }
}

/** Which preset was last open on a page. */
export function rememberPreset(page: PageId, presetId: string): void {
  try {
    localStorage.setItem(`${STORAGE_PREFIX}last.${page}`, presetId)
  } catch {
    /* ignored */
  }
}

export function recallPreset(page: PageId): string | null {
  try {
    return localStorage.getItem(`${STORAGE_PREFIX}last.${page}`)
  } catch {
    return null
  }
}
