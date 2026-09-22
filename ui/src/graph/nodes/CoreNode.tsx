// Spec: Genesis Markdown/60-UI/Fleet View.md §Layout · 60-UI/Genesis Core.md
//
// The centre of the body map — "Genesis at the centre" (Fleet View §Layout).
//
// This is a *static* node: a bold rectangle, the orchestrator, nothing more. The
// animated presence (`components/GenesisCore.tsx`) lives on Home — "the animated
// presence at the centre of the idle screen" (Genesis Core §What it is for).
// Running a particle canvas inside React Flow made the graph churn and let the
// 300px node overlap the inner band; a plain node has neither problem.
//
// Genesis Core §What it may never be, prohibition 2: **never a control.** This
// node has no click handler, and adding one would be a spec violation.

import { memo } from 'react'
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react'
import type { CoreState } from '@/types/events'

export interface CoreNodeData extends Record<string, unknown> {
  state: CoreState
  inFlight: number
  label: string
}
export type CoreFlowNode = Node<CoreNodeData, 'core'>

export const CoreNode = memo(function CoreNode({ data }: NodeProps<CoreFlowNode>) {
  return (
    <div
      className="flex flex-col items-center justify-center select-none"
      style={{
        width: 200,
        height: 84,
        pointerEvents: 'none',
        background: 'var(--bg-raised)',
        border: '2px solid var(--core)',
        borderRadius: 'var(--r-md)',
        boxShadow: '0 0 0 5px color-mix(in oklab, var(--core) 13%, transparent)',
      }}
    >
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <div
        className="label"
        style={{ color: 'var(--core-hot)', letterSpacing: '0.34em', fontSize: 'var(--fs-sm)', fontWeight: 700 }}
      >
        {data.label}
      </div>
      <div className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', marginTop: 4 }}>
        {data.inFlight} task{data.inFlight === 1 ? '' : 's'} in flight
      </div>
    </div>
  )
})
