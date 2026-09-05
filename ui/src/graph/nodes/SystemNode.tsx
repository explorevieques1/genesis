// Spec: Genesis Markdown/50-Risk/Safety Invariants.md · Genesis Markdown/10-Architecture/MCP Gateway.md
//
// The nodes that are not ordinary LLM agents:
//
//   `spinal` — the Pre-Trade Risk Engine and the Kill Switch. Rendered in the
//              reflex palette with a hard border, because Safety Invariants #1
//              and #4 are structural facts an operator should be able to see.
//   `mcp`    — the tool surface, split afferent (sense) / efferent (hand) per
//              Biological Design §2. Reads and writes are different nerves and
//              are drawn as different things.
//   `memory` — one node per Memory Fabric layer.

import { memo } from 'react'
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react'
import type { HealthState, MemoryLayer } from '@/types/fleet'
import type { McpServerSpec } from '@/data/roster'

// -- spinal -----------------------------------------------------------------

export interface SpinalNodeData extends Record<string, unknown> {
  id: string
  label: string
  sub: string
  health: HealthState
  armed: boolean
  dimmed: boolean
  selected: boolean
}
export type SpinalFlowNode = Node<SpinalNodeData, 'spinal'>

export const SpinalNode = memo(function SpinalNode({ data }: NodeProps<SpinalFlowNode>) {
  const bad = data.health === 'down' || data.health === 'degraded'
  return (
    <div style={{ width: 210, opacity: data.dimmed ? 0.18 : 1, transition: 'opacity 200ms linear' }}>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <div
        className="px-2 py-[7px]"
        style={{
          background: 'var(--bg-inset)',
          // A double border: this is not styled like the agent nodes on purpose.
          border: `1px solid ${data.selected ? 'var(--core-hot)' : bad ? 'var(--verdict-blocked)' : 'var(--spinal)'}`,
          outline: '1px solid var(--spinal-dim)',
          outlineOffset: 2,
          borderRadius: 'var(--r-sm)',
        }}
      >
        <div className="flex items-center gap-[5px]">
          <span style={{ fontSize: 'var(--fs-micro)', color: 'var(--spinal)' }}>▮▮</span>
          <span style={{ fontSize: 'var(--fs-sm)', fontWeight: 600, color: 'var(--ink)' }}>
            {data.label}
          </span>
          {data.armed && (
            <span className="label ml-auto" style={{ color: 'var(--spinal)' }}>ARMED</span>
          )}
        </div>
        <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', marginTop: 2 }}>
          {data.sub}
        </div>
      </div>
    </div>
  )
})

// -- mcp --------------------------------------------------------------------

export interface McpNodeData extends Record<string, unknown> {
  server: McpServerSpec
  dimmed: boolean
}
export type McpFlowNode = Node<McpNodeData, 'mcp'>

export const McpNode = memo(function McpNode({ data }: NodeProps<McpFlowNode>) {
  const { server } = data
  const efferent = server.pathway === 'efferent'
  return (
    <div
      title={`${server.pathway} · ${server.status} — ${server.what}`}
      style={{ width: 190, opacity: data.dimmed ? 0.18 : server.status === 'build' ? 0.62 : 1 }}
    >
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <div
        className="flex items-center gap-[6px] px-[6px] py-[4px]"
        style={{
          background: 'var(--bg-deep)',
          border: `1px ${server.status === 'build' ? 'dashed' : 'solid'} var(--hairline-bright)`,
          // Efferent nodes are chamfered on the write side. Shape, not only hue.
          borderRadius: efferent ? '2px 2px 8px 2px' : '8px 2px 2px 2px',
        }}
      >
        <span
          style={{
            fontSize: 'var(--fs-micro)',
            color: efferent ? 'var(--phase-acting)' : 'var(--phase-perceiving)',
            flexShrink: 0,
          }}
        >
          {efferent ? '◀' : '▶'}
        </span>
        <span className="num truncate" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-dim)' }}>
          {server.name}
        </span>
      </div>
    </div>
  )
})

// -- memory -----------------------------------------------------------------

export interface MemoryNodeData extends Record<string, unknown> {
  layer: MemoryLayer
  reads: number
  writes: number
  hot: boolean
  dimmed: boolean
}
export type MemoryFlowNode = Node<MemoryNodeData, 'memory'>

export const MemoryNode = memo(function MemoryNode({ data }: NodeProps<MemoryFlowNode>) {
  return (
    <div
      title={data.layer.question}
      style={{ width: 168, opacity: data.dimmed ? 0.18 : 1 }}
    >
      <Handle type="target" position={Position.Top} />
      <Handle type="source" position={Position.Top} />
      <div
        className="px-2 py-[6px]"
        style={{
          background: 'var(--bg-panel)',
          border: `1px solid ${data.hot ? 'var(--edge-memory)' : 'var(--hairline)'}`,
          borderRadius: 'var(--r-sm)',
        }}
      >
        <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink-dim)' }}>{data.layer.name}</div>
        <div className="num flex gap-2" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)' }}>
          <span style={{ color: data.reads ? 'var(--phase-perceiving)' : undefined }}>r {data.reads}</span>
          <span style={{ color: data.writes ? 'var(--phase-acting)' : undefined }}>w {data.writes}</span>
        </div>
      </div>
    </div>
  )
})
