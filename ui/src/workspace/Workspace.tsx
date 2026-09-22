// Spec: Genesis Markdown/60-UI/UI Stack.md §3 Layout — Dockview
//
// The dock. Panels a person can split, drag, float, close and open again,
// seeded once per category and theirs from then on.
//
// Three things make this more than a wrapper around Dockview:
//
// **A category is a workspace.** One dock per main category, its arrangement
// saved under that category's id. There is no preset switcher any more: a
// category opens seeded with its own modules the first time, and after that it
// is whatever the operator built. "Charting" means *your* charting layout,
// including the journal graph you pulled in beside the chart.
//
// **A seed is a first run, not a state.** `SEEDS` lays panels out once. The
// moment anything is dragged or closed, Dockview's serialised layout is saved
// against the page id and used from then on — geometry authored by a person,
// recalled without being asked for.
//
// **A panel that throws does not take the page down.** Every panel is wrapped
// in its own boundary. `UI Stack`'s governing constraint is that the UI failing
// must never hide risk, and the concrete version of that here is: a chart
// library that throws on a malformed series must not blank the workspace that
// also contains the risk gauges. One panel shows an error; the rest keep
// rendering.

import { useCallback, useEffect, useRef } from 'react'
// v8 split the React bindings out of `dockview` (now a re-export of the
// framework-agnostic `dockview-core`) into `dockview-react`.
import { DockviewReact } from 'dockview-react'
import type { DockviewApi, DockviewReadyEvent, IDockviewPanelProps } from 'dockview'
import 'dockview/dist/styles/dockview.css'
import { PanelBoundary } from '@/components/PanelBoundary'
import type { PageId } from '@/shell/pages'
import { PANEL_COMPONENTS } from './panels'
import { setDockApi } from './dock'
import { loadLayout, saveLayout, MODULE_BY_ID, SEEDS } from './modules'

/**
 * Dockview's component map, with every panel wrapped once.
 *
 * Built at module scope rather than per render: Dockview keys panels by
 * component name, and handing it a new object identity on every render makes
 * it tear down and rebuild every panel — which, for a chart, means losing the
 * viewport the operator just set.
 */
const COMPONENTS = Object.fromEntries(
  Object.entries(PANEL_COMPONENTS).map(([id, Component]) => [
    id,
    (props: IDockviewPanelProps) => (
      <PanelBoundary name={id}>
        <Component {...props} />
      </PanelBoundary>
    ),
  ]),
)

export function Workspace({ page }: { page: PageId }) {
  const apiRef = useRef<DockviewApi | null>(null)
  // Which category the live dock is showing. Compared against the prop so a
  // switch rebuilds, while an unrelated re-render does not.
  const builtRef = useRef<PageId | null>(null)

  const build = useCallback((api: DockviewApi, target: PageId) => {
    api.clear()

    const saved = loadLayout(target)
    if (saved) {
      try {
        api.fromJSON(saved as never)
        builtRef.current = target
        return
      } catch {
        // A layout saved by an older build can reference a panel that no
        // longer exists. Falling through to the seed is the right recovery --
        // better a standard arrangement than an empty dock nobody asked for.
      }
    }

    // Seeds name modules; the dock needs panel instance ids, because the same
    // module may be placed more than once. Slots are keyed by module id within
    // one seed, which is enough for `referencePanel` and costs no ceremony.
    const placed = new Map<string, string>()
    for (const slot of SEEDS[target]) {
      const module = MODULE_BY_ID[slot.id]
      const panelId = `${slot.id}#seed`
      const reference = slot.position?.referencePanel
      const referenceId = reference ? placed.get(reference) : undefined
      api.addPanel({
        id: panelId,
        component: slot.id,
        title: module.title,
        position: referenceId
          ? { referencePanel: referenceId, direction: slot.position?.direction ?? 'right' }
          : undefined,
      })
      placed.set(slot.id, panelId)
    }

    // Sizes are applied after every panel exists, because a fraction of the
    // container means nothing until the container has been divided.
    for (const slot of SEEDS[target]) {
      if (!slot.size) continue
      const panel = api.getPanel(placed.get(slot.id) ?? '')
      if (!panel) continue
      const horizontal = slot.position?.direction === 'left' || slot.position?.direction === 'right'
      if (horizontal) {
        panel.api.setSize({ width: Math.round(api.width * slot.size) })
      } else {
        panel.api.setSize({ height: Math.round(api.height * slot.size) })
      }
    }
    builtRef.current = target
  }, [])

  const onReady = useCallback(
    (event: DockviewReadyEvent) => {
      apiRef.current = event.api
      // Published so the command line can open a panel into this dock without
      // being a child of it. See `dock.ts` -- it holds wiring, never state.
      setDockApi(event.api)
      build(event.api, page)

      // Persist on every structural change. Debounced, because dragging a
      // divider fires this continuously and serialising a layout on every
      // mouse-move frame is real work on a small machine.
      let timer: number | undefined
      const persist = () => {
        window.clearTimeout(timer)
        timer = window.setTimeout(() => {
          const current = builtRef.current
          if (!current) return
          try {
            saveLayout(current, event.api.toJSON())
          } catch {
            /* a layout that will not serialise is not worth crashing over */
          }
        }, 400)
      }
      event.api.onDidLayoutChange(persist)
    },
    [build, page],
  )

  useEffect(() => {
    const api = apiRef.current
    if (api && builtRef.current !== page) build(api, page)
  }, [page, build])

  // Unregister on unmount, so a stale api cannot be handed panels that would
  // land in a dock nobody is looking at.
  useEffect(() => () => setDockApi(null), [])

  return (
    <DockviewReact
      components={COMPONENTS}
      onReady={onReady}
      className="dockview-theme-genesis"
      // An empty dock is a legitimate state now -- "clear space" produces one
      // deliberately. The watermark says how to fill it rather than implying
      // something went wrong.
      watermarkComponent={Watermark}
    />
  )
}

function Watermark() {
  return (
    <div
      className="flex flex-col items-center justify-center h-full gap-1"
      style={{ color: 'var(--ink-ghost)' }}
    >
      <div className="label">empty workspace</div>
      <div style={{ fontSize: 'var(--fs-tiny)' }}>
        ⌘K, then a module code — CH chart, EV events, BM body map
      </div>
    </div>
  )
}
