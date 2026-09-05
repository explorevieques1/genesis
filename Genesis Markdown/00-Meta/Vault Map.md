---
title: Vault Map
tags: [meta, generated]
---

# Vault Map

> [!warning] Generated file
> Written by `scripts/build_vault_map.py`. Do not edit by hand —
> re-run the script after adding, renaming, or moving a note.

Every note name resolves to exactly one path. When you meet a `[[wikilink]]`
while reading, this is how you find the file behind it.

**113 notes.** Status: ○ spec · ◐ building · ● built

> [!danger] Name collisions
> These names appear more than once, so `[[link]]` is ambiguous. Rename one:

> - `Agent — Chart Markup` → `10-Architecture/Agent — Chart Markup.md`, `20-Agents/Charting/Agent — Chart Markup.md`
> - `Voice Stack` → `10-Architecture/Voice Stack.md`, `Voice Stack.md`


## 00-Meta

| Note | Path | | Implemented by |
|---|---|---|---|
| `Build Order` | `Genesis Markdown/00-Meta/Build Order.md` |  |  |
| `Conventions` | `Genesis Markdown/00-Meta/Conventions.md` |  |  |
| `Glossary` | `Genesis Markdown/00-Meta/Glossary.md` |  |  |
| `How To Use This Vault` | `Genesis Markdown/00-Meta/How To Use This Vault.md` |  |  |
| `Open Questions` | `Genesis Markdown/00-Meta/Open Questions.md` |  |  |
| `Working With Claude Code` | `Genesis Markdown/00-Meta/Working With Claude Code.md` |  |  |

## 10-Architecture

| Note | Path | | Implemented by |
|---|---|---|---|
| `Agent Contract` | `Genesis Markdown/10-Architecture/Agent Contract.md` | ◐ | [src/genesis/agents/base.py, tests/agents/test_contract.py] |
| `Agent — Chart Markup` | `Genesis Markdown/10-Architecture/Agent — Chart Markup.md` |  |  |
| `Approval Modes` | `Genesis Markdown/10-Architecture/Approval Modes.md` | ○ |  |
| `Biological Design` | `Genesis Markdown/10-Architecture/Biological Design.md` | ○ |  |
| `Charting Engine` | `Genesis Markdown/10-Architecture/Charting Engine.md` | ● | [src/genesis/charting/render.py, src/genesis/charting/theme.py, src/genesis/charting/levels.py, src/genesis/charting/indicators.py, tests/charting/test_render.py, tests/charting/test_levels.py] |
| `Company Data Model` | `Genesis Markdown/10-Architecture/Company Data Model.md` | ● | [src/genesis/company/schema.py, src/genesis/company/symbols.py, src/genesis/company/profile.py, src/genesis/company/store.py, src/genesis/company/providers/yfinance.py, src/genesis/company/providers/edgar.py, tests/company/] |
| `Config And Secrets` | `Genesis Markdown/10-Architecture/Config And Secrets.md` | ◐ | [src/genesis/config.py, src/genesis/default_config.yaml, tests/test_config.py] |
| `Daemon And Cadence` | `Genesis Markdown/10-Architecture/Daemon And Cadence.md` | ◐ | [src/genesis/daemon/daemon.py, src/genesis/daemon/calendar.py, src/genesis/daemon/scheduler.py, src/genesis/daemon/supervisor.py, tests/daemon/] |
| `Error Handling And Degradation` | `Genesis Markdown/10-Architecture/Error Handling And Degradation.md` | ◐ | [src/genesis/errors.py, src/genesis/bus/bus.py] |
| `LLM Model Tiers` | `Genesis Markdown/10-Architecture/LLM Model Tiers.md` | ◐ | [src/genesis/llm/backend.py] |
| `Market Data Catalog` | `Genesis Markdown/10-Architecture/Market Data Catalog.md` | ○ |  |
| `Market Data Plane` | `Genesis Markdown/10-Architecture/Market Data Plane.md` | ◐ | [src/genesis/marketdata/normalize.py, src/genesis/marketdata/interface.py, src/genesis/marketdata/budget.py, src/genesis/marketdata/store.py, src/genesis/marketdata/staleness.py, src/genesis/marketdata/source.py, src/genesis/marketdata/build.py, src/genesis/marketdata/adapters/csv.py, src/genesis/marketdata/adapters/databento.py, src/genesis/marketdata/adapters/yfinance.py, src/genesis/marketdata/adapters/ibkr.py, src/genesis/marketdata/reconcile.py, src/genesis/charting/source.py, src/genesis/charting/bars.py, tests/marketdata/] |
| `Market Data Sources` | `Genesis Markdown/10-Architecture/Market Data Sources.md` | ◐ | [src/genesis/marketdata/staleness.py, src/genesis/marketdata/normalize.py, src/genesis/marketdata/reconcile.py, src/genesis/marketdata/adapters/ibkr.py, src/genesis/config.py] |
| `Markup Spec` | `Genesis Markdown/10-Architecture/Markup Spec.md` | ● | [src/genesis/charting/spec.py, src/genesis/charting/store.py, tests/charting/test_spec.py, tests/charting/test_store_and_outcomes.py] |
| `Observability` | `Genesis Markdown/10-Architecture/Observability.md` | ◐ | [src/genesis/observability.py, src/genesis/cli.py, tests/test_observability.py] |
| `Orchestrator Tools` | `Genesis Markdown/10-Architecture/Orchestrator Tools.md` | ● | [src/genesis/orchestrator/tools.py, src/genesis/orchestrator/runner.py] |
| `Orchestrator` | `Genesis Markdown/10-Architecture/Orchestrator.md` | ◐ | [src/genesis/orchestrator/record.py, src/genesis/orchestrator/verbosity.py, src/genesis/orchestrator/intent.py, src/genesis/orchestrator/loop.py, src/genesis/orchestrator/answers.py, src/genesis/orchestrator/build.py, src/genesis/orchestrator/planner.py, src/genesis/orchestrator/plan.py, src/genesis/orchestrator/registry.py, src/genesis/orchestrator/runner.py, src/genesis/orchestrator/tools.py, src/genesis/orchestrator/toolbridge.py, src/genesis/orchestrator/reasoner.py, src/genesis/llm/anthropic_backend.py] |
| `System Overview` | `Genesis Markdown/10-Architecture/System Overview.md` | ○ |  |
| `Task Bus` | `Genesis Markdown/10-Architecture/Task Bus.md` | ◐ | [src/genesis/bus/bus.py, src/genesis/bus/task.py, tests/bus/test_task_bus.py] |
| `Voice Stack` | `Genesis Markdown/10-Architecture/Voice Stack.md` | ◐ | [src/genesis/voice/capture.py, src/genesis/voice/vad.py, src/genesis/voice/wake.py, src/genesis/voice/stt.py, src/genesis/voice/tts.py, src/genesis/voice/player.py, src/genesis/voice/speaker.py, src/genesis/voice/echo.py, src/genesis/voice/reflex.py, src/genesis/voice/earcons.py, src/genesis/voice/policy.py] |
| `Web Access` | `Genesis Markdown/10-Architecture/Web Access.md` | ○ |  |

