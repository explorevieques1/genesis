// Spec: Genesis Markdown/40-Memory/Memory Fabric.md · 60-UI/UI Stack.md §6
//
// A force graph on a canvas — the Obsidian-shaped view of the journal.
//
// Canvas rather than SVG, and d3-force rather than React Flow. React Flow is
// reserved by the spec for Fleet View, where nodes are *addressable things*
// with their own React content. Here they are dots: a thousand of them, moving
// sixty times a second, none of which needs a DOM node. A thousand SVG circles
// with transforms is a thousand style recalculations per frame, and on the
// machine this runs on that is the whole frame budget.
//
// **The selection behaviour is the Handshake reference, and it is subtractive.**
// Clicking a node does not light it up. It dims everything that is not
// connected to it, eases the camera toward it, and reveals its neighbours'
// labels in a short stagger. The surface never gets *louder* when you interact
// with it — it gets quieter everywhere else. That is what makes a dense graph
// readable rather than festive, and it is also why it degrades cleanly: with
// `--motion-scale: 0` the same selection still works, it just arrives instantly.
//
// The simulation stops. An idle force graph that keeps ticking is a laptop fan
// at 3 a.m. for a picture that is not changing — `UI Stack`'s "an organism at
// rest should cost nothing" applies to the renderer too, so the loop halts once
// alpha decays and restarts only on interaction.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation,
  type Simulation, type SimulationLinkDatum, type SimulationNodeDatum,
} from 'd3-force'
import { approach, motionScale } from '@/lib/motion'
import { withAlpha } from '@/lib/format'

export interface GraphNodeInput {
  id: string
  kind: string
  label: string
  /** Drives radius. Anything countable — trades on a symbol, evidence count. */
  weight?: number
  /** Overrides the palette for this node. */
  color?: string
}

export interface GraphEdgeInput {
  source: string
  target: string
  kind: string
}

interface Node extends SimulationNodeDatum, GraphNodeInput {
  radius: number
}
type Link = SimulationLinkDatum<Node> & { kind: string }

interface Props {
  nodes: GraphNodeInput[]
  edges: GraphEdgeInput[]
  /** Node id → colour. Falls back to `--ink-faint`. */
  palette?: Record<string, string>
  selectedId?: string | null
  onSelect?: (id: string | null) => void
}

const RADIUS_BASE = 3.2

