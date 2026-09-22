// Spec: Genesis Markdown/10-Architecture/Biological Design.md · 30-MCP/MCP Gateway.md
//
// The panels that describe the system to itself: capabilities, the tool
// surface, companies, and the research canvas that does not exist yet.
//
// The capability map is the most important panel in the application, and it is
// deliberately the least exciting. It renders `/v1/capabilities` — every probe
// the daemon ran, what it found, and the vault note for anything missing. It is
// the surface's proprioception made visible: instead of the operator inferring
// what works from which pages look populated, the system states it.

import { useMemo, useState } from 'react'
import { api, type CapabilityRecord, type McpToolRow } from '@/api/client'
import { useCapabilities, useCapability } from '@/api/capabilities'
import { useRead } from '@/api/useRead'
import { Absent, Loading, Unbuilt } from '@/components/States'
import { Chip, Num, PanelBody, Section, Table } from '@/components/Primitives'
import { stagger } from '@/lib/motion'
import { openPanel } from '@/workspace/dock'
import { toolPanelId } from './tool'
import { ResearchCanvas } from '@/views/ResearchCanvas'

// ---------------------------------------------------------------------------
// Capability map
// ---------------------------------------------------------------------------

export function CapabilityMapPanel() {
  const { state, reload } = useCapabilities()

  if (state.status === 'loading') return <Loading rows={6} label="probing" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  const { capabilities, families, built, total } = state.data
  const groups = Object.entries(families)

  return (
    <PanelBody>
      <div className="flex items-baseline gap-3">
        <span style={{ fontSize: 'var(--fs-xl)' }}>
          <Num value={built} digits={0} />
          <span style={{ color: 'var(--ink-ghost)' }}> / {total}</span>
        </span>
        <span className="label">organs present</span>
        <span style={{ flex: 1 }} />
        <button className="btn-ghost" onClick={reload}>re-probe</button>
      </div>

      {/* A bar, so the ratio is readable without arithmetic. */}
      <div
        style={{
          height: 3, background: 'var(--bg-inset)', borderRadius: 2,
          overflow: 'hidden', flexShrink: 0,
        }}
      >
        <div
          style={{
            height: '100%', width: `${(built / total) * 100}%`,
            background: 'var(--core)',
            transition: 'width 400ms cubic-bezier(0.2, 0.8, 0.2, 1)',
          }}
        />
      </div>

      {groups.map(([family, ids]) => (
        <Section key={family} title={family} dense>
          <div className="flex flex-col" style={{ gap: 2 }}>
            {ids.map((id, index) => (
              <CapabilityRow key={id} record={capabilities[id]} index={index} />
            ))}
          </div>
        </Section>
      ))}

      <div
        className="label"
        style={{ color: 'var(--ink-ghost)', textTransform: 'none',
          letterSpacing: 0, lineHeight: 1.5, marginTop: 4 }}
      >
        Each row is a real check — an import that succeeded or a file that
        exists — run just now, not a list of what someone believed was
        finished. Pages read this to decide what they may render.
      </div>
    </PanelBody>
  )
}

