// Spec: Genesis Markdown/60-UI/UI Stack.md §3 Layout · 60-UI/Widget Catalog.md
//
// Every panel the dock can place, in one map.
//
// The registry is the contract between `presets.ts` (which names panels) and
// the components (which render them). Keeping it in one file means a preset
// cannot reference a panel that does not exist without TypeScript saying so at
// build time, rather than Dockview rendering an empty rectangle at runtime.
//
// The Fleet views are reused rather than rewritten. `BodyMap`, `TraceView`,
// `MemoryFabric` and `ExecutionPath` were already built against the store and
// the event stream; wrapping them as panels is what lets the fleet surface
// participate in workspaces without a second implementation of the graph.

import type { ComponentType } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import { useGenesis } from '@/store/useGenesis'

import { AgentInspector } from '@/components/AgentInspector'
import { EventStream } from '@/components/EventStream'
import { BodyMap } from '@/views/BodyMap'
import { TraceView } from '@/views/TraceView'
import { MemoryFabric } from '@/views/MemoryFabric'
import { ExecutionPath } from '@/views/ExecutionPath'

import {
  ChartPanel, CoveragePanel, MarkupSpecsPanel, SymbolDetailPanel, WatchlistPanel,
} from './panels/charting'
import {
  BacktestEquityPanel, BacktestHistoryPanel, BacktestRunnerPanel,
  BacktestStatsPanel, BacktestTradesPanel,
} from './panels/backtest'
import {
  JournalEntriesPanel, JournalGraphPanel, JournalPatternsPanel,
} from './panels/journal'
import {
  CapabilityMapPanel, CompanyProfilePanel, ResearchCanvasPanel, ToolSurfacePanel,
} from './panels/system'
import {
  AgentSettingsPanel, ApprovalSettingsPanel, AudioSettingsPanel, DataSettingsPanel,
} from './panels/settings'
import { CadencePanel, WorkflowBuilderPanel } from './panels/automation'
import type { PanelId } from './presets'

/**
 * The fleet views take `now` — the shell's single clock — so elapsed labels and
 * staleness checks across the whole surface tick together rather than each
 * component owning a timer. Read here rather than threaded through Dockview,
 * which has no way to pass props to a panel.
 */
function useNow(): number {
  // The store already re-renders subscribers on ingest; for panels that only
  // need a coarse "as of", second resolution is plenty and costs one
  // subscription rather than a render loop.
  return useGenesis((s) => s.connection.lastEventAt) ?? Date.now()
}

function BodyMapPanel() {
  const now = useNow()
  return (
    // React Flow needs its provider inside the panel, because a panel can be
    // moved, floated, or closed independently -- there is no stable ancestor to
    // hoist it to.
    <ReactFlowProvider>
      <BodyMap now={now} />
    </ReactFlowProvider>
  )
}

function TracePanel() {
  return <TraceView now={useNow()} />
}

function MemoryFabricPanel() {
  return <MemoryFabric now={useNow()} />
}

function ExecutionPathPanel() {
  return <ExecutionPath now={useNow()} />
}

function AgentInspectorPanel() {
  return <AgentInspector now={useNow()} />
}

export const PANEL_COMPONENTS: Record<PanelId, ComponentType<Record<string, unknown>>> = {
  // charting
  'chart': ChartPanel,
  'watchlist': WatchlistPanel,
  'coverage': CoveragePanel,
  'symbol-detail': SymbolDetailPanel,
  'markup-specs': MarkupSpecsPanel,
  // backtest
  'backtest-runner': BacktestRunnerPanel,
  'backtest-equity': BacktestEquityPanel,
  'backtest-stats': BacktestStatsPanel,
  'backtest-trades': BacktestTradesPanel,
  'backtest-history': BacktestHistoryPanel,
  // research
  'company-profile': CompanyProfilePanel,
  'tool-surface': ToolSurfacePanel,
  'research-canvas': ResearchCanvasPanel,
  // journal
  'journal-graph': JournalGraphPanel,
  'journal-entries': JournalEntriesPanel,
  'journal-patterns': JournalPatternsPanel,
  // settings
  'settings-audio': AudioSettingsPanel,
  'settings-agents': AgentSettingsPanel,
  'settings-data': DataSettingsPanel,
  'settings-approval': ApprovalSettingsPanel,
  // automation
  'workflow-builder': WorkflowBuilderPanel,
  'cadence': CadencePanel,
  // fleet & shared
  'body-map': BodyMapPanel,
  'event-stream': EventStream as ComponentType<Record<string, unknown>>,
  'agent-inspector': AgentInspectorPanel,
  'memory-fabric': MemoryFabricPanel,
  'execution-path': ExecutionPathPanel,
  'trace': TracePanel,
  'capability-map': CapabilityMapPanel,
} as Record<PanelId, ComponentType<Record<string, unknown>>>