## 20-Agents

| Note | Path | | Implemented by |
|---|---|---|---|
| `Agent Index` | `Genesis Markdown/20-Agents/Agent Index.md` | ○ |  |
| `Agent — Chart Markup` | `Genesis Markdown/20-Agents/Charting/Agent — Chart Markup.md` | ● | [src/genesis/agents/charting/chart_markup.py, src/genesis/charting/compose.py, tests/charting/test_agents.py] |
| `Agent — Data Viz` | `Genesis Markdown/20-Agents/Charting/Agent — Data Viz.md` | ● | [src/genesis/agents/charting/data_viz.py, src/genesis/charting/analytics.py, tests/charting/test_analytics.py, tests/charting/test_agents.py] |
| `Agent — Level Watcher` | `Genesis Markdown/20-Agents/Charting/Agent — Level Watcher.md` | ● | [src/genesis/agents/charting/level_watcher.py, src/genesis/charting/outcomes.py, tests/charting/test_agents.py] |
| `Agent — Multi Timeframe` | `Genesis Markdown/20-Agents/Charting/Agent — Multi Timeframe.md` | ● | [src/genesis/agents/charting/multi_timeframe.py, tests/charting/test_agents.py] |
| `Agent — Pattern Recognition` | `Genesis Markdown/20-Agents/Charting/Agent — Pattern Recognition.md` | ● | [src/genesis/agents/charting/pattern_recognition.py, src/genesis/charting/structure.py, tests/charting/test_structure.py, tests/charting/test_agents.py] |
| `Charting Family` | `Genesis Markdown/20-Agents/Charting/Charting Family.md` | ● | [src/genesis/agents/charting/__init__.py, src/genesis/agents/charting/fleet.py, tests/charting/test_agents.py] |
| `Agent — Broker Adapter` | `Genesis Markdown/20-Agents/Execution/Agent — Broker Adapter.md` | ○ |  |
| `Agent — Execution Quality` | `Genesis Markdown/20-Agents/Execution/Agent — Execution Quality.md` | ○ |  |
| `Agent — Order Manager` | `Genesis Markdown/20-Agents/Execution/Agent — Order Manager.md` | ○ |  |
| `Agent — Position And PnL Accountant` | `Genesis Markdown/20-Agents/Execution/Agent — Position And PnL Accountant.md` | ○ |  |
| `Execution Family` | `Genesis Markdown/20-Agents/Execution/Execution Family.md` | ○ |  |
| `Futures Broker Options` | `Genesis Markdown/20-Agents/Execution/Futures Broker Options.md` | ○ |  |
| `Agent — Backtest Vs Live Drift` | `Genesis Markdown/20-Agents/Journal/Agent — Backtest Vs Live Drift.md` | ● | [src/genesis/agents/journal/drift.py, src/genesis/journal/drift.py, tests/journal/test_agents.py] |
| `Agent — Digest` | `Genesis Markdown/20-Agents/Journal/Agent — Digest.md` | ● | [src/genesis/agents/journal/digest.py, tests/journal/test_agents.py] |
| `Agent — Insight Miner` | `Genesis Markdown/20-Agents/Journal/Agent — Insight Miner.md` | ● | [src/genesis/agents/journal/insight_miner.py, src/genesis/journal/patterns.py, tests/journal/test_patterns.py, tests/journal/test_agents.py] |
| `Agent — Performance Analyst` | `Genesis Markdown/20-Agents/Journal/Agent — Performance Analyst.md` | ● | [src/genesis/agents/journal/performance_analyst.py, src/genesis/metrics/core.py, tests/journal/test_metrics.py, tests/journal/test_agents.py] |
| `Agent — Trade Journal` | `Genesis Markdown/20-Agents/Journal/Agent — Trade Journal.md` | ● | [src/genesis/agents/journal/trade_journal.py, tests/journal/test_agents.py] |
| `Agent — Watchdog` | `Genesis Markdown/20-Agents/Journal/Agent — Watchdog.md` | ● | [src/genesis/agents/journal/watchdog.py, src/genesis/journal/health.py, tests/journal/test_agents.py] |
| `Journal Family` | `Genesis Markdown/20-Agents/Journal/Journal Family.md` | ● | [src/genesis/journal/store.py, src/genesis/journal/schema.py, src/genesis/journal/bridge.py, src/genesis/agents/journal/fleet.py, tests/journal/test_bridge.py] |
| `Agent — Fundamental` | `Genesis Markdown/20-Agents/Research/Agent — Fundamental.md` | ○ |  |
| `Agent — Idea Synthesizer` | `Genesis Markdown/20-Agents/Research/Agent — Idea Synthesizer.md` | ○ |  |
| `Agent — Market Analyst` | `Genesis Markdown/20-Agents/Research/Agent — Market Analyst.md` | ○ |  |
| `Agent — News And Catalyst` | `Genesis Markdown/20-Agents/Research/Agent — News And Catalyst.md` | ○ |  |
| `Agent — Regime And Correlation` | `Genesis Markdown/20-Agents/Research/Agent — Regime And Correlation.md` | ○ |  |
| `Agent — Screener` | `Genesis Markdown/20-Agents/Research/Agent — Screener.md` | ○ |  |
| `Agent — Sentiment` | `Genesis Markdown/20-Agents/Research/Agent — Sentiment.md` | ○ |  |
| `Research Family` | `Genesis Markdown/20-Agents/Research/Research Family.md` | ○ |  |
| `Agent — Backtest Runner` | `Genesis Markdown/20-Agents/Strategy/Agent — Backtest Runner.md` | ◐ | - src/genesis/backtest/strategy.py |
| `Agent — ML Signal` | `Genesis Markdown/20-Agents/Strategy/Agent — ML Signal.md` |  |  |
| `Agent — Optimizer` | `Genesis Markdown/20-Agents/Strategy/Agent — Optimizer.md` | ○ |  |
| `Agent — Portfolio And Allocation` | `Genesis Markdown/20-Agents/Strategy/Agent — Portfolio And Allocation.md` | ○ |  |
| `Agent — Prop Firm Guard` | `Genesis Markdown/20-Agents/Strategy/Agent — Prop Firm Guard.md` | ○ |  |
| `Agent — Risk Metrics` | `Genesis Markdown/20-Agents/Strategy/Agent — Risk Metrics.md` | ○ |  |
| `Agent — Strategy Author` | `Genesis Markdown/20-Agents/Strategy/Agent — Strategy Author.md` | ○ |  |
| `Strategy Family` | `Genesis Markdown/20-Agents/Strategy/Strategy Family.md` | ○ |  |

