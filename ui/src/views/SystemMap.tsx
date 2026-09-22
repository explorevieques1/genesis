// Spec: Genesis Markdown/60-UI/System Map.md
//
// `MAP` — everything ⌘K can reach, as one graph, and every node a link.
//
// The nodes are the palette's own catalogue (`shell/catalogue.ts`), so the map
// cannot show a thing the palette cannot open, and clicking a node runs the
// same `run` choosing that row in ⌘K would. Parity by construction: there is
// no map-only action to drift.
//
// Five blocks, read left to right as "how you get in" → "what does the work":
//   doors    pages, commands, config — what you pick or type
//   series   every stored series (each opens the chart)
//   modules  grouped under their home page
//   agents   grouped by family
//   tools    grouped by MCP server
// A block taller than ROWS wraps into another column, so 131 tools read as a
// wall you can scan rather than a 5 000 px strip. Agent families and tool
// servers are ordered by the rows of what links to them, which keeps edges
// short without a solver. ELK was tried: a layered layout of 264 nodes is four
// columns and a very tall canvas, unreadable at any zoom that fits.
//
// Positions are computed once per topology, like the body map — hover and
// search restyle, they never move a node.

import { memo, useCallback, useEffect, useMemo, useState } from 'react'
import {
  Background, BackgroundVariant, Controls, Handle, Position, ReactFlow, useReactFlow,
  type Edge, type Node, type NodeMouseHandler, type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { PAGES } from '@/shell/pages'
import { FAMILY_ORDER } from '@/data/roster'
import { KIND_COLOUR, useCatalogue, openPalette, type Item, type Kind, type Rel } from '@/shell/catalogue'
import type { PageId } from '@/shell/pages'
import { useWorkspace } from '@/workspace/context'

const W = 214
const H = 30
const ROW = 36
const COL = W + 22
const BLOCK_GAP = 190
/** Rows per column before a block wraps. */
const ROWS = 34

/** Block order, left to right. Edges are drawn from the lower block to the higher. */
const COLUMN: Record<Kind, number> = { page: 0, command: 0, config: 0, series: 1, module: 2, agent: 3, tool: 4 }

const REL_DASH: Record<Rel, string | undefined> = {
  home: undefined, opens: undefined, about: '6 3', seeded: '6 5', shows: '2 3', uses: undefined, reads: '1 4',
}
const REL_WHAT: Record<Rel, string> = {
  home: 'page → module whose home it is',
  seeded: 'page → module seeded onto it from elsewhere',
  opens: 'series, tier, vault or workflow → module it opens',
  about: 'command → module it answers into',
  shows: "module → agent whose work it shows",
  uses: 'agent → tool it declares',
  reads: "agent → agent whose memory it reads",
}

type ItemData = { item: Item; state: 'hot' | 'dim' | 'plain' }
type TitleData = { title: string; count: number; big: boolean }
type MapNode = Node<ItemData, 'item'> | Node<TitleData, 'title'>

const ItemNode = memo(function ItemNode({ data }: NodeProps<Node<ItemData, 'item'>>) {
  const { item, state } = data
  const colour = KIND_COLOUR[item.kind]
  return (
    <div
      title={`${item.kind} · ${item.hint}\nclick to open`}
      style={{
        width: W, height: H, display: 'flex', alignItems: 'center', gap: 6, padding: '0 8px 0 0',
        background: 'var(--bg-panel)', borderRadius: 'var(--r-sm)', cursor: 'pointer', overflow: 'hidden',
        border: `1px solid ${state === 'hot' ? colour : 'var(--hairline)'}`,
        opacity: state === 'dim' ? 0.2 : 1,
        boxShadow: state === 'hot' ? `0 0 0 1px ${colour}` : undefined,
        transition: 'opacity 120ms, border-color 120ms',
      }}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} style={{ opacity: 0 }} />
      <span style={{ width: 3, alignSelf: 'stretch', background: colour, flexShrink: 0 }} />
      {item.code && (
        <span className="num" style={{
          fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', flexShrink: 0,
          border: '1px solid var(--hairline-bright)', borderRadius: 3, padding: '0 4px',
        }}>
          {item.code}
        </span>
      )}
      <span style={{
        fontSize: 'var(--fs-tiny)', color: 'var(--ink)',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {item.label}
      </span>
      <Handle type="source" position={Position.Right} isConnectable={false} style={{ opacity: 0 }} />
    </div>
  )
})

const TitleNode = memo(function TitleNode({ data }: NodeProps<Node<TitleData, 'title'>>) {
  return (
    <div className="label" style={{
      width: W, color: data.big ? 'var(--ink)' : 'var(--ink-faint)', paddingTop: data.big ? 0 : 12,
      fontSize: data.big ? 'var(--fs-tiny)' : undefined,
    }}>
      {data.title} <span className="num" style={{ color: 'var(--ink-ghost)' }}>{data.count}</span>
    </div>
  )
})

const nodeTypes = { item: ItemNode, title: TitleNode }

export function SystemMap() {
  const { select } = useWorkspace()
  const { fitView } = useReactFlow()
  const [hover, setHover] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const onPage = useCallback((p: PageId) => { window.location.hash = p }, [])
  const onSymbol = useCallback((symbolId: string, timeframe: string) => select({ symbolId, timeframe }), [select])
  const noop = useCallback(() => {}, [])

  // Always loading: the map is open because someone asked for it. `page` only
  // ranks palette rows and picks a fallback when there is no dock — and a
  // panel is, by definition, in a dock.
  const { items: all, settled, missing } = useCatalogue(true, {
    page: 'fleet', onPage, onSymbol, onClose: noop, onCommand: openPalette,
  })

  // Settings modules appear twice in the palette (Modules and Config). One node.
  const items = useMemo(() => all.filter((i) => !i.alias), [all])
  const byId = useMemo(() => new Map(items.map((i) => [i.id, i])), [items])

  const links = useMemo(() => {
    const seen = new Set<string>()
    const out: { id: string; source: string; target: string; rel: Rel }[] = []
    for (const i of items) {
      for (const l of i.links) {
        const to = byId.get(l.to)
        if (!to) continue // an id that never loaded — an agent not in this fleet
        // Draw left to right, whichever end declared it.
        const [source, target] = COLUMN[i.kind] <= COLUMN[to.kind] ? [i.id, to.id] : [to.id, i.id]
        const id = `${source}>${target}`
        if (!seen.has(id)) { seen.add(id); out.push({ id, source, target, rel: l.rel }) }
      }
    }
    return out
  }, [items, byId])

  const neighbours = useMemo(() => {
    const m = new Map<string, Set<string>>()
    const add = (a: string, b: string) => (m.get(a) ?? m.set(a, new Set()).get(a)!).add(b)
    for (const l of links) { add(l.source, l.target); add(l.target, l.source) }
    return m
  }, [links])

  const layout = useMemo(() => (settled ? place(items, neighbours) : null), [settled, items, neighbours])

  const needle = query.trim().toLowerCase()
  const matches = useMemo(() => {
    if (!needle) return null
    return new Set(items.filter((i) => i.tokens.some((t) => t.includes(needle)) || i.hint.toLowerCase().includes(needle)).map((i) => i.id))
  }, [items, needle])

  const nodes = useMemo<MapNode[]>(() => {
    if (!layout) return []
    const hot = hover ? new Set([hover, ...(neighbours.get(hover) ?? [])]) : matches
    const out: MapNode[] = items.map((item) => ({
      id: item.id, type: 'item', position: layout.pos[item.id],
      data: { item, state: !hot ? 'plain' : hot.has(item.id) ? 'hot' : 'dim' },
    }))
    for (const t of layout.titles) {
      out.push({ id: t.id, type: 'title', position: { x: t.x, y: t.y }, data: t, selectable: false })
    }
    return out
  }, [items, layout, hover, matches, neighbours])

  const edges = useMemo<Edge[]>(() => links.map((l) => {
    const touching = hover ? l.source === hover || l.target === hover
      : matches ? matches.has(l.source) && matches.has(l.target) : null
    return {
      id: l.id, source: l.source, target: l.target, selectable: false,
      style: {
        stroke: KIND_COLOUR[byId.get(l.source)!.kind],
        strokeDasharray: REL_DASH[l.rel],
        strokeWidth: touching ? 1.6 : 1,
        opacity: touching === null ? 0.18 : touching ? 0.95 : 0.03,
      },
    }
  }), [links, byId, hover, matches])

  // Frame the doors, series and modules; agents and tools are one pan to the right.
  useEffect(() => {
    if (!layout) return
    const t = setTimeout(() => fitView({
      nodes: items.filter((i) => COLUMN[i.kind] <= 2).map((i) => ({ id: i.id })),
      // Left inset clears the legend panel, which floats over the canvas.
      padding: { left: '280px', top: '40px', right: '20px', bottom: '20px' }, maxZoom: 0.9, duration: 300,
    }), 60)
    return () => clearTimeout(t)
  }, [layout]) // eslint-disable-line react-hooks/exhaustive-deps -- re-frame on a new layout only

  const onNodeClick = useCallback<NodeMouseHandler<MapNode>>((_, node) => {
    if (node.type === 'item') node.data.item.run()
  }, [])

  const counts = useMemo(() => {
    const c: Partial<Record<Kind, number>> = {}
    for (const i of items) c[i.kind] = (c[i.kind] ?? 0) + 1
    return c
  }, [items])

  return (
    <div className="relative h-full w-full">
      <ReactFlow<MapNode>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={onNodeClick}
        onNodeMouseEnter={(_, n) => n.type === 'item' && setHover(n.id)}
        onNodeMouseLeave={() => setHover(null)}
        nodesDraggable={false}
        nodesConnectable={false}
        onlyRenderVisibleElements
        proOptions={{ hideAttribution: true }}
        minZoom={0.05}
        maxZoom={2}
      >
        <Background variant={BackgroundVariant.Dots} gap={26} size={1} color="var(--hairline)" />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>

      <div className="absolute panel" style={{ left: 10, top: 10, padding: 8, width: 250, backdropFilter: 'blur(6px)' }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="find a module, tool, agent…"
          style={{
            width: '100%', background: 'var(--bg-inset)', border: '1px solid var(--hairline)',
            borderRadius: 'var(--r-sm)', padding: '3px 7px', fontSize: 'var(--fs-tiny)', outline: 'none',
          }}
        />
        <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', margin: '6px 0' }}>
          {settled ? `${items.length} things you can reach · ${links.length} links` : 'reading the catalogue…'}
          <br />click a node to open it · hover to trace its links
        </div>

        <div className="label" style={{ margin: '6px 0 3px' }}>nodes</div>
        <div className="flex flex-wrap" style={{ gap: '2px 10px' }}>
          {(Object.keys(KIND_COLOUR) as Kind[]).map((k) => (
            <span key={k} className="flex items-center gap-[5px]" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-dim)' }}>
              <span style={{ width: 6, height: 6, borderRadius: 1, background: KIND_COLOUR[k] }} />
              {k} <span className="num" style={{ color: 'var(--ink-ghost)' }}>{counts[k] ?? 0}</span>
            </span>
          ))}
        </div>

        <div className="label" style={{ margin: '8px 0 3px' }}>links</div>
        {(Object.keys(REL_WHAT) as Rel[]).map((r) => (
          <div key={r} className="flex items-center gap-[6px]" style={{ fontSize: 'var(--fs-micro)' }} title={REL_WHAT[r]}>
            <svg width="22" height="8" style={{ flexShrink: 0 }}>
              <line x1="0" y1="4" x2="22" y2="4" stroke="var(--ink-dim)" strokeDasharray={REL_DASH[r]} />
            </svg>
            <span style={{ color: 'var(--ink-dim)' }}>{r}</span>
            <span style={{ color: 'var(--ink-ghost)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{REL_WHAT[r]}</span>
          </div>
        ))}

        {missing.length > 0 && (
          <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--state-warn, var(--core-flare))', marginTop: 6 }}>
            not on the map — the daemon did not answer for: {missing.join(', ')}
          </div>
        )}
      </div>
    </div>
  )
}

interface Title extends TitleData { id: string; x: number; y: number }

/**
 * Deterministic placement. Each block is a list of rows — a group title, then
 * its items — poured into columns of ROWS. Later blocks sort their groups and
 * items by the mean row of what links to them in earlier blocks (a one-pass
 * barycentre), so a server sits across from the agents that call it.
 */
function place(items: Item[], neighbours: Map<string, Set<string>>) {
  const pos: Record<string, { x: number; y: number }> = {}
  const titles: Title[] = []
  let x = 0

  const bary = (id: string) => {
    const ys = [...(neighbours.get(id) ?? [])].map((n) => pos[n]?.y).filter((y): y is number => y !== undefined)
    return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : Infinity
  }
  const byBary = (a: Item, b: Item) => bary(a.id) - bary(b.id) || a.label.localeCompare(b.label)

  const block = (title: string, groups: { title: string; items: Item[] }[]) => {
    const count = groups.reduce((n, g) => n + g.items.length, 0)
    if (!count) return
    titles.push({ id: `title:${title}`, title, count, big: true, x, y: -ROW * 1.4 })
    let col = 0
    let row = 0
    for (const g of groups) {
      if (!g.items.length) continue
      // A group starts a fresh column rather than leaving its title stranded at
      // the foot of one — unless it is longer than a column anyway.
      if (row > 0 && row + 1 + g.items.length > ROWS) { col++; row = 0 }
      const at = () => ({ x: x + col * COL, y: row * ROW })
      titles.push({ id: `title:${title}:${g.title}`, title: g.title, count: g.items.length, big: false, ...at() })
      row++
      for (const item of g.items) {
        if (row >= ROWS) { col++; row = 0 }
        pos[item.id] = at()
        row++
      }
    }
    x += (col + 1) * COL + BLOCK_GAP
  }
  const of = (kind: Kind) => items.filter((i) => i.kind === kind)
  const grouped = (list: Item[], order: string[]) => {
    const keys = [...new Set(list.map((i) => i.group ?? ''))]
    keys.sort((a, b) => {
      const ia = order.indexOf(a), ib = order.indexOf(b)
      if (ia !== -1 || ib !== -1) return (ia === -1 ? 1e9 : ia) - (ib === -1 ? 1e9 : ib)
      const mean = (k: string) => {
        const ys = list.filter((i) => i.group === k).map((i) => bary(i.id)).filter(Number.isFinite)
        return ys.length ? ys.reduce((p, q) => p + q, 0) / ys.length : Infinity
      }
      return mean(a) - mean(b) || a.localeCompare(b)
    })
    return keys.map((k) => ({ title: k, items: list.filter((i) => (i.group ?? '') === k).sort(byBary) }))
  }

  block('Doors', [
    { title: 'pages', items: of('page') },
    { title: 'commands', items: of('command') },
    { title: 'config', items: of('config') },
  ])
  block('Series', [{ title: 'bar store', items: of('series') }])
  // Modules keep nav order, so the pages column reads straight across.
  block('Modules', PAGES.map((p) => ({ title: p.label, items: of('module').filter((m) => m.home === p.id) })))
  block('Agents', grouped(of('agent'), FAMILY_ORDER as string[]))
  block('Tools', grouped(of('tool'), []))
  return { pos, titles }
}
