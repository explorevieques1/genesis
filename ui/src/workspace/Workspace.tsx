// Spec: Genesis Markdown/60-UI/UI Stack.md §3 Layout — Dockview
//
// The dock. Panels a person can split, drag, float and close, arranged by a
// named preset and remembered once they have moved anything.
//
// Two things make this more than a wrapper around Dockview:
//
// **A preset is the default, not the state.** On first open a preset lays its
// panels out from `presets.ts`. The moment a person drags a divider, Dockview's
// serialised layout is saved against that preset id and used from then on. So
// "Analysis" means *your* analysis layout after the first time you adjust it,
// and "reset" is a real, discoverable action rather than something only a
// cleared cache can do.
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
import { PANEL_COMPONENTS } from './panels'
import {
  loadLayout, saveLayout, type PanelId, type Preset,
} from './presets'

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

export function Workspace({ preset }: { preset: Preset }) {
  const apiRef = useRef<DockviewApi | null>(null)
  // Which preset the live dock is showing. Compared against the prop so a
  // switch rebuilds, while an unrelated re-render does not.
  const builtRef = useRef<string | null>(null)

  const build = useCallback((api: DockviewApi, target: Preset) => {
    api.clear()

    const saved = loadLayout(target.id)
    if (saved) {
      try {
        api.fromJSON(saved as never)
        builtRef.current = target.id
        return
      } catch {
        // A layout saved by an older build can reference a panel that no
        // longer exists. Falling through to the preset default is the right
        // recovery -- better a standard arrangement than an empty dock.
      }
    }

    const placed = new Set<PanelId>()
    for (const slot of target.panels) {
      const reference = slot.position?.referencePanel
      api.addPanel({
        id: slot.id,
        component: slot.id,
        title: slot.title,
        position:
          reference && placed.has(reference)
            ? { referencePanel: reference, direction: slot.position?.direction ?? 'right' }
            : undefined,
        initialWidth: slot.size ? undefined : undefined,
      })
      placed.add(slot.id)
    }

    // Sizes are applied after every panel exists, because a fraction of the
    // container means nothing until the container has been divided.
    for (const slot of target.panels) {
      if (!slot.size) continue
      const panel = api.getPanel(slot.id)
      if (!panel) continue
      const horizontal = slot.position?.direction === 'left' || slot.position?.direction === 'right'
      if (horizontal) {
        panel.api.setSize({ width: Math.round(api.width * slot.size) })
      } else {
        panel.api.setSize({ height: Math.round(api.height * slot.size) })
      }
    }
    builtRef.current = target.id
  }, [])

  const onReady = useCallback(
    (event: DockviewReadyEvent) => {
      apiRef.current = event.api
      build(event.api, preset)

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
    [build, preset],
  )

  useEffect(() => {
    const api = apiRef.current
    if (api && builtRef.current !== preset.id) build(api, preset)
  }, [preset, build])

  return (
    <DockviewReact
      components={COMPONENTS}
      onReady={onReady}
      className="dockview-theme-genesis"
      // A dock with every panel closed is a dead page. Watermark says so and
      // points at the reset control rather than leaving a blank rectangle.
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
      <div className="label">no panels open</div>
      <div style={{ fontSize: 'var(--fs-tiny)' }}>
        pick a workspace from the top bar, or reset this one
      </div>
    </div>
  )
}