## 30-MCP

| Note | Path | | Implemented by |
|---|---|---|---|
| `MCP Gateway Build Plan` | `Genesis Markdown/30-MCP/MCP Gateway Build Plan.md` | ● | [src/genesis/mcp/] |
| `MCP Gateway` | `Genesis Markdown/30-MCP/MCP Gateway.md` | ● | [src/genesis/mcp/spec.py, src/genesis/mcp/registry.py, |
| `MCP List` | `Genesis Markdown/30-MCP/MCP List.md` |  |  |
| `MCP Server Catalog` | `Genesis Markdown/30-MCP/MCP Server Catalog.md` | ◐ | [src/genesis/mcp/servers.py, |
| `genesis-backtest-mcp` | `Genesis Markdown/30-MCP/genesis-backtest-mcp.md` | ○ |  |
| `genesis-charting-mcp` | `Genesis Markdown/30-MCP/genesis-charting-mcp.md` | ● | [src/genesis/charting/server.py, src/genesis/charting/pine.py, tests/charting/test_charting_server.py] |
| `genesis-execution-mcp` | `Genesis Markdown/30-MCP/genesis-execution-mcp.md` | ○ |  |
| `genesis-memory-mcp` | `Genesis Markdown/30-MCP/genesis-memory-mcp.md` | ○ |  |
| `genesis-tradingview-mcp` | `Genesis Markdown/30-MCP/genesis-tradingview-mcp.md` | ◐ | [src/genesis/tradingview/cdp.py, |

## 40-Memory

| Note | Path | | Implemented by |
|---|---|---|---|
| `Episodic Log` | `Genesis Markdown/40-Memory/Episodic Log.md` | ◐ | [src/genesis/memory/episodic.py, tests/memory/test_episodic.py] |
| `Knowledge Graph` | `Genesis Markdown/40-Memory/Knowledge Graph.md` | ○ |  |
| `Memory Consolidation` | `Genesis Markdown/40-Memory/Memory Consolidation.md` | ○ |  |
| `Memory Fabric` | `Genesis Markdown/40-Memory/Memory Fabric.md` | ◐ | [src/genesis/memory/db.py, src/genesis/memory/episodic.py, src/genesis/memory/ledger.py] |
| `Obsidian Vault Schema` | `Genesis Markdown/40-Memory/Obsidian Vault Schema.md` | ○ |  |
| `Recall Pathways` | `Genesis Markdown/40-Memory/Recall Pathways.md` | ○ |  |
| `Trade Ledger` | `Genesis Markdown/40-Memory/Trade Ledger.md` | ◐ | [src/genesis/memory/ledger.py, tests/memory/test_ledger.py, tests/crash/test_ledger_durability.py] |
| `Vector Store` | `Genesis Markdown/40-Memory/Vector Store.md` | ○ |  |
| `Working Memory` | `Genesis Markdown/40-Memory/Working Memory.md` | ● | [src/genesis/memory/working.py, src/genesis/orchestrator/record.py] |

## 50-Risk

| Note | Path | | Implemented by |
|---|---|---|---|
| `Kill Switch` | `Genesis Markdown/50-Risk/Kill Switch.md` | ○ |  |
| `Paper To Live Promotion` | `Genesis Markdown/50-Risk/Paper To Live Promotion.md` | ○ |  |
| `Pre-Trade Risk Engine` | `Genesis Markdown/50-Risk/Pre-Trade Risk Engine.md` | ○ |  |
| `Prop Firm Rules` | `Genesis Markdown/50-Risk/Prop Firm Rules.md` | ○ |  |
| `Risk Envelope` | `Genesis Markdown/50-Risk/Risk Envelope.md` | ○ |  |
| `Safety Invariants` | `Genesis Markdown/50-Risk/Safety Invariants.md` | ○ |  |

## 60-UI

| Note | Path | | Implemented by |
|---|---|---|---|
| `Dashboard` | `Genesis Markdown/60-UI/Dashboard.md` | ◐ | [ui/src/App.tsx, ui/src/components/SafetyFloor.tsx, ui/src/components/KillSwitch.tsx, ui/src/components/EventStream.tsx, ui/src/components/SystemHealth.tsx] |
| `Desktop Shell` | `Genesis Markdown/60-UI/Desktop Shell.md` |  |  |
| `Fleet View` | `Genesis Markdown/60-UI/Fleet View.md` | ◐ | [ui/src/views/BodyMap.tsx, ui/src/graph/useFleetGraph.ts, ui/src/graph/layout.ts, ui/src/graph/nodes/AgentNode.tsx, ui/src/graph/edges/FleetEdges.tsx, ui/src/views/TraceView.tsx] |
| `Genesis Core` | `Genesis Markdown/60-UI/Genesis Core.md` | ◐ | [ui/src/components/GenesisCore.tsx, ui/src/graph/nodes/CoreNode.tsx] |
| `UI Stack` | `Genesis Markdown/60-UI/UI Stack.md` | ◐ | [ui/package.json, ui/vite.config.ts, ui/src/styles/tokens.css, ui/src/transport/transport.ts, ui/src/transport/live.ts, ui/src/lib/format.ts, ui/src/components/SurfaceBoundary.tsx, ui/src/components/TapToSpeak.tsx, src/genesis/server/app.py, src/genesis/commands.py, tests/test_server.py, tests/test_commands.py] |
| `Voice UX` | `Genesis Markdown/60-UI/Voice UX.md` | ● | [src/genesis/voice/speech.py, src/genesis/voice/earcons.py, src/genesis/voice/policy.py, src/genesis/orchestrator/verbosity.py] |
| `Widget Catalog` | `Genesis Markdown/60-UI/Widget Catalog.md` | ◐ | [ui/src/components/EventStream.tsx, ui/src/components/SafetyFloor.tsx, ui/src/components/KillSwitch.tsx, ui/src/views/MemoryFabric.tsx, ui/src/views/ExecutionPath.tsx] |

## 70-Schemas

| Note | Path | | Implemented by |
|---|---|---|---|
| `Data Model Overview` | `Genesis Markdown/70-Schemas/Data Model Overview.md` | ○ |  |
| `Event Schema` | `Genesis Markdown/70-Schemas/Event Schema.md` | ○ |  |
| `Idea Schema` | `Genesis Markdown/70-Schemas/Idea Schema.md` | ○ |  |
| `Markup Spec Schema` | `Genesis Markdown/70-Schemas/Markup Spec Schema.md` | ● | [src/genesis/charting/spec.py, tests/charting/test_spec.py] |
| `Order And Fill Schema` | `Genesis Markdown/70-Schemas/Order And Fill Schema.md` | ◐ | [src/genesis/memory/ledger.py] |
| `Strategy Schema` | `Genesis Markdown/70-Schemas/Strategy Schema.md` | ○ |  |
| `Trade Journal Schema` | `Genesis Markdown/70-Schemas/Trade Journal Schema.md` | ● | [src/genesis/journal/schema.py, src/genesis/journal/store.py, tests/journal/test_schema.py, tests/journal/test_store.py] |

## 80-Repos

| Note | Path | | Implemented by |
|---|---|---|---|
| `Repo Map` | `Genesis Markdown/80-Repos/Repo Map.md` |  |  |
| `Repo — Gensis Terminal Official` | `Genesis Markdown/80-Repos/Repo — Gensis Terminal Official.md` |  |  |
| `Repo — Lithium Codebase` | `Genesis Markdown/80-Repos/Repo — Lithium Codebase.md` |  |  |
| `Repo — gensis-agents` | `Genesis Markdown/80-Repos/Repo — gensis-agents.md` |  |  |
| `Repo — jarvis` | `Genesis Markdown/80-Repos/Repo — jarvis.md` |  |  |
| `Trading Corpus Index` | `Genesis Markdown/80-Repos/Trading Corpus Index.md` |  |  |

## (root)

| Note | Path | | Implemented by |
|---|---|---|---|
| `Biological Design for Gensis Orchistrator` | `Genesis Markdown/Biological Design for Gensis Orchistrator.md` |  |  |
| `Genesis Agent — Home` | `Genesis Markdown/Genesis Agent — Home.md` |  |  |
| `Genesis Commands` | `Genesis Markdown/Genesis Commands.md` |  |  |
| `IBKR` | `Genesis Markdown/IBKR.md` |  |  |
| `Voice Stack` | `Genesis Markdown/Voice Stack.md` |  |  |
| `yfinance` | `Genesis Markdown/yfinance.md` |  |  |

---

## Build status

```dataview
TABLE status, implemented_by
FROM "10-Architecture" OR "20-Agents" OR "30-MCP" OR "40-Memory" OR "50-Risk" OR "60-UI" OR "70-Schemas"
WHERE status != null
SORT status ASC, file.name ASC
```
