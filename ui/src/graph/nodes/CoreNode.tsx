// Spec: Genesis Markdown/60-UI/Genesis Core.md
//
// The centre of the body map. This is the *graph* rendering of the core; the
// animated presence itself is `components/GenesisCore.tsx`.
//
// Genesis Core §What it may never be, prohibition 2: **never a control.** A large
// glowing target in the centre of the screen must not be able to act. This node
// has no click handler, and adding one would be a spec violation, not a feature.

import { memo } from 'react'
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react'
import type { CoreState } from '@/types/events'
import { GenesisCore } from '@/components/GenesisCore'

export interface CoreNodeData extends Record<string, unknown> {
  state: CoreState
  inFlight: number
  label: string
}
export type CoreFlowNode = Node<CoreNodeData, 'core'>

export const CoreNode = memo(function CoreNode({ data }: NodeProps<CoreFlowNode>) {
  return (
    <div
      className="flex flex-col items-center justify-center"
      style={{ width: 340, height: 340, pointerEvents: 'none' }}
    >
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <GenesisCore state={data.state} size={300} />
      <div
        className="label"
        style={{ marginTop: -34, color: 'var(--core-hot)', letterSpacing: '0.34em', fontSize: 'var(--fs-sm)' }}
      >
        {data.label}
      </div>
      <div className="num" style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', marginTop: 3 }}>
        {data.inFlight} task{data.inFlight === 1 ? '' : 's'} in flight
      </div>
    </div>
  )
})