export function ForceGraph({ nodes, edges, palette, selectedId, onSelect }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const simulation = useRef<Simulation<Node, Link> | null>(null)
  const frame = useRef(0)
  const [hovered, setHovered] = useState<string | null>(null)

  /**
   * The camera. Held in a ref rather than state because it is written every
   * frame — putting it in state would re-render React sixty times a second to
   * move a canvas that React does not draw.
   */
  const view = useRef({ x: 0, y: 0, k: 1, targetX: 0, targetY: 0, targetK: 1 })
  const dragging = useRef<{ node: Node | null; panning: boolean; lastX: number; lastY: number }>({
    node: null, panning: false, lastX: 0, lastY: 0,
  })

  /** Adjacency, so a selection can dim in O(1) per node rather than scanning. */
  const neighbours = useMemo(() => {
    const map = new Map<string, Set<string>>()
    for (const edge of edges) {
      if (!map.has(edge.source)) map.set(edge.source, new Set())
      if (!map.has(edge.target)) map.set(edge.target, new Set())
      map.get(edge.source)!.add(edge.target)
      map.get(edge.target)!.add(edge.source)
    }
    return map
  }, [edges])

  const nodeData = useMemo<Node[]>(
    () => nodes.map((n) => ({
      ...n,
      radius: RADIUS_BASE + Math.sqrt(n.weight ?? 1) * 1.9,
    })),
    [nodes],
  )

  // -- simulation -------------------------------------------------------
  useEffect(() => {
    if (!nodeData.length) return
    const byId = new Map(nodeData.map((n) => [n.id, n]))
    const links: Link[] = edges
      .filter((e) => byId.has(e.source) && byId.has(e.target))
      .map((e) => ({ source: byId.get(e.source)!, target: byId.get(e.target)!, kind: e.kind }))

    const sim = forceSimulation<Node, Link>(nodeData)
      .force('link', forceLink<Node, Link>(links).id((d) => d.id).distance(42).strength(0.32))
      .force('charge', forceManyBody<Node>().strength(-120).distanceMax(320))
      .force('center', forceCenter(0, 0))
      // Collision keeps labels from stacking. Without it a dense cluster is an
      // unreadable blob, which is the usual failure of this kind of view.
      .force('collide', forceCollide<Node>((d) => d.radius + 3))
      .alphaDecay(0.035)
      // `stop()` immediately: the render loop drives ticks, so the simulation
      // and the paint stay on one clock instead of two.
      .stop()

    simulation.current = sim
    // Pre-settle off-screen. Dropping the user into a graph mid-explosion looks
    // broken; 80 ticks is enough to reach a readable arrangement.
    for (let i = 0; i < 80; i++) sim.tick()
    sim.alpha(0.35)

    return () => { sim.stop(); simulation.current = null }
  }, [nodeData, edges])

  // -- render loop ------------------------------------------------------
  const draw = useCallback(() => {
    const element = canvas.current
    const sim = simulation.current
    if (!element || !sim) return
    const context = element.getContext('2d')
    if (!context) return

    const style = getComputedStyle(document.documentElement)
    const token = (name: string, fallback: string) =>
      style.getPropertyValue(name).trim() || fallback
    const inkFaint = token('--ink-faint', '#4d6076')
    const hairline = token('--hairline-bright', '#223044')
    const core = token('--core', '#3d8bff')
    const ink = token('--ink', '#d6e2f0')

    const dpr = window.devicePixelRatio || 1
    const width = element.clientWidth
    const height = element.clientHeight
    if (element.width !== width * dpr || element.height !== height * dpr) {
      element.width = width * dpr
      element.height = height * dpr
    }

    const v = view.current
    const scale = motionScale()
    // With motion off the camera snaps; with it on it eases. Same destination
    // either way, which is what makes the reduced tier a removal rather than a
    // different behaviour.
    if (scale === 0) {
      v.x = v.targetX; v.y = v.targetY; v.k = v.targetK
    } else {
      v.x = approach(v.x, v.targetX, 0.16, 16.7)
      v.y = approach(v.y, v.targetY, 0.16, 16.7)
      v.k = approach(v.k, v.targetK, 0.16, 16.7)
    }

    context.setTransform(dpr, 0, 0, dpr, 0, 0)
    context.clearRect(0, 0, width, height)
    context.translate(width / 2 + v.x, height / 2 + v.y)
    context.scale(v.k, v.k)

    const focus = selectedId ?? hovered
    const near = focus ? neighbours.get(focus) ?? new Set<string>() : null
    const isLit = (id: string) => !focus || id === focus || near!.has(id)

    // -- edges, behind everything
    context.lineWidth = 1 / v.k
    for (const link of (sim.force('link') as ReturnType<typeof forceLink<Node, Link>>).links()) {
      const source = link.source as Node
      const target = link.target as Node
      if (source.x == null || target.x == null) continue
      const lit = isLit(source.id) && isLit(target.id)
      context.strokeStyle = lit
        ? (focus ? core : hairline)
        : withAlpha(hairline, 0.3)
      context.globalAlpha = lit ? (focus ? 0.7 : 0.4) : 0.12
      context.beginPath()
      context.moveTo(source.x, source.y!)
      context.lineTo(target.x!, target.y!)
      context.stroke()
    }

    // -- nodes
    context.globalAlpha = 1
    for (const node of sim.nodes()) {
      if (node.x == null || node.y == null) continue
      const lit = isLit(node.id)
      const colour = node.color ?? palette?.[node.kind] ?? inkFaint
      context.globalAlpha = lit ? 1 : 0.22
      context.beginPath()
      context.arc(node.x, node.y, node.radius, 0, Math.PI * 2)
      context.fillStyle = colour
      context.fill()

      if (node.id === selectedId) {
        // A ring, not a colour change: shape survives greyscale and
        // red-green deficiency, which `Fleet View` requires of every state.
        context.beginPath()
        context.arc(node.x, node.y, node.radius + 3.5 / v.k, 0, Math.PI * 2)
        context.strokeStyle = core
        context.lineWidth = 1.5 / v.k
        context.stroke()
      }
    }

    // -- labels, only where they can be read
    //
    // Drawn for the focused node and its neighbours, or for everything once
    // zoomed in far enough that they will not overlap. A graph that labels
    // every node at every zoom is a graph nobody can read.
    const labelAll = v.k > 1.7
    context.globalAlpha = 1
    context.font = `${10 / v.k}px ${token('--font-ui', 'sans-serif')}`
    context.textAlign = 'center'
    context.textBaseline = 'top'
    for (const node of sim.nodes()) {
      if (node.x == null || node.y == null) continue
      const show = labelAll || (focus ? isLit(node.id) : false)
      if (!show) continue
      context.fillStyle = node.id === focus ? ink : inkFaint
      context.fillText(
        node.label.length > 28 ? `${node.label.slice(0, 27)}…` : node.label,
        node.x,
        node.y + node.radius + 3 / v.k,
      )
    }

    // Tick only while there is energy left, or while something is being
    // dragged. An arranged graph costs nothing.
    if (sim.alpha() > sim.alphaMin() || dragging.current.node) {
      sim.tick()
      frame.current = requestAnimationFrame(draw)
    } else if (
      Math.abs(v.x - v.targetX) > 0.4 ||
      Math.abs(v.y - v.targetY) > 0.4 ||
      Math.abs(v.k - v.targetK) > 0.004
    ) {
      // Still travelling to a selection: keep painting, do not keep simulating.
      frame.current = requestAnimationFrame(draw)
    } else {
      frame.current = 0
    }
  }, [neighbours, selectedId, hovered, palette])

  const kick = useCallback(() => {
    if (!frame.current) frame.current = requestAnimationFrame(draw)
  }, [draw])

  useEffect(() => {
    kick()
    return () => { if (frame.current) cancelAnimationFrame(frame.current); frame.current = 0 }
  }, [kick])

  // Redraw when the selection changes even if the simulation has settled.
  useEffect(() => { kick() }, [selectedId, hovered, kick])

  // -- camera: ease toward the selection --------------------------------
  useEffect(() => {
    const sim = simulation.current
    if (!sim || !selectedId) return
    const node = sim.nodes().find((n) => n.id === selectedId)
    if (!node || node.x == null || node.y == null) return
    const v = view.current
    v.targetK = Math.max(v.k, 1.5)
    v.targetX = -node.x * v.targetK
    v.targetY = -node.y * v.targetK
    kick()
  }, [selectedId, kick])

  // -- pointer ----------------------------------------------------------
  const pick = useCallback((clientX: number, clientY: number): Node | null => {
    const element = canvas.current
    const sim = simulation.current
    if (!element || !sim) return null
    const rect = element.getBoundingClientRect()
    const v = view.current
    const x = (clientX - rect.left - rect.width / 2 - v.x) / v.k
    const y = (clientY - rect.top - rect.height / 2 - v.y) / v.k
    let best: Node | null = null
    let bestDistance = Infinity
    for (const node of sim.nodes()) {
      if (node.x == null || node.y == null) continue
      const distance = Math.hypot(node.x - x, node.y - y)
      // A generous hit radius: these dots are 4 px across and a person should
      // not have to be precise to select one.
      if (distance < node.radius + 8 && distance < bestDistance) {
        best = node; bestDistance = distance
      }
    }
    return best
  }, [])

  useEffect(() => {
    const element = canvas.current
    if (!element) return

    const onDown = (event: PointerEvent) => {
      const node = pick(event.clientX, event.clientY)
      dragging.current = {
        node, panning: !node, lastX: event.clientX, lastY: event.clientY,
      }
      if (node) {
        simulation.current?.alphaTarget(0.2)
        node.fx = node.x; node.fy = node.y
      }
      element.setPointerCapture(event.pointerId)
      kick()
    }

    const onMove = (event: PointerEvent) => {
      const drag = dragging.current
      if (drag.node) {
        const v = view.current
        const rect = element.getBoundingClientRect()
        drag.node.fx = (event.clientX - rect.left - rect.width / 2 - v.x) / v.k
        drag.node.fy = (event.clientY - rect.top - rect.height / 2 - v.y) / v.k
        kick()
        return
      }
      if (drag.panning) {
        const v = view.current
        v.targetX += event.clientX - drag.lastX
        v.targetY += event.clientY - drag.lastY
        drag.lastX = event.clientX
        drag.lastY = event.clientY
        kick()
        return
      }
      const node = pick(event.clientX, event.clientY)
      const id = node?.id ?? null
      element.style.cursor = node ? 'pointer' : 'grab'
      setHovered((current) => (current === id ? current : id))
    }

    const onUp = (event: PointerEvent) => {
      const drag = dragging.current
      if (drag.node) {
        // Released, not pinned. Leaving fx/fy set would freeze the node and
        // slowly turn the graph into a hand-arranged diagram nobody meant to
        // make.
        drag.node.fx = null
        drag.node.fy = null
        simulation.current?.alphaTarget(0)
      } else if (!drag.panning || (Math.abs(event.clientX - drag.lastX) < 3)) {
        const node = pick(event.clientX, event.clientY)
        onSelect?.(node?.id ?? null)
      }
      dragging.current = { node: null, panning: false, lastX: 0, lastY: 0 }
      element.releasePointerCapture(event.pointerId)
      kick()
    }

    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const v = view.current
      const factor = Math.exp(-event.deltaY * 0.0016)
      v.targetK = Math.min(6, Math.max(0.25, v.targetK * factor))
      kick()
    }

    const onLeave = () => setHovered(null)

    element.addEventListener('pointerdown', onDown)
    element.addEventListener('pointermove', onMove)
    element.addEventListener('pointerup', onUp)
    element.addEventListener('pointerleave', onLeave)
    element.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      element.removeEventListener('pointerdown', onDown)
      element.removeEventListener('pointermove', onMove)
      element.removeEventListener('pointerup', onUp)
      element.removeEventListener('pointerleave', onLeave)
      element.removeEventListener('wheel', onWheel)
    }
  }, [pick, onSelect, kick])

  // Repaint on container resize — the canvas is sized from its box.
  useEffect(() => {
    if (!host.current) return
    const observer = new ResizeObserver(() => kick())
    observer.observe(host.current)
    return () => observer.disconnect()
  }, [kick])

  return (
    <div ref={host} style={{ position: 'relative', width: '100%', height: '100%' }}>
      <canvas
        ref={canvas}
        style={{ width: '100%', height: '100%', display: 'block', cursor: 'grab' }}
      />
      {selectedId && (
        <button
          className="btn-ghost"
          style={{ position: 'absolute', top: 6, right: 6 }}
          onClick={() => {
            onSelect?.(null)
            const v = view.current
            v.targetX = 0; v.targetY = 0; v.targetK = 1
            kick()
          }}
        >
          clear focus
        </button>
      )}
    </div>
  )
}
