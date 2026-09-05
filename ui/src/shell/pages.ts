// Spec: Genesis Markdown/60-UI/UI Stack.md §3 Layout · 60-UI/Dashboard.md
//
// The pages, declared once.
//
// Nav, the command palette, the workspace presets and the keyboard shortcuts
// all read this list. That is the point: a page added in one place appears in
// all four, and cannot appear in the nav but be unreachable by ⌘K, which is the
// usual way a surface grows a dead tab.
//
// **`requires` is load-bearing, not documentation.** Each page names the
// capability it needs, and the shell dims a page whose capability probe came
// back `built: false` — so the nav itself reports what the system can do. A
// person looking at the top bar can see that Automation is not built without
// clicking it, and clicking it explains what is missing rather than showing an
// empty canvas that implies it should be working.

export type PageId =
  | 'overview'
  | 'charting'
  | 'research'
  | 'backtest'
  | 'journal'
  | 'automation'
  | 'fleet'
  | 'settings'

export interface PageDef {
  id: PageId
  label: string
  /** One line, shown in the command palette and as the nav tooltip. */
  hint: string
  /**
   * The capability this page is about. `null` for pages that are always
   * meaningful — Settings works precisely when things are broken, and Overview
   * exists to report what is missing.
   */
  requires: string | null
  /** Digit shortcut: ⌘1 … ⌘8, in this order. */
  key: string
}

export const PAGES: PageDef[] = [
  {
    id: 'overview',
    label: 'Overview',
    hint: 'What this system currently is — organs present, data held, work done',
    requires: null,
    key: '1',
  },
  {
    id: 'charting',
    label: 'Charting',
    hint: 'Price, the series Genesis holds, and the charts it has drawn',
    requires: 'marketdata.bars',
    key: '2',
  },
  {
    id: 'research',
    label: 'Research',
    hint: 'Companies, filings and the tool surface available to answer a question',
    requires: null,
    key: '3',
  },
  {
    id: 'backtest',
    label: 'Backtest',
    hint: 'Run a strategy over stored bars and read the result',
    requires: 'backtest.engine',
    key: '4',
  },
  {
    id: 'journal',
    label: 'Journal',
    hint: 'Trades, lessons and the graph between them',
    requires: 'journal.store',
    key: '5',
  },
  {
    id: 'automation',
    label: 'Automation',
    hint: 'Workflows Genesis can run on a cadence or an event',
    requires: 'automation.workflows',
    key: '6',
  },
  {
    id: 'fleet',
    label: 'Fleet',
    hint: 'The organism: agents, traces, memory and the execution path',
    requires: null,
    key: '7',
  },
  {
    id: 'settings',
    label: 'Settings',
    hint: 'Microphone, data, agents, tools and approval mode',
    requires: null,
    key: '8',
  },
]

export const PAGE_BY_ID = Object.fromEntries(PAGES.map((p) => [p.id, p])) as Record<PageId, PageDef>

/**
 * The page the shell opens on.
 *
 * Overview, not a dashboard of positions — because at this phase the most
 * useful thing the surface can tell you is what it is. A landing page showing
 * an empty positions table would imply the system trades, which it does not
 * yet.
 */
export const DEFAULT_PAGE: PageId = 'overview'