function CapabilityRow({ record, index }: { record: CapabilityRecord; index: number }) {
  const [open, setOpen] = useState(false)
  if (!record) return null

  return (
    <div className="lift" style={{ ['--i' as string]: stagger(index, 16) }}>
      <button
        className="row-hit flex items-center gap-2 w-full"
        style={{ padding: '3px 6px', textAlign: 'left' }}
        onClick={() => setOpen((v) => !v)}
      >
        {/* Shape, not only colour: a filled square is present, a hollow one is
            absent. Survives greyscale, as Fleet View requires of every state. */}
        <span
          aria-hidden
          style={{
            width: 7, height: 7, flexShrink: 0,
            borderRadius: 1,
            background: record.built ? 'var(--verdict-pass)' : 'transparent',
            border: `1px solid ${record.built ? 'var(--verdict-pass)' : 'var(--ink-ghost)'}`,
          }}
        />
        <span
          style={{
            fontSize: 'var(--fs-tiny)',
            color: record.built ? 'var(--ink-dim)' : 'var(--ink-faint)',
          }}
        >
          {record.label}
        </span>
        <span style={{ flex: 1 }} />
        {!record.built && <Chip tone="warn">absent</Chip>}
      </button>
      {open && (
        <div
          className="flex flex-col gap-1"
          style={{ padding: '4px 6px 6px 21px' }}
        >
          <div className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', lineHeight: 1.5 }}>
            {record.detail}
          </div>
          <div className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-ghost)' }}>
            spec: {record.spec}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tool surface
// ---------------------------------------------------------------------------

export function ToolSurfacePanel() {
  const [query, setQuery] = useState('')
  const tools = useRead(() => api.mcpTools(), [])
  const servers = useRead(() => api.mcpServers(), [])

  const rows = useMemo(() => {
    if (tools.state.status !== 'ready') return []
    const needle = query.trim().toLowerCase()
    return tools.state.data.tools.filter((tool) =>
      !needle ||
      tool.id.toLowerCase().includes(needle) ||
      tool.capability.toLowerCase().includes(needle) ||
      tool.keywords.some((k) => k.toLowerCase().includes(needle)),
    )
  }, [tools.state, query])

  if (tools.state.status === 'loading') return <Loading rows={6} label="tool catalogue" />
  if (tools.state.status !== 'ready') {
    return <Absent reason={tools.state.reason} onRetry={tools.reload} />
  }

  const serverCount = servers.state.status === 'ready'
    ? servers.state.data.servers.filter((s) => s.enabled).length
    : null

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 hairline-b" style={{ padding: '4px 8px', flexShrink: 0 }}>
        <input
          className="field"
          placeholder="filter tools"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ flex: 1, minWidth: 0 }}
        />
        <span className="label" style={{ color: 'var(--ink-ghost)' }}>
          {rows.length} of {tools.state.data.count}
          {serverCount !== null && ` · ${serverCount} servers`}
        </span>
      </div>

      <Table
        rows={rows}
        keyOf={(row) => row.id}
        // A catalogue row is now a way in. Clicking one opens that tool with
        // its own arguments, which is what makes this a control surface rather
        // than a printed menu.
        onSelect={(row) =>
          openPanel('tool', {
            // A stable id: the same tool always lands in the same panel rather
            // than stacking a fresh empty form beside the one you filled in.
            id: toolPanelId(row.id),
            title: row.name,
            params: { toolId: row.id },
          })
        }
        columns={[
          {
            key: 'tool', header: 'tool',
            render: (row: McpToolRow) => (
              <span style={{ color: row.enabled ? 'var(--ink)' : 'var(--ink-ghost)' }}>
                <span className="label" style={{ letterSpacing: 0, textTransform: 'none' }}>
                  {row.server}.
                </span>
                {row.name}
              </span>
            ),
          },
          {
            key: 'capability', header: 'capability',
            render: (row: McpToolRow) => (
              <span className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)' }}>
                {row.capability}
              </span>
            ),
          },
          {
            key: 'writes', header: 'writes', align: 'right', width: 96,
            render: (row: McpToolRow) =>
              // Three states, not two. `null` means the catalogue did not
              // declare it and the server's own hint is believed — worth
              // showing, because an undeclared tool is one nobody has vetted.
              row.mutating === null ? (
                <Chip tone="neutral" title="not declared; the server's own hint is believed">
                  undeclared
                </Chip>
              ) : row.mutating ? (
                <Chip tone="warn">mutates</Chip>
              ) : (
                <Chip tone="good">read-only</Chip>
              ),
          },
          {
            key: 'tier', header: 'tier', align: 'right', width: 44,
            render: (row: McpToolRow) => <Num value={row.tier} digits={0} />,
          },
        ]}
      />

      <div
        className="label hairline-t"
        style={{ padding: '4px 8px', color: 'var(--ink-ghost)', flexShrink: 0,
          textTransform: 'none', letterSpacing: 0, lineHeight: 1.5 }}
      >
        The declared catalogue, from config. Sessions are not opened by a page
        load — live connection state arrives on the event stream.
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Research canvas — not built
// ---------------------------------------------------------------------------

/**
 * The node canvas has no backend.
 *
 * It could be built entirely in the browser with `localStorage`, and that is
 * exactly why it is not. A research canvas whose nodes only exist in one
 * viewer's browser is not something Genesis can read, cite, or write to — and
 * "Genesis has access to it" was the whole requirement. A canvas the agent
 * cannot see is a drawing tool, not a research surface.
 *
 * So it stays reported-absent until `genesis.research.canvas` exists, and the
 * empty state says which note specifies it.
 */
export function ResearchCanvasPanel() {
  const capability = useCapability('research.canvas')
  if (!capability) return <Loading rows={3} />
  if (!capability.built) return <Unbuilt capability={capability} />
  return <ResearchCanvas />
}
