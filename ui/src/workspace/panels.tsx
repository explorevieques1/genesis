// Spec: Genesis Markdown/60-UI/UI Stack.md §3 Layout · 60-UI/Widget Catalog.md
//
// Every panel the dock can place, in one map.
//
// The registry is the contract between `modules.ts` (which names and codes
// them) and the components (which render them). Keeping it in one file means a
// module cannot reference a panel that does not exist without TypeScript saying
// so at build time, rather than Dockview rendering an empty rectangle at
// runtime.
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
import { SystemMap } from '@/views/SystemMap'
import { Biology } from '@/views/Biology'
import { DnaPanel } from '@/workspace/panels/dna'
import { TradeIdeasPanel } from '@/workspace/panels/trade-ideas'
import { TraceView } from '@/views/TraceView'
import { MemoryFabric } from '@/views/MemoryFabric'
import { ExecutionPath } from '@/views/ExecutionPath'

import {
  ChartPanel, CoveragePanel, LiveDataPanel, MarkupSpecsPanel, SymbolDetailPanel, WatchlistPanel,
} from './panels/charting'
import { WatchlistManagerPanel } from './panels/watchlist'
import { CandleRangesPanel } from './panels/ranges'
import {
  BacktestEquityPanel, BacktestHistoryPanel, BacktestRunnerPanel,
  BacktestStatsPanel, BacktestTradesPanel,
} from './panels/backtest'
import {
  JournalDeskPanel, JournalEntriesPanel, JournalGraphPanel, JournalPatternsPanel,
  JournalMarksPanel,
} from './panels/journal'
import {
  CapabilityMapPanel, ResearchCanvasPanel, ToolSurfacePanel,
} from './panels/system'
import { CompanyProfilePanel } from './panels/company'
import {
  AgentSettingsPanel, ApprovalSettingsPanel, AudioSettingsPanel, DataSettingsPanel,
  ModelSettingsPanel,
} from './panels/settings'
import { CadencePanel } from './panels/automation'
import { FeedPanel } from './panels/feed'
import { WorkflowBuilderPanel } from './panels/workflow-builder'
import { ResearchDirectoryPanel, ResearchNotePanel } from './panels/research'
import { ScreenerPanel } from './panels/screener'
import { EconCalendarPanel } from './panels/econ'
import { NewsPanel } from './panels/news'
import { NotebookPanel } from './panels/notebook'
import { NotebookGraphPanel } from './panels/nodes'
import { StatusPanel } from './panels/status'
import { TaskManagerPanel } from './panels/tasks'
import { ToolPanel } from './panels/tool'
import { TradingViewPanel } from './panels/tradingview'
import { BrowserPanel } from './panels/browser'
import { HeatmapPanel } from './panels/heatmap'
import { MoversPanel } from './panels/movers'
import { PerformancePanel } from './panels/performance'
import { AskGenesisPanel } from './panels/ask'
import { HelpPanel } from './panels/help'
import { TradePanel } from './panels/trade'
import { AccountPanel } from './panels/account'
import { BrokerSetupPanel } from './panels/broker'
import type { PanelId } from './modules'

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

function SystemMapPanel() {
  return (
    <ReactFlowProvider>
      <SystemMap />
    </ReactFlowProvider>
  )
}

function BiologyPanel() {
  return (
    <ReactFlowProvider>
      <Biology />
    </ReactFlowProvider>
  )
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

// The `as` cast this map used to end with silenced exactly the error it exists
// to raise: `settings-models` was registered here, rendered fine, and appeared
// in no union and no module -- a panel nothing could open. Without the cast,
// TypeScript reports both directions, which is the point of the registry.
export const PANEL_COMPONENTS: Record<PanelId, ComponentType<Record<string, unknown>>> = {
  // charting
  'chart': ChartPanel,
  'watchlist': WatchlistPanel,
  'live-data': LiveDataPanel,
  'watchlist-manager': WatchlistManagerPanel,
  'candle-ranges': CandleRangesPanel,
  'coverage': CoveragePanel,
  'symbol-detail': SymbolDetailPanel,
  'markup-specs': MarkupSpecsPanel,
  'tradingview': TradingViewPanel,
  'browser': BrowserPanel,
  'heatmap': HeatmapPanel,
  'movers': MoversPanel,
  'performance': PerformancePanel,
  // trade
  'broker-account': AccountPanel,
  'broker-setup': BrokerSetupPanel,
  'order-ticket': TradePanel,
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
  'research-directory': ResearchDirectoryPanel,
  'research-note': ResearchNotePanel,
  'screener': ScreenerPanel,
  'news': NewsPanel as ComponentType<Record<string, unknown>>,
  'econ-calendar': EconCalendarPanel,
  // journal
  'journal-graph': JournalGraphPanel,
  'journal-entries': JournalEntriesPanel,
  'journal-patterns': JournalPatternsPanel,
  'journal-desk': JournalDeskPanel,
  'journal-marks': JournalMarksPanel,
  'notebook': NotebookPanel,
  'notebook-graph': NotebookGraphPanel,
  // settings
  'settings-audio': AudioSettingsPanel,
  'settings-agents': AgentSettingsPanel,
  'settings-data': DataSettingsPanel,
  'settings-approval': ApprovalSettingsPanel,
  'settings-models': ModelSettingsPanel,
  // automation
  'workflow-builder': WorkflowBuilderPanel as ComponentType<Record<string, unknown>>,
  'cadence': CadencePanel,
  'feed': FeedPanel,
  // fleet & shared
  'body-map': BodyMapPanel,
  'system-map': SystemMapPanel,
  'biology': BiologyPanel,
  'dna': DnaPanel,
  'trade-ideas': TradeIdeasPanel,
  'event-stream': EventStream as ComponentType<Record<string, unknown>>,
  'agent-inspector': AgentInspectorPanel,
  'memory-fabric': MemoryFabricPanel,
  'execution-path': ExecutionPathPanel,
  'trace': TracePanel,
  'capability-map': CapabilityMapPanel,
  'status': StatusPanel,
  'task-manager': TaskManagerPanel,
  'ask-genesis': AskGenesisPanel,
  'help': HelpPanel,
  // Every MCP tool, through one component. It reads `params.toolId` and builds
  // its form from that tool's own JSON Schema, so the 132nd server needs no
  // entry here.
  'tool': ToolPanel as ComponentType<Record<string, unknown>>,
}
