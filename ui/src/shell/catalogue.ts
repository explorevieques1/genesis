// Spec: Genesis Markdown/60-UI/Terminal.md · 60-UI/System Map.md
//
// Everything a person can reach — pages, modules, series, tools, agents,
// commands, config — built once, for two surfaces: the ⌘K palette lists it,
// `MAP` draws it.
//
// One builder, not two, for the reason the palette already gives about its
// inline and overlay placements: two copies drift, and then the map shows a
// thing the palette cannot open. Every item's `run` is the palette's own door,
// so clicking a node on the map *is* choosing that row in ⌘K.
//
// `links` are the relationships, and every one is read from something real:
//   home / seeded  — `MODULES[].home` and `SEEDS`
//   uses           — an agent's declared `tools` (a tool id or a capability)
//   reads          — an agent's `memory.read` naming another agent
//   opens          — a series opens `CH`, a tier `MT`, a vault `NOT`, an agent
//                    that is a workflow `WB`
//   about          — COMMAND_ABOUT below, the one hand-kept table
//   shows          — MODULE_AGENTS below, the other

import { useMemo } from 'react'
import { api } from '@/api/client'
import { useRead } from '@/api/useRead'
import { PAGES, type PageId } from './pages'
import { openPanel } from '@/workspace/dock'
import { toolPanelId } from '@/workspace/panels/tool'
import { MODULES, SEEDS, type Module } from '@/workspace/modules'
import { useGenesis } from '@/store/useGenesis'

export type Kind = 'page' | 'module' | 'series' | 'tool' | 'agent' | 'command' | 'config'
export type Rel = 'home' | 'seeded' | 'opens' | 'about' | 'shows' | 'uses' | 'reads'

export const KIND_COLOUR: Record<Kind, string> = {
  page: 'var(--core-hot)',
  module: 'var(--core)',
  series: 'var(--family-charting)',
  tool: 'var(--family-strategy)',
  agent: 'var(--family-journal)',
  command: 'var(--core-flare)',
  config: 'var(--ink-dim)',
}

export interface Item {
  kind: Kind
  id: string
  label: string
  hint: string
  /** The module's short code, shown as the thing you actually typed. */
  code?: string
  /** Everything a query can match against, lowercased. */
  tokens: string[]
  /** Modules whose home is the current category sort first. */
  local?: boolean
  /** A module's home page — its section under the Modules filter. */
  home?: PageId
  /** What `MAP` clusters it under: an agent's family, a tool's server, a module's home. */
  group?: string
  /** A second palette row for a thing that already has one (settings modules under Config). */
  alias?: boolean
  /** Item ids this one relates to. Ids that never loaded are dropped by the reader. */
  links: { to: string; rel: Rel }[]
  run: () => void
}

/**
 * What each deterministic command is about. The wire says only `name` and
 * `help`; the module each one answers into is here. Mirrors `App.onReply` for
 * the three that open a panel, and the command's own subject for the rest.
 * ponytail: hand-kept — move to `GET /v1/commands` as an `opens` field if it drifts.
 */
const COMMAND_ABOUT: Record<string, Module['id']> = {
  chart: 'chart',
  company: 'company-profile',
  open_tradingview: 'tradingview',
  status: 'status',
  screen: 'screener',
  canvas: 'research-canvas',
  notebook: 'notebook',
  note_that: 'notebook',
  search_notes: 'notebook',
}

/**
 * Which agents' output a module shows. The agent half of `MODULE_LINKS` in
 * `scripts/build_connection_graph.py`, by agent id; organs that are not fleet
 * agents (the risk engine) are left out.
 * ponytail: second copy of that table — fold into `modules.ts` if they disagree.
 */
const MODULE_AGENTS: Partial<Record<Module['id'], string[]>> = {
  'chart': ['chart-markup', 'level-watcher'],
  'markup-specs': ['chart-markup', 'pattern-recognition', 'multi-timeframe'],
  'performance': ['data-viz'],
  'backtest-runner': ['backtest-runner'],
  'backtest-equity': ['backtest-runner'],
  'backtest-stats': ['backtest-runner', 'risk-metrics'],
  'backtest-trades': ['backtest-runner'],
  'backtest-history': ['backtest-runner'],
  'research-canvas': ['topic-researcher', 'idea-synthesizer'],
  'research-directory': ['topic-researcher', 'market-analyst', 'idea-synthesizer'],
  'research-note': ['topic-researcher'],
  'company-profile': ['fundamental'],
  'screener': ['screener'],
  'news': ['news-collector', 'news-catalyst'],
  'journal-graph': ['trade-journal', 'insight-miner'],
  'journal-entries': ['trade-journal'],
  'journal-patterns': ['insight-miner'],
  'journal-desk': ['digest', 'watchdog', 'drift', 'insight-miner', 'performance-analyst', 'trade-journal'],
  'cadence': ['watchdog', 'digest'],
  'execution-path': ['order-manager'],
  'status': ['watchdog'],
}

