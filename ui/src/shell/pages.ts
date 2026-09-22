// Spec: Genesis Markdown/60-UI/UI Stack.md §3 Layout · 60-UI/Dashboard.md
//
// The pages, declared once.
//
// The pages are the **main categories**, and each one is a workspace: a dock
// with its own persisted arrangement, into which any module can be spawned.
//
// Nav, the command palette, the seed layouts and the keyboard shortcuts all
// read this list. That is the point: a page added in one place appears in all
// four, and cannot appear in the nav but be unreachable by ⌘K, which is the
// usual way a surface grows a dead tab.
//
// **`requires` is load-bearing, not documentation.** Each page names the
// capability it needs, and the shell dims a page whose capability probe came
// back `built: false` — so the nav itself reports what the system can do. A
// person looking at the top bar can see that Automation is not built without
// clicking it, and clicking it explains what is missing rather than showing an
// empty canvas that implies it should be working.

export type PageId =
  | 'home'
  | 'overview'
  | 'charting'
  | 'trade'
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
  /** Digit shortcut: ⌘1 … ⌘9 then ⌘0, in this order. */
  key: string
}

export const PAGES: PageDef[] = [
  {
    id: 'home',
    label: 'Home',
    // Operating Model §3. The landing page holds nothing: a command line, the
    // safety strip, the core. Panels arrive because someone asked for them.
    //
    // It was called "Canvas", which named the *shape* of the page rather than
    // its job, and collided with the research canvas — a real module you can
    // spawn (`CA`). This is where you talk to Genesis; Home says that.
    //
    // `requires: null` because an empty page is meaningful in every state of
    // the system — it is the one page that is never dimmed and never wrong.
    hint: 'Start here. Type to see everything you can reach',
    requires: null,
    key: '1',
  },
  {
    id: 'overview',
    label: 'Overview',
    hint: 'What this system currently is — organs present, data held, work done',
    requires: null,
    key: '2',
  },
  {
    id: 'charting',
    label: 'Charting',
    hint: 'Price, the series Genesis holds, and the charts it has drawn',
    requires: 'marketdata.bars',
    key: '3',
  },
  {
    id: 'trade',
    label: 'Trade',
    hint: 'The active-trading desk — the execution path, and what you are in',
    // `execution.broker`, so the nav dims until a broker is actually wired.
    // Trade is the one category where a page that *looks* ready and is not is
    // dangerous rather than merely misleading — Safety Invariants §1.
    requires: 'execution.broker',
    key: '4',
  },
  {
    id: 'research',
    label: 'Research',
    hint: 'What the research agents found — notes, ideas and their sources',
    requires: null,
    key: '5',
  },
  {
    id: 'backtest',
    label: 'Backtest',
    hint: 'Run a strategy over stored bars and read the result',
    requires: 'backtest.engine',
    key: '6',
  },
  {
    id: 'journal',
    label: 'Journal',
    hint: 'Your notebook, the trades, and the graph between them',
    // `null` since the notebook landed here. It was `journal.store`, which
    // dimmed the whole page until the trade journal agent had written its
    // database — and now that would make `NOT` and `NOD` unreachable, though
    // a vault of markdown needs no database at all. The panels that *do* need
    // `journal.store` still gate themselves on it.
    requires: null,
    key: '7',
  },
  {
    id: 'automation',
    label: 'Automation',
    hint: 'Workflows Genesis can run on a cadence or an event',
    requires: 'automation.workflows',
    key: '8',
  },
  {
    id: 'fleet',
    label: 'Fleet',
    hint: 'The organism: agents, traces, memory and the execution path',
    requires: null,
    key: '9',
  },
  {
    id: 'settings',
    label: 'Settings',
    hint: 'Microphone, data, agents, tools and approval mode',
    requires: null,
    key: '0',
  },
]

export const PAGE_BY_ID = Object.fromEntries(PAGES.map((p) => [p.id, p])) as Record<PageId, PageDef>

/**
 * The page the shell opens on.
 *
 * **An empty page** — Operating Model §3.
 *
 * This was `overview`, which reported what the system currently is. That is a
 * real page and a useful one, and it was still the wrong front door: it
 * answered a question nobody asked. The first screen teaches the operator what
 * the software is about, and a screen that fills itself teaches them that
 * things appear on their own — exactly backwards for a system where a panel
 * appearing means an agent decided something.
 *
 * The empty screen only works because the input is self-describing: one
 * keystroke in the command line reveals every page, panel, series, agent and
 * tool by name. Discoverability lives in the input, not in a pre-populated
 * screen.
 */
export const DEFAULT_PAGE: PageId = 'home'