export interface Handlers {
  /** The category the operator is standing in: ranks modules, and Home has no dock. */
  page: PageId
  onPage: (page: PageId) => void
  onSymbol: (symbolId: string, timeframe: string) => void
  onClose: () => void
  /** A command's help line is an example, not a literal — put it in a field to edit. */
  onCommand: (text: string) => void
}

/** Event the shell listens for to open ⌘K with a line already typed. */
export const PALETTE_EVENT = 'genesis:palette'
export const openPalette = (text: string) =>
  window.dispatchEvent(new CustomEvent<string>(PALETTE_EVENT, { detail: text }))

/**
 * @param load  read the live halves (series, tools, agents…). A closed palette passes false.
 * @returns     `settled` once every read has answered; `missing` names those that failed.
 */
export function useCatalogue(load: boolean, h: Handlers) {
  const select = useGenesis((s) => s.select)
  const symbols = useRead(() => api.symbols(), [load])
  const tools = useRead(() => api.mcpTools(), [load])
  const agents = useRead(() => api.agents(), [load])
  const commands = useRead(() => api.commandList(), [load])
  const models = useRead(() => api.models(), [load])
  const vaults = useRead(() => api.vaults(), [load])
  const { page, onPage, onSymbol, onClose, onCommand } = h

  const items = useMemo<Item[]>(() => {
    const out: Item[] = PAGES.map((def) => ({
      kind: 'page' as const,
      id: `page:${def.id}`,
      label: def.label,
      hint: def.hint,
      tokens: [def.label.toLowerCase(), def.hint.toLowerCase()],
      links: [
        ...MODULES.filter((m) => m.home === def.id).map((m) => ({ to: `module:${m.id}`, rel: 'home' as const })),
        ...SEEDS[def.id]
          .filter((s) => MODULES.find((m) => m.id === s.id)?.home !== def.id)
          .map((s) => ({ to: `module:${s.id}`, rel: 'seeded' as const })),
      ],
      run: () => { onPage(def.id); onClose() },
    }))

    // Every module, spawnable into whatever workspace you are standing in.
    //
    // `home` ranks, it does not confine. A chart in Settings is unusual, not
    // forbidden — and forbidding it is what turned nine categories into nine
    // cages, where the journal graph could not sit beside a chart no matter how
    // much you wanted it to. Modules belonging to the current category sort
    // first; everything else is one keystroke further down the same list.
    for (const module of MODULES) {
      out.push({
        kind: 'module',
        id: `module:${module.id}`,
        label: module.title,
        code: module.code,
        hint: module.hint,
        local: module.home === page,
        home: module.home,
        group: module.home,
        tokens: [
          module.code.toLowerCase(),
          module.title.toLowerCase(),
          ...(module.aliases ?? []).map((a) => a.toLowerCase()),
        ],
        links: (MODULE_AGENTS[module.id] ?? []).map((a) => ({ to: `agent:${a}`, rel: 'shows' as const })),
        // No id: every open is a new instance. Four charts in one workspace is
        // the point, not an accident to guard against.
        //
        // `openPanel` returns false when there is no dock — which is Home. In
        // that case, go to the module's home category; the dock there replays
        // the open (see `dock.ts`).
        run: () => {
          if (!openPanel(module.id, { title: module.title }) && page === 'home') {
            onPage(module.home === 'home' ? 'overview' : module.home)
          }
          onClose()
        },
      })
    }

    if (symbols.state.status === 'ready') {
      for (const row of symbols.state.data.symbols) {
        out.push({
          kind: 'series',
          id: `series:${row.symbol_id}:${row.timeframe}`,
          label: `${row.symbol} ${row.timeframe}`,
          hint: `${row.bars} bars · ${row.coverage[0]?.source ?? 'unknown source'}`,
          tokens: [`${row.symbol} ${row.timeframe}`.toLowerCase(), row.symbol.toLowerCase()],
          links: [{ to: 'module:chart', rel: 'opens' }],
          run: () => { onSymbol(row.symbol_id, row.timeframe); onPage('charting'); onClose() },
        })
      }
    }
    if (agents.state.status === 'ready') {
      const toolRows = tools.state.status === 'ready' ? tools.state.data.tools : []
      for (const agent of agents.state.data.agents) {
        // A declared tool is either a tool id or a capability several servers
        // provide — the gateway routes by capability, so each provider is a real edge.
        const uses = toolRows
          .filter((t) => agent.tools.includes(t.id) || agent.tools.includes(t.capability))
          .map((t) => ({ to: `tool:${t.id}`, rel: 'uses' as const }))
        const reads = (agent.memory.read ?? [])
          .filter((ns) => ns !== agent.id)
          .map((ns) => ({ to: `agent:${ns}`, rel: 'reads' as const }))
        out.push({
          kind: 'agent',
          id: `agent:${agent.id}`,
          label: agent.name ?? agent.id,
          group: agent.family,
          hint: `${agent.family} · ${agent.reflex ? 'reflex (tier none)' : `tier ${agent.model_tier}`}`,
          tokens: [(agent.name ?? agent.id).toLowerCase(), agent.id.toLowerCase(), agent.family.toLowerCase()],
          links: [
            ...uses, ...reads,
            ...(agent.workflow ? [{ to: 'module:workflow-builder', rel: 'opens' as const }] : []),
          ],
          // Straight to that agent's inspector, here. Stable id: one inspector,
          // re-pointed, rather than a stack of them.
          run: () => {
            select({ agentId: agent.id })
            if (!openPanel('agent-inspector', { id: 'agent-inspector', title: 'Inspector' })) onPage('fleet')
            onClose()
          },
        })
      }
    }
    if (commands.state.status === 'ready') {
      for (const c of commands.state.data.commands) {
        const about = COMMAND_ABOUT[c.name]
        out.push({
          kind: 'command',
          id: `command:${c.name}`,
          label: c.help,
          hint: c.name.replace(/_/g, ' '),
          tokens: [c.help.toLowerCase(), c.name.toLowerCase()],
          links: about ? [{ to: `module:${about}`, rel: 'about' }] : [],
          // The help line is an example, not a literal ("chart NVDA [daily]"),
          // so it fills the field for editing rather than firing.
          run: () => onCommand(c.help.replace(/\s*\[[^\]]*\]/g, '')),
        })
      }
    }
    // Configuration. The settings modules first — they are where every knob
    // lives — then the knobs the palette can name directly.
    for (const module of MODULES.filter((m) => m.home === 'settings')) {
      out.push({
        kind: 'config',
        id: `config:${module.id}`,
        label: module.title,
        code: module.code,
        hint: module.hint,
        tokens: [module.code.toLowerCase(), module.title.toLowerCase(), 'settings'],
        alias: true,
        links: [],
        run: () => {
          if (!openPanel(module.id, { id: module.id, title: module.title })) onPage('settings')
          onClose()
        },
      })
    }
    if (models.state.status === 'ready') {
      for (const tier of models.state.data.tiers) {
        out.push({
          kind: 'config',
          id: `config:tier:${tier.tier}`,
          label: `Model tier ${tier.tier}`,
          hint: `${tier.backend} · ${tier.model}${tier.key_present || tier.local ? '' : ' · no key'}`,
          tokens: [`tier ${tier.tier}`, tier.tier.toLowerCase(), tier.model.toLowerCase(), 'model'],
          links: [{ to: 'module:settings-models', rel: 'opens' }],
          run: () => {
            if (!openPanel('settings-models', { id: 'settings-models', title: 'Model tiers' })) onPage('settings')
            onClose()
          },
        })
      }
    }
    if (vaults.state.status === 'ready') {
      const { active } = vaults.state.data
      for (const vault of vaults.state.data.vaults) {
        out.push({
          kind: 'config',
          id: `config:vault:${vault.name}`,
          label: `Use vault ${vault.name}`,
          hint: `${vault.path}${vault.name === active ? ' · active' : ''}${vault.exists ? '' : ' · missing'}`,
          tokens: [`vault ${vault.name}`.toLowerCase(), vault.name.toLowerCase(), 'notebook'],
          links: [{ to: 'module:notebook', rel: 'opens' }],
          // Same endpoint the notebook's own vault picker posts to.
          run: () => { void api.vaultSelect(vault.name).finally(onClose) },
        })
      }
    }
    if (tools.state.status === 'ready') {
      for (const tool of tools.state.data.tools) {
        out.push({
          kind: 'tool',
          id: `tool:${tool.id}`,
          label: tool.id,
          group: tool.server,
          hint: `${tool.capability}${tool.mutating ? ' · mutates' : ''}`,
          tokens: [tool.id.toLowerCase(), tool.name.toLowerCase()],
          links: [],
          // Typing a tool name opens that tool, wherever you are. This is the
          // line that turns the catalogue from a menu into a control surface:
          // one panel component, `params.toolId`, and every tool in the
          // catalogue is addressable by name.
          run: () => {
            // A stable id here, unlike a module: typing a tool's name twice
            // should return you to the form you filled in, not hand you an
            // empty one beside it.
            openPanel('tool', {
              id: toolPanelId(tool.id),
              title: tool.name,
              params: { toolId: tool.id },
            })
            onClose()
          },
        })
      }
    }

    return out
  }, [symbols.state, tools.state, agents.state, commands.state, models.state, vaults.state,
    page, onPage, onSymbol, onClose, onCommand, select])

  const reads = { series: symbols, tools, agents, commands, models, vaults }
  const settled = Object.values(reads).every((r) => r.state.status !== 'loading')
  const missing = Object.entries(reads).filter(([, r]) => r.state.status === 'error' || r.state.status === 'absent').map(([k]) => k)
  return { items, settled, missing }
}
