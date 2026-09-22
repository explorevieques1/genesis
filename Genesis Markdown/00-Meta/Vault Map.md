---
title: Vault Map
tags: [meta, generated]
status: built
implemented_by: [src/genesis/dna/__init__.py, src/genesis/dna/vault_map.py, ui/src/workspace/panels/dna.tsx, scripts/build_vault_map.py]
---

# Vault Map

> [!warning] Generated file
> Written by `genesis dna map` (`src/genesis/dna/vault_map.py`). Do not edit
> by hand — re-run it after adding, renaming, or moving a note.

Every note name resolves to exactly one path. When you meet a `[[wikilink]]`
while reading, this is how you find the file behind it.

**220 notes.** Status: ○ spec · ◐ building · ● built

> [!danger] Name collisions
> These names appear more than once, so `[[link]]` is ambiguous. Rename one:

> - `Agent — Chart Markup` → `Genesis Markdown/10-Architecture/Agent — Chart Markup.md`, `Genesis Markdown/20-Agents/Charting/Agent — Chart Markup.md`
> - `Voice Stack` → `Genesis Markdown/10-Architecture/Voice Stack.md`, `Genesis Markdown/Voice Stack.md`


## 00-Meta

| Note | Path | | Implemented by |
|---|---|---|---|
| `Build Order` | `Genesis Markdown/00-Meta/Build Order.md` |  | tests/daemon/test_entry_point.py |
| `Conventions` | `Genesis Markdown/00-Meta/Conventions.md` | ● | evals/__init__.py, evals/conftest.py, evals/helpers.py, evals/test_scaffold.py, src/genesis/dna/__init__.py, src/genesis/dna/drift.py, src/genesis/dna/genome.py, src/genesis/dna/prompts.py, ui/src/workspace/panels/dna.tsx, scripts/check_body_map.py, tests/dna/test_drift.py, tests/dna/test_genome.py |
| `Glossary` | `Genesis Markdown/00-Meta/Glossary.md` |  |  |
| `How To Use This Vault` | `Genesis Markdown/00-Meta/How To Use This Vault.md` |  |  |
| `Master Plan v2` | `Genesis Markdown/00-Meta/Master Plan v2.md` |  |  |
| `Open Questions` | `Genesis Markdown/00-Meta/Open Questions.md` |  |  |
| `UI-0 Build Order` | `Genesis Markdown/00-Meta/UI-0 Build Order.md` | ◐ | src/genesis/orchestrator/answer.py, src/genesis/orchestrator/loop.py, src/genesis/orchestrator/build.py, src/genesis/server/analyst.py, src/genesis/server/app.py, src/genesis/server/tool_routes.py, tests/test_parity.py |
| `Working With Claude Code` | `Genesis Markdown/00-Meta/Working With Claude Code.md` |  |  |

## 10-Architecture

| Note | Path | | Implemented by |
|---|---|---|---|
| `Agent Contract` | `Genesis Markdown/10-Architecture/Agent Contract.md` | ● | src/genesis/agents/base.py, tests/agents/test_contract.py, src/genesis/agents/__init__.py, tests/conftest.py, tests/helpers.py, src/genesis/server/fleet.py, ui/src/components/AgentInspector.tsx, ui/src/workspace/panels/automation.tsx |
| `Agent — Chart Markup` | `Genesis Markdown/10-Architecture/Agent — Chart Markup.md` |  |  |
| `Approval Modes` | `Genesis Markdown/10-Architecture/Approval Modes.md` | ● | src/genesis/execution/approval.py, src/genesis/execution/order_manager.py, tests/execution/test_approval.py |
| `Biological Design` | `Genesis Markdown/10-Architecture/Biological Design.md` | ◐ | src/genesis/voice/reflex.py, ui/src/components/PhaseMark.tsx, tests/test_reflex.py, ui/src/workspace/panels/system.tsx, src/genesis/biology.py, ui/src/views/Biology.tsx |
| `Charting Engine` | `Genesis Markdown/10-Architecture/Charting Engine.md` | ● | src/genesis/charting/render.py, src/genesis/charting/theme.py, src/genesis/charting/levels.py, src/genesis/charting/indicators.py, tests/charting/test_render.py, tests/charting/test_levels.py, ui/src/workspace/panels/tradingview.tsx, ui/src/workspace/panels/charting.tsx, ui/src/components/charts/SymbolBar.tsx, src/genesis/server/symbol_routes.py, tests/test_symbol_routes.py, src/genesis/research/setup.py, tests/research/test_setup.py |
| `Company Data Model` | `Genesis Markdown/10-Architecture/Company Data Model.md` | ● | src/genesis/company/schema.py, src/genesis/company/symbols.py, src/genesis/company/profile.py, src/genesis/company/store.py, src/genesis/company/providers/yfinance.py, src/genesis/company/providers/edgar.py, tests/company/, src/genesis/company/__init__.py, src/genesis/company/providers/__init__.py, tests/company/__init__.py, tests/company/test_hazards.py, tests/company/test_providers.py, tests/company/test_store.py |
| `Config And Secrets` | `Genesis Markdown/10-Architecture/Config And Secrets.md` | ● | src/genesis/config.py, src/genesis/default_config.yaml, tests/test_config.py |
| `Daemon And Cadence` | `Genesis Markdown/10-Architecture/Daemon And Cadence.md` | ● | src/genesis/daemon/daemon.py, src/genesis/daemon/calendar.py, src/genesis/daemon/scheduler.py, src/genesis/daemon/supervisor.py, tests/daemon/, src/genesis/daemon/__init__.py, tests/daemon/test_calendar.py, tests/daemon/test_daemon.py, tests/daemon/test_scheduler.py, tests/daemon/test_supervisor.py |
| `Error Handling And Degradation` | `Genesis Markdown/10-Architecture/Error Handling And Degradation.md` | ● | src/genesis/errors.py, src/genesis/bus/bus.py, ui/src/components/SurfaceBoundary.tsx |
| `LLM Model Tiers` | `Genesis Markdown/10-Architecture/LLM Model Tiers.md` | ● | src/genesis/llm/backend.py, src/genesis/llm/anthropic_backend.py, src/genesis/llm/openai_compat.py, src/genesis/llm/usage.py, src/genesis/llm/tiers.py, src/genesis/cli.py, src/genesis/llm/parse.py, tests/llm/test_anthropic_tool_loop.py, tests/llm/test_bad_request.py, tests/llm/test_ollama_status.py, tests/llm/test_providers.py |
| `Market Data Catalog` | `Genesis Markdown/10-Architecture/Market Data Catalog.md` | ◐ | src/genesis/marketdata/universe.py |
| `Market Data Plane` | `Genesis Markdown/10-Architecture/Market Data Plane.md` | ● | src/genesis/marketdata/normalize.py, src/genesis/marketdata/interface.py, src/genesis/marketdata/budget.py, src/genesis/marketdata/store.py, src/genesis/marketdata/staleness.py, src/genesis/marketdata/source.py, src/genesis/marketdata/build.py, src/genesis/marketdata/adapters/csv.py, src/genesis/marketdata/adapters/databento.py, src/genesis/marketdata/adapters/yfinance.py, src/genesis/marketdata/adapters/ibkr.py, src/genesis/marketdata/reconcile.py, src/genesis/marketdata/ibkr_live.py, ui/src/workspace/panels/account.tsx, src/genesis/server/broker_routes.py, ui/src/workspace/panels/broker.tsx, src/genesis/charting/source.py, src/genesis/charting/bars.py, tests/marketdata/, src/genesis/marketdata/__init__.py, src/genesis/marketdata/adapters/__init__.py, tests/charting/test_bars.py, tests/marketdata/__init__.py, tests/marketdata/test_adapters.py, tests/marketdata/test_budget.py, tests/marketdata/test_ibkr.py, tests/marketdata/test_ibkr_chain.py, tests/marketdata/test_ibkr_live.py, tests/marketdata/test_normalize.py, tests/marketdata/test_source.py, tests/marketdata/test_staleness.py, tests/marketdata/test_store.py, src/genesis/server/symbol_routes.py |
| `Market Data Sources` | `Genesis Markdown/10-Architecture/Market Data Sources.md` | ● | src/genesis/marketdata/staleness.py, src/genesis/marketdata/normalize.py, src/genesis/marketdata/reconcile.py, src/genesis/marketdata/adapters/ibkr.py, src/genesis/marketdata/store.py, src/genesis/config.py, tests/marketdata/test_open_store.py, src/genesis/marketdata/quotes.py, tests/marketdata/test_reconcile.py, src/genesis/marketdata/heatmap.py, src/genesis/marketdata/performance.py, ui/src/components/charts/PriceChart.tsx, ui/src/workspace/panels/charting.tsx, ui/src/workspace/panels/heatmap.tsx, ui/src/workspace/panels/performance.tsx, ui/src/workspace/panels/ranges.tsx, ui/src/workspace/panels/tradingview.tsx |
| `Markup Spec` | `Genesis Markdown/10-Architecture/Markup Spec.md` | ● | src/genesis/charting/spec.py, src/genesis/charting/store.py, tests/charting/test_spec.py, tests/charting/test_store_and_outcomes.py, src/genesis/charting/timeframes.py |
| `Observability` | `Genesis Markdown/10-Architecture/Observability.md` | ● | src/genesis/observability.py, src/genesis/cli.py, tests/test_observability.py, ui/src/views/TraceView.tsx, tests/test_fleet_health.py |
| `Operating Model` | `Genesis Markdown/10-Architecture/Operating Model.md` | ◐ | src/genesis/company/resolve.py, src/genesis/orchestrator/answer.py, src/genesis/server/analyst.py, tests/test_parity.py |
| `Orchestrator Tools` | `Genesis Markdown/10-Architecture/Orchestrator Tools.md` | ● | src/genesis/orchestrator/tools.py, src/genesis/orchestrator/runner.py, tests/orchestrator/test_runner.py, tests/orchestrator/test_tools.py |
| `Orchestrator` | `Genesis Markdown/10-Architecture/Orchestrator.md` | ◐ | src/genesis/orchestrator/answer.py, src/genesis/orchestrator/record.py, src/genesis/orchestrator/verbosity.py, src/genesis/orchestrator/intent.py, src/genesis/orchestrator/loop.py, src/genesis/orchestrator/answers.py, src/genesis/orchestrator/build.py, src/genesis/orchestrator/planner.py, src/genesis/orchestrator/plan.py, src/genesis/orchestrator/registry.py, src/genesis/orchestrator/runner.py, src/genesis/research/findings.py, src/genesis/orchestrator/tools.py, src/genesis/orchestrator/toolbridge.py, src/genesis/orchestrator/reasoner.py, src/genesis/llm/anthropic_backend.py, tests/orchestrator/test_plan.py, tests/orchestrator/test_planner.py, tests/orchestrator/test_reasoner_tools.py, tests/orchestrator/test_voice_planning.py, tests/test_voice_loop.py, ui/src/workspace/panels/automation.tsx |
| `System Overview` | `Genesis Markdown/10-Architecture/System Overview.md` | ○ |  |
| `Task Bus` | `Genesis Markdown/10-Architecture/Task Bus.md` | ● | src/genesis/bus/bus.py, src/genesis/bus/task.py, tests/bus/test_task_bus.py, src/genesis/bus/__init__.py, evals/test_agent_routing.py |
| `Voice Stack` | `Genesis Markdown/10-Architecture/Voice Stack.md` | ● | src/genesis/voice/capture.py, src/genesis/voice/vad.py, src/genesis/voice/wake.py, src/genesis/voice/stt.py, src/genesis/voice/tts.py, src/genesis/voice/player.py, src/genesis/voice/speaker.py, src/genesis/voice/echo.py, src/genesis/voice/reflex.py, src/genesis/voice/earcons.py, src/genesis/voice/policy.py, src/genesis/orchestrator/build.py, tests/orchestrator/test_build.py, evals/corpora/intent.py, evals/test_intent_classification.py, src/genesis/server/voice_routes.py, ui/src/components/TapToSpeak.tsx, ui/src/lib/speak.ts |
| `Web Access` | `Genesis Markdown/10-Architecture/Web Access.md` | ◐ | src/genesis/browser/__init__.py |

## 20-Agents

| Note | Path | | Implemented by |
|---|---|---|---|
| `Agent Index` | `Genesis Markdown/20-Agents/Agent Index.md` | ◐ | ui/src/data/roster.ts, evals/corpora/requests.py, evals/test_request_coverage.py, src/genesis/server/fleet.py |
| `Agent — Chart Markup` | `Genesis Markdown/20-Agents/Charting/Agent — Chart Markup.md` | ● | src/genesis/agents/charting/chart_markup.py, src/genesis/charting/compose.py, tests/charting/test_agents.py |
| `Agent — Data Viz` | `Genesis Markdown/20-Agents/Charting/Agent — Data Viz.md` | ● | src/genesis/agents/charting/data_viz.py, src/genesis/charting/analytics.py, tests/charting/test_analytics.py, tests/charting/test_agents.py |
| `Agent — Level Watcher` | `Genesis Markdown/20-Agents/Charting/Agent — Level Watcher.md` | ● | src/genesis/agents/charting/level_watcher.py, src/genesis/charting/outcomes.py, tests/charting/test_agents.py |
| `Agent — Multi Timeframe` | `Genesis Markdown/20-Agents/Charting/Agent — Multi Timeframe.md` | ● | src/genesis/agents/charting/multi_timeframe.py, tests/charting/test_agents.py |
| `Agent — Pattern Recognition` | `Genesis Markdown/20-Agents/Charting/Agent — Pattern Recognition.md` | ● | src/genesis/agents/charting/pattern_recognition.py, src/genesis/charting/structure.py, tests/charting/test_structure.py, tests/charting/test_agents.py |
| `Charting Family` | `Genesis Markdown/20-Agents/Charting/Charting Family.md` | ● | src/genesis/agents/charting/__init__.py, src/genesis/agents/charting/fleet.py, tests/charting/test_agents.py, src/genesis/charting/outcomes.py, tests/charting/conftest.py, tests/journal/test_question_catalogue.py, evals/charting_questions.yaml |
| `Agent — Broker Adapter` | `Genesis Markdown/20-Agents/Execution/Agent — Broker Adapter.md` | ◐ | src/genesis/execution/ibkr_broker.py, tests/execution/fake_broker.py |
| `Agent — Execution Quality` | `Genesis Markdown/20-Agents/Execution/Agent — Execution Quality.md` | ◐ | src/genesis/agents/execution/execution_quality.py, tests/execution/test_execution_quality.py |
| `Agent — Order Manager` | `Genesis Markdown/20-Agents/Execution/Agent — Order Manager.md` | ◐ | src/genesis/execution/order_manager.py, src/genesis/server/execution_routes.py, tests/execution/test_order_manager.py, tests/execution/fake_broker.py, ui/src/api/useExecState.ts, ui/src/workspace/panels/trade.tsx |
| `Agent — Position And PnL Accountant` | `Genesis Markdown/20-Agents/Execution/Agent — Position And PnL Accountant.md` | ◐ | src/genesis/agents/execution/accountant.py, tests/execution/test_accountant.py |
| `Execution Family` | `Genesis Markdown/20-Agents/Execution/Execution Family.md` | ◐ | src/genesis/execution/, src/genesis/agents/execution/__init__.py, src/genesis/execution/__init__.py, src/genesis/server/execution_routes.py |
| `Futures Broker Options` | `Genesis Markdown/20-Agents/Execution/Futures Broker Options.md` | ○ |  |
| `Agent — Backtest Vs Live Drift` | `Genesis Markdown/20-Agents/Journal/Agent — Backtest Vs Live Drift.md` | ● | src/genesis/agents/journal/drift.py, src/genesis/journal/drift.py, tests/journal/test_agents.py |
| `Agent — Digest` | `Genesis Markdown/20-Agents/Journal/Agent — Digest.md` | ● | src/genesis/agents/journal/digest.py, tests/journal/test_agents.py |
| `Agent — Insight Miner` | `Genesis Markdown/20-Agents/Journal/Agent — Insight Miner.md` | ● | src/genesis/agents/journal/insight_miner.py, src/genesis/journal/patterns.py, tests/journal/test_patterns.py, tests/journal/test_agents.py, ui/src/workspace/panels/journal.tsx |
| `Agent — Performance Analyst` | `Genesis Markdown/20-Agents/Journal/Agent — Performance Analyst.md` | ● | src/genesis/agents/journal/performance_analyst.py, src/genesis/metrics/core.py, tests/journal/test_metrics.py, tests/journal/test_agents.py |
| `Agent — Trade Journal` | `Genesis Markdown/20-Agents/Journal/Agent — Trade Journal.md` | ● | src/genesis/agents/journal/trade_journal.py, src/genesis/journal/bridge.py, src/genesis/server/journal_routes.py, ui/src/workspace/panels/charting.tsx, ui/src/workspace/panels/journal.tsx, tests/journal/test_agents.py |
| `Agent — Watchdog` | `Genesis Markdown/20-Agents/Journal/Agent — Watchdog.md` | ● | src/genesis/agents/journal/watchdog.py, src/genesis/journal/health.py, tests/journal/test_agents.py |
| `Journal Family` | `Genesis Markdown/20-Agents/Journal/Journal Family.md` | ● | src/genesis/server/journal_routes.py, ui/src/workspace/panels/journal.tsx, src/genesis/journal/store.py, src/genesis/journal/schema.py, src/genesis/journal/bridge.py, src/genesis/agents/journal/fleet.py, tests/journal/test_bridge.py, src/genesis/agents/journal/__init__.py, tests/journal/conftest.py, tests/journal/test_agents.py |
| `Agent — Fundamental` | `Genesis Markdown/20-Agents/Research/Agent — Fundamental.md` | ◐ | src/genesis/agents/research/fundamental.py, tests/company/test_valuation.py, src/genesis/company/valuation.py, src/genesis/company/resolve.py, src/genesis/commands.py |
| `Agent — Idea Synthesizer` | `Genesis Markdown/20-Agents/Research/Agent — Idea Synthesizer.md` | ● | src/genesis/agents/research/idea_synthesizer.py, src/genesis/research/schema.py, tests/research/test_research_family.py |
| `Agent — Market Analyst` | `Genesis Markdown/20-Agents/Research/Agent — Market Analyst.md` | ● | src/genesis/agents/research/market_analyst.py, tests/research/test_research_family.py |
| `Agent — News And Catalyst` | `Genesis Markdown/20-Agents/Research/Agent — News And Catalyst.md` | ◐ | src/genesis/agents/research/news_catalyst.py, src/genesis/agents/research/fleet.py, src/genesis/server/news_routes.py, src/genesis/news/ideas.py, tests/news/test_ideas.py, src/genesis/news/symbols.py |
| `Agent — News Collector` | `Genesis Markdown/20-Agents/Research/Agent — News Collector.md` | ● | src/genesis/agents/research/news_collector.py, src/genesis/news/collect.py, src/genesis/news/store.py, src/genesis/agents/research/fleet.py |
| `Agent — Regime And Correlation` | `Genesis Markdown/20-Agents/Research/Agent — Regime And Correlation.md` | ○ |  |
| `Agent — Screener` | `Genesis Markdown/20-Agents/Research/Agent — Screener.md` | ◐ | src/genesis/screener/snapshot.py, src/genesis/screener/scan.py, src/genesis/screener/chat.py, src/genesis/agents/research/screener.py, src/genesis/screener/__init__.py, tests/test_screener.py |
| `Agent — Sentiment` | `Genesis Markdown/20-Agents/Research/Agent — Sentiment.md` | ○ |  |
| `Agent — Session Plan` | `Genesis Markdown/20-Agents/Research/Agent — Session Plan.md` | ◐ | src/genesis/agents/research/session_plan.py, src/genesis/research/plan.py, src/genesis/server/plan_routes.py, tests/research/test_session_plan.py, ui/src/workspace/panels/trade-ideas.tsx |
| `Agent — Topic Researcher` | `Genesis Markdown/20-Agents/Research/Agent — Topic Researcher.md` | ● | src/genesis/agents/research/topic_researcher.py, src/genesis/agents/research/fleet.py, src/genesis/research/store.py, src/genesis/research/web.py, src/genesis/cli.py, tests/research/test_research_family.py |
| `Research Family` | `Genesis Markdown/20-Agents/Research/Research Family.md` | ◐ | src/genesis/agents/research/fleet.py, src/genesis/research/store.py, src/genesis/agents/research/__init__.py, src/genesis/research/__init__.py, src/genesis/research/schema.py, tests/research/test_research_family.py, src/genesis/research/web.py, ui/src/workspace/panels/research.tsx |
| `Agent — Backtest Runner` | `Genesis Markdown/20-Agents/Strategy/Agent — Backtest Runner.md` | ◐ | src/genesis/backtest/__init__.py, src/genesis/backtest/runner.py, src/genesis/backtest/spec_strategy.py, src/genesis/backtest/store.py, ui/src/workspace/panels/backtest.tsx, tests/backtest/test_nautilus_runner.py, src/genesis/server/backtest_routes.py, src/genesis/backtest/strategy.py |
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
| `MCP Gateway Build Plan` | `Genesis Markdown/30-MCP/MCP Gateway Build Plan.md` | ● | src/genesis/mcp/ |
| `MCP Gateway` | `Genesis Markdown/30-MCP/MCP Gateway.md` | ● | src/genesis/mcp/__init__.py, src/genesis/mcp/allowlist.py, src/genesis/mcp/build.py, src/genesis/mcp/cache.py, src/genesis/mcp/discovery.py, src/genesis/mcp/errors.py, src/genesis/mcp/fence.py, src/genesis/mcp/gateway.py, src/genesis/mcp/limits.py, src/genesis/mcp/registry.py, src/genesis/mcp/router.py, src/genesis/mcp/runtime.py, src/genesis/mcp/spec.py, src/genesis/mcp/transports.py, src/genesis/orchestrator/toolbridge.py, tests/helpers_mcp.py, tests/mcp/test_allowlist.py, tests/mcp/test_cache.py, tests/mcp/test_fence.py, tests/mcp/test_gateway.py, tests/mcp/test_gateway_build.py, tests/mcp/test_gateway_path.py, tests/mcp/test_limits.py, tests/mcp/test_registry.py, tests/mcp/test_router.py, tests/mcp/test_runtime.py, tests/mcp/test_sdk_not_shadowed.py, tests/mcp/test_sdk_shapes.py, tests/orchestrator/test_toolbridge.py, evals/corpora/tool_selection.py, evals/test_tool_selection.py, src/genesis/research/web.py, src/genesis/server/tool_routes.py, ui/src/workspace/panels/system.tsx, ui/src/workspace/panels/tool.tsx, ui/src/graph/nodes/SystemNode.tsx |
| `MCP List` | `Genesis Markdown/30-MCP/MCP List.md` |  |  |
| `MCP Server Catalog` | `Genesis Markdown/30-MCP/MCP Server Catalog.md` | ◐ | src/genesis/mcp/servers.py, src/genesis/mcp/default_servers.yaml, src/genesis/mcp/discovery.py, tests/mcp/test_discovery.py, tests/mcp/test_servers.py |
| `genesis-backtest-mcp` | `Genesis Markdown/30-MCP/genesis-backtest-mcp.md` | ○ |  |
| `genesis-charting-mcp` | `Genesis Markdown/30-MCP/genesis-charting-mcp.md` | ● | src/genesis/charting/server.py, src/genesis/charting/pine.py, tests/charting/test_charting_server.py |
| `genesis-execution-mcp` | `Genesis Markdown/30-MCP/genesis-execution-mcp.md` | ○ |  |
| `genesis-memory-mcp` | `Genesis Markdown/30-MCP/genesis-memory-mcp.md` | ○ |  |
| `genesis-tradingview-mcp` | `Genesis Markdown/30-MCP/genesis-tradingview-mcp.md` | ● | src/genesis/tradingview/cdp.py, src/genesis/tradingview/surface.py, src/genesis/tradingview/markup.py, src/genesis/tradingview/server.py, src/genesis/tradingview/selectors.yaml, src/genesis/tradingview/__init__.py, tests/tradingview/test_cdp.py, tests/tradingview/test_surface.py |

## 40-Memory

| Note | Path | | Implemented by |
|---|---|---|---|
| `Episodic Log` | `Genesis Markdown/40-Memory/Episodic Log.md` | ◐ | src/genesis/memory/episodic.py, tests/memory/test_episodic.py, src/genesis/ids.py |
| `Knowledge Graph` | `Genesis Markdown/40-Memory/Knowledge Graph.md` | ◐ | src/genesis/memory/graph.py, src/genesis/research/store.py, tests/research/test_canvas.py, ui/src/graph/nodes/EntityNode.tsx |
| `Memory Consolidation` | `Genesis Markdown/40-Memory/Memory Consolidation.md` | ◐ | src/genesis/memory/consolidate.py, tests/memory/test_consolidate.py |
| `Memory Fabric` | `Genesis Markdown/40-Memory/Memory Fabric.md` | ● | src/genesis/memory/db.py, src/genesis/memory/episodic.py, src/genesis/memory/ledger.py, src/genesis/memory/__init__.py, ui/src/views/MemoryFabric.tsx, ui/src/components/graph/ForceGraph.tsx |
| `Obsidian Vault Schema` | `Genesis Markdown/40-Memory/Obsidian Vault Schema.md` | ◐ | src/genesis/research/store.py |
| `Recall Pathways` | `Genesis Markdown/40-Memory/Recall Pathways.md` | ◐ | evals/test_memory_recall.py |
| `Research Directory` | `Genesis Markdown/40-Memory/Research Directory.md` | ● | src/genesis/research/store.py, src/genesis/research/schema.py, src/genesis/research/findings.py, src/genesis/company/resolve.py, src/genesis/server/reads.py, ui/src/workspace/panels/research.tsx, tests/orchestrator/test_findings.py |
| `Trade Ledger` | `Genesis Markdown/40-Memory/Trade Ledger.md` | ● | src/genesis/memory/ledger.py, tests/memory/test_ledger.py, tests/crash/test_ledger_durability.py, tests/crash/helpers.py, tests/crash/ledger_writer.py |
| `Vector Store` | `Genesis Markdown/40-Memory/Vector Store.md` | ◐ | src/genesis/memory/vectors.py, tests/memory/test_vectors.py |
| `Working Memory` | `Genesis Markdown/40-Memory/Working Memory.md` | ● | src/genesis/memory/working.py, src/genesis/orchestrator/record.py, tests/orchestrator/test_record.py, tests/test_working_memory.py |

## 50-Risk

| Note | Path | | Implemented by |
|---|---|---|---|
| `Kill Switch` | `Genesis Markdown/50-Risk/Kill Switch.md` | ◐ | src/genesis/execution/killswitch.py, src/genesis/execution/halt.py, ui/src/components/KillSwitch.tsx |
| `Paper To Live Promotion` | `Genesis Markdown/50-Risk/Paper To Live Promotion.md` | ○ |  |
| `Pre-Trade Risk Engine` | `Genesis Markdown/50-Risk/Pre-Trade Risk Engine.md` | ◐ | src/genesis/execution/risk.py, tests/execution/test_risk.py, ui/src/views/ExecutionPath.tsx |
| `Prop Firm Rules` | `Genesis Markdown/50-Risk/Prop Firm Rules.md` | ○ |  |
| `Risk Envelope` | `Genesis Markdown/50-Risk/Risk Envelope.md` | ◐ | src/genesis/config.py, src/genesis/marketdata/universe.py, tests/marketdata/test_universe.py |
| `Safety Invariants` | `Genesis Markdown/50-Risk/Safety Invariants.md` | ◐ | src/genesis/metrics/__init__.py, ui/src/components/SafetyFloor.tsx, ui/src/graph/nodes/SystemNode.tsx |

## 60-UI

| Note | Path | | Implemented by |
|---|---|---|---|
| `Ask Genesis` | `Genesis Markdown/60-UI/Ask Genesis.md` | ◐ | src/genesis/server/conversation_routes.py, ui/src/workspace/panels/ask.tsx, ui/src/workspace/panels/help.tsx, ui/src/api/client.ts, src/genesis/memory/conversations.py |
| `Automation` | `Genesis Markdown/60-UI/Automation.md` | ◐ | src/genesis/automation/, src/genesis/automation/actions.py, src/genesis/automation/catalog.py, src/genesis/automation/templates.py, src/genesis/server/automation_routes.py, tests/automation/, ui/src/workspace/panels/workflow-builder.tsx, ui/src/graph/nodes/StepNode.tsx, ui/src/components/automation/wiring.ts, src/genesis/automation/__init__.py, src/genesis/automation/runner.py, tests/automation/test_routes.py, tests/automation/test_runner.py |
| `Candle Ranges` | `Genesis Markdown/60-UI/Candle Ranges.md` | ● | src/genesis/marketdata/ranges.py, src/genesis/server/range_routes.py, ui/src/workspace/panels/ranges.tsx, tests/marketdata/test_ranges.py |
| `Chart Tools` | `Genesis Markdown/60-UI/Chart Tools.md` | ● | src/genesis/charting/drawings.py, src/genesis/server/drawing_routes.py, ui/src/components/charts/DrawingLayer.tsx, ui/src/components/charts/ChartControls.tsx, ui/src/components/charts/drawings.ts, ui/src/components/charts/drawings.check.ts, tests/charting/test_drawings.py |
| `Company Description` | `Genesis Markdown/60-UI/Company Description.md` | ● | ui/src/workspace/panels/company.tsx, tests/company/test_describe.py, ui/src/api/client.ts, src/genesis/company/profile.py, src/genesis/company/providers/yfinance.py, src/genesis/marketdata/quotes.py, src/genesis/server/reads.py, src/genesis/server/watchlist_routes.py |
| `Dashboard` | `Genesis Markdown/60-UI/Dashboard.md` | ◐ | ui/src/App.tsx, ui/src/components/SafetyFloor.tsx, ui/src/components/KillSwitch.tsx, ui/src/components/EventStream.tsx, ui/src/components/SystemHealth.tsx, ui/src/shell/CommandBar.tsx, ui/src/shell/TopBar.tsx, ui/src/shell/pages.ts, ui/src/store/useGenesis.ts |
| `Desktop Shell` | `Genesis Markdown/60-UI/Desktop Shell.md` |  |  |
| `Economic Calendar` | `Genesis Markdown/60-UI/Economic Calendar.md` | ● | src/genesis/news/econ.py, ui/src/workspace/panels/econ.tsx, src/genesis/news/store.py, src/genesis/news/collect.py, src/genesis/server/news_routes.py, ui/src/components/EconCountdown.tsx, ui/src/components/SystemHealth.tsx, ui/src/api/client.ts |
| `Feed` | `Genesis Markdown/60-UI/Feed.md` | ● | src/genesis/automation/feed.py, src/genesis/server/automation_routes.py, ui/src/workspace/panels/feed.tsx, tests/automation/test_feed.py |
| `Fleet View` | `Genesis Markdown/60-UI/Fleet View.md` | ◐ | ui/src/views/BodyMap.tsx, ui/src/graph/useFleetGraph.ts, ui/src/graph/layout.ts, ui/src/graph/nodes/AgentNode.tsx, ui/src/graph/edges/FleetEdges.tsx, ui/src/views/TraceView.tsx, ui/src/types/fleet.ts, ui/src/store/useGenesis.ts |
| `Genesis Core` | `Genesis Markdown/60-UI/Genesis Core.md` | ◐ | ui/src/components/GenesisCore.tsx, ui/src/shell/CommandBar.tsx, ui/src/graph/nodes/CoreNode.tsx, ui/src/components/Primitives.tsx, ui/src/lib/motion.ts, ui/src/lib/speak.ts |
| `Index Movers` | `Genesis Markdown/60-UI/Index Movers.md` | ● | src/genesis/marketdata/index_map.py, ui/src/workspace/panels/movers.tsx, tests/marketdata/test_index_map.py, ui/src/workspace/modules.ts, ui/src/api/client.ts, src/genesis/marketdata/heatmap.py, src/genesis/server/watchlist_routes.py |
| `News` | `Genesis Markdown/60-UI/News.md` | ◐ | src/genesis/news/__init__.py, ui/src/workspace/panels/news.tsx, tests/research/test_news.py, ui/src/workspace/panels/status.tsx, ui/src/api/client.ts, src/genesis/news/store.py, src/genesis/news/collect.py, src/genesis/server/news_routes.py, src/genesis/automation/actions.py |
| `Nodes` | `Genesis Markdown/60-UI/Nodes.md` | ● | src/genesis/notebook/links.py, src/genesis/server/notebook_routes.py, ui/src/workspace/panels/nodes.tsx, src/genesis/notebook/__init__.py, tests/test_notebook.py |
| `Notebook` | `Genesis Markdown/60-UI/Notebook.md` | ● | src/genesis/notebook/vault.py, src/genesis/notebook/links.py, src/genesis/server/notebook_routes.py, ui/src/workspace/panels/notebook.tsx, src/genesis/notebook/__init__.py, tests/test_notebook.py |
| `Research Canvas` | `Genesis Markdown/60-UI/Research Canvas.md` | ● | src/genesis/research/canvas.py, src/genesis/memory/graph.py, src/genesis/server/canvas_routes.py, ui/src/views/ResearchCanvas.tsx, ui/src/graph/nodes/EntityNode.tsx, tests/research/test_canvas.py |
| `Screener` | `Genesis Markdown/60-UI/Screener.md` | ◐ | ui/src/workspace/panels/screener.tsx, ui/src/workspace/panels/ask.tsx, ui/src/workspace/modules.ts, ui/src/api/client.ts, ui/src/App.tsx, src/genesis/server/watchlist_routes.py, src/genesis/server/app.py, tests/test_screener.py |
| `System Map` | `Genesis Markdown/60-UI/System Map.md` | ● | ui/src/views/SystemMap.tsx, ui/src/shell/catalogue.ts |
| `Task Manager` | `Genesis Markdown/60-UI/Task Manager.md` | ● | ui/src/workspace/panels/tasks.tsx, ui/src/workspace/modules.ts |
| `Terminal` | `Genesis Markdown/60-UI/Terminal.md` | ◐ | ui/src/workspace/dock.ts, tests/test_tool_routes.py, src/genesis/server/tool_routes.py, ui/src/shell/catalogue.ts, ui/src/workspace/modules.ts, ui/src/workspace/panels/tool.tsx, ui/src/workspace/panels/watchlist.tsx, src/genesis/mcp/build.py, ui/src/workspace/panels/ask.tsx, ui/src/workspace/panels/help.tsx, ui/src/shell/CommandBar.tsx, src/genesis/server/conversation_routes.py |
| `UI Stack` | `Genesis Markdown/60-UI/UI Stack.md` | ◐ | ui/package.json, ui/vite.config.ts, ui/src/styles/tokens.css, ui/src/transport/transport.ts, ui/src/transport/live.ts, ui/src/lib/format.ts, ui/src/components/SurfaceBoundary.tsx, ui/src/components/TapToSpeak.tsx, src/genesis/server/app.py, src/genesis/commands.py, tests/test_server.py, tests/test_commands.py, ui/src/main.tsx, ui/src/App.tsx |
| `Voice UX` | `Genesis Markdown/60-UI/Voice UX.md` | ● | src/genesis/voice/speech.py, src/genesis/voice/earcons.py, src/genesis/voice/policy.py, src/genesis/orchestrator/verbosity.py, tests/test_earcons.py, tests/test_speech.py, tests/test_speech_dates.py, tests/test_speech_policy.py, tests/test_verbosity.py, src/genesis/server/voice_routes.py, ui/src/components/TapToSpeak.tsx, ui/src/shell/CommandBar.tsx |
| `Widget Catalog` | `Genesis Markdown/60-UI/Widget Catalog.md` | ◐ | ui/src/components/EventStream.tsx, ui/src/components/SafetyFloor.tsx, ui/src/components/KillSwitch.tsx, ui/src/views/MemoryFabric.tsx, ui/src/views/ExecutionPath.tsx, ui/src/workspace/panels/heatmap.tsx, src/genesis/marketdata/heatmap.py, ui/src/workspace/panels/performance.tsx, src/genesis/marketdata/performance.py, ui/src/workspace/panels/trade.tsx, ui/src/api/useExecState.ts, ui/src/components/charts/PriceChart.tsx, ui/src/workspace/panels.tsx, ui/src/workspace/panels/browser.tsx |
| `Workspaces` | `Genesis Markdown/60-UI/Workspaces.md` | ● | ui/src/shell/pages.ts, ui/src/shell/TopBar.tsx, ui/src/shell/CommandBar.tsx, ui/src/workspace/modules.ts, ui/src/workspace/Workspace.tsx, ui/src/workspace/panels.tsx, ui/src/workspace/context.tsx, ui/src/workspace/dock.ts, ui/src/App.tsx, ui/src/workspace/panels/research.tsx |

## 70-Schemas

| Note | Path | | Implemented by |
|---|---|---|---|
| `Conversation Store` | `Genesis Markdown/70-Schemas/Conversation Store.md` | ◐ | src/genesis/memory/conversations.py, tests/memory/test_conversations.py, src/genesis/server/conversation_routes.py |
| `Data Model Overview` | `Genesis Markdown/70-Schemas/Data Model Overview.md` | ○ |  |
| `Event Schema` | `Genesis Markdown/70-Schemas/Event Schema.md` | ◐ | ui/src/types/events.ts, ui/src/components/EventStream.tsx |
| `Idea Schema` | `Genesis Markdown/70-Schemas/Idea Schema.md` | ◐ | src/genesis/news/ideas.py, ui/src/workspace/panels/trade-ideas.tsx, tests/news/test_ideas.py, src/genesis/research/setup.py, tests/research/test_setup.py |
| `Markup Spec Schema` | `Genesis Markdown/70-Schemas/Markup Spec Schema.md` | ● | src/genesis/charting/spec.py, tests/charting/test_spec.py, ui/src/components/charts/drawings.ts |
| `Order And Fill Schema` | `Genesis Markdown/70-Schemas/Order And Fill Schema.md` | ◐ | src/genesis/memory/ledger.py, src/genesis/execution/order_manager.py, src/genesis/execution/approval.py |
| `Strategy Schema` | `Genesis Markdown/70-Schemas/Strategy Schema.md` | ◐ | src/genesis/backtest/strategy.py |
| `Trade Journal Schema` | `Genesis Markdown/70-Schemas/Trade Journal Schema.md` | ● | src/genesis/journal/schema.py, src/genesis/journal/store.py, tests/journal/test_schema.py, tests/journal/test_store.py |
| `Watchlist Store` | `Genesis Markdown/70-Schemas/Watchlist Store.md` | ● | src/genesis/watchlist/__init__.py, src/genesis/watchlist/store.py, ui/src/workspace/panels/watchlist.tsx, src/genesis/server/watchlist_routes.py, src/genesis/marketdata/quotes.py, src/genesis/commands.py, tests/test_watchlist.py |
| `Workflow Schema` | `Genesis Markdown/70-Schemas/Workflow Schema.md` | ● | src/genesis/automation/workflow.py, src/genesis/automation/store.py, src/genesis/automation/actions.py, ui/src/components/automation/wiring.check.ts, ui/src/components/automation/wiring.ts, tests/automation/test_workflow.py |

## 80-Repos

| Note | Path | | Implemented by |
|---|---|---|---|
| `Repo Map` | `Genesis Markdown/80-Repos/Repo Map.md` |  |  |
| `Repo — Gensis Terminal Official` | `Genesis Markdown/80-Repos/Repo — Gensis Terminal Official.md` |  |  |
| `Repo — Lithium Codebase` | `Genesis Markdown/80-Repos/Repo — Lithium Codebase.md` |  |  |
| `Repo — gensis-agents` | `Genesis Markdown/80-Repos/Repo — gensis-agents.md` |  |  |
| `Repo — jarvis` | `Genesis Markdown/80-Repos/Repo — jarvis.md` |  |  |
| `Trading Corpus Index` | `Genesis Markdown/80-Repos/Trading Corpus Index.md` |  |  |

## 90-Graph

| Note | Path | | Implemented by |
|---|---|---|---|
| `Connection Graph` | `Genesis Markdown/90-Graph/Connection Graph.md` | ● | scripts/build_connection_graph.py |
| `Module AG — Agents` | `Genesis Markdown/90-Graph/Modules/Module AG — Agents.md` |  |  |
| `Module AI — Ask Genesis` | `Genesis Markdown/90-Graph/Modules/Module AI — Ask Genesis.md` |  |  |
| `Module AP — Approval` | `Genesis Markdown/90-Graph/Modules/Module AP — Approval.md` |  |  |
| `Module BM — Body map` | `Genesis Markdown/90-Graph/Modules/Module BM — Body map.md` |  |  |
| `Module CA — Canvas` | `Genesis Markdown/90-Graph/Modules/Module CA — Canvas.md` |  |  |
| `Module CD — Running cadences` | `Genesis Markdown/90-Graph/Modules/Module CD — Running cadences.md` |  |  |
| `Module CH — Chart` | `Genesis Markdown/90-Graph/Modules/Module CH — Chart.md` |  |  |
| `Module CM — Capabilities` | `Genesis Markdown/90-Graph/Modules/Module CM — Capabilities.md` |  |  |
| `Module CO — Company` | `Genesis Markdown/90-Graph/Modules/Module CO — Company.md` |  |  |
| `Module CR — Candle Ranges` | `Genesis Markdown/90-Graph/Modules/Module CR — Candle Ranges.md` |  |  |
| `Module CV — Coverage` | `Genesis Markdown/90-Graph/Modules/Module CV — Coverage.md` |  |  |
| `Module DA — Data` | `Genesis Markdown/90-Graph/Modules/Module DA — Data.md` |  |  |
| `Module EQ — Equity` | `Genesis Markdown/90-Graph/Modules/Module EQ — Equity.md` |  |  |
| `Module EV — Events` | `Genesis Markdown/90-Graph/Modules/Module EV — Events.md` |  |  |
| `Module FD — Feed` | `Genesis Markdown/90-Graph/Modules/Module FD — Feed.md` |  |  |
| `Module HI — History` | `Genesis Markdown/90-Graph/Modules/Module HI — History.md` |  |  |
| `Module HLP — Help` | `Genesis Markdown/90-Graph/Modules/Module HLP — Help.md` |  |  |
| `Module HLT — Status` | `Genesis Markdown/90-Graph/Modules/Module HLT — Status.md` |  |  |
| `Module HM — Heatmap` | `Genesis Markdown/90-Graph/Modules/Module HM — Heatmap.md` |  |  |
| `Module IN — Instrument` | `Genesis Markdown/90-Graph/Modules/Module IN — Instrument.md` |  |  |
| `Module IS — Inspector` | `Genesis Markdown/90-Graph/Modules/Module IS — Inspector.md` |  |  |
| `Module JE — Entries` | `Genesis Markdown/90-Graph/Modules/Module JE — Entries.md` |  |  |
| `Module JG — Graph` | `Genesis Markdown/90-Graph/Modules/Module JG — Graph.md` |  |  |
| `Module JM — Marks` | `Genesis Markdown/90-Graph/Modules/Module JM — Marks.md` |  |  |
| `Module JP — Patterns` | `Genesis Markdown/90-Graph/Modules/Module JP — Patterns.md` |  |  |
| `Module MK — Markup` | `Genesis Markdown/90-Graph/Modules/Module MK — Markup.md` |  |  |
| `Module MM — Memory` | `Genesis Markdown/90-Graph/Modules/Module MM — Memory.md` |  |  |
| `Module MT — Model tiers` | `Genesis Markdown/90-Graph/Modules/Module MT — Model tiers.md` |  |  |
| `Module NOD — Nodes` | `Genesis Markdown/90-Graph/Modules/Module NOD — Nodes.md` |  |  |
| `Module NOT — Notebook` | `Genesis Markdown/90-Graph/Modules/Module NOT — Notebook.md` |  |  |
| `Module PFM — Performance` | `Genesis Markdown/90-Graph/Modules/Module PFM — Performance.md` |  |  |
| `Module RD — Research` | `Genesis Markdown/90-Graph/Modules/Module RD — Research.md` |  |  |
| `Module RN — Note` | `Genesis Markdown/90-Graph/Modules/Module RN — Note.md` |  |  |
| `Module SG — Strategy` | `Genesis Markdown/90-Graph/Modules/Module SG — Strategy.md` |  |  |
| `Module SR — Series` | `Genesis Markdown/90-Graph/Modules/Module SR — Series.md` |  |  |
| `Module ST — Statistics` | `Genesis Markdown/90-Graph/Modules/Module ST — Statistics.md` |  |  |
| `Module TC — Trace` | `Genesis Markdown/90-Graph/Modules/Module TC — Trace.md` |  |  |
| `Module TM — Tasks` | `Genesis Markdown/90-Graph/Modules/Module TM — Tasks.md` |  |  |
| `Module TR — Trades` | `Genesis Markdown/90-Graph/Modules/Module TR — Trades.md` |  |  |
| `Module TS — Tools` | `Genesis Markdown/90-Graph/Modules/Module TS — Tools.md` |  |  |
| `Module TV — TradingView` | `Genesis Markdown/90-Graph/Modules/Module TV — TradingView.md` |  |  |
| `Module VO — Voice` | `Genesis Markdown/90-Graph/Modules/Module VO — Voice.md` |  |  |
| `Module WB — Workflow builder` | `Genesis Markdown/90-Graph/Modules/Module WB — Workflow builder.md` |  |  |
| `Module WL — Watchlist` | `Genesis Markdown/90-Graph/Modules/Module WL — Watchlist.md` |  |  |
| `Module XP — Execution path` | `Genesis Markdown/90-Graph/Modules/Module XP — Execution path.md` |  |  |
| `Tool — backtesting` | `Genesis Markdown/90-Graph/Tools/Tool — backtesting.md` |  |  |
| `Tool — calendar` | `Genesis Markdown/90-Graph/Tools/Tool — calendar.md` |  |  |
| `Tool — convert` | `Genesis Markdown/90-Graph/Tools/Tool — convert.md` |  |  |
| `Tool — empyrical` | `Genesis Markdown/90-Graph/Tools/Tool — empyrical.md` |  |  |
| `Tool — filings` | `Genesis Markdown/90-Graph/Tools/Tool — filings.md` |  |  |
| `Tool — financial-datasets` | `Genesis Markdown/90-Graph/Tools/Tool — financial-datasets.md` |  |  |
| `Tool — genesis-backtest` | `Genesis Markdown/90-Graph/Tools/Tool — genesis-backtest.md` |  |  |
| `Tool — genesis-charting` | `Genesis Markdown/90-Graph/Tools/Tool — genesis-charting.md` |  |  |
| `Tool — genesis-execution` | `Genesis Markdown/90-Graph/Tools/Tool — genesis-execution.md` |  |  |
| `Tool — macro` | `Genesis Markdown/90-Graph/Tools/Tool — macro.md` |  |  |
| `Tool — market-data` | `Genesis Markdown/90-Graph/Tools/Tool — market-data.md` |  |  |
| `Tool — mcp-market-data` | `Genesis Markdown/90-Graph/Tools/Tool — mcp-market-data.md` |  |  |
| `Tool — mcp` | `Genesis Markdown/90-Graph/Tools/Tool — mcp.md` |  |  |
| `Tool — news` | `Genesis Markdown/90-Graph/Tools/Tool — news.md` |  |  |
| `Tool — obsidian` | `Genesis Markdown/90-Graph/Tools/Tool — obsidian.md` |  |  |
| `Tool — options` | `Genesis Markdown/90-Graph/Tools/Tool — options.md` |  |  |
| `Tool — papers` | `Genesis Markdown/90-Graph/Tools/Tool — papers.md` |  |  |
| `Tool — pine` | `Genesis Markdown/90-Graph/Tools/Tool — pine.md` |  |  |
| `Tool — pyfolio` | `Genesis Markdown/90-Graph/Tools/Tool — pyfolio.md` |  |  |
| `Tool — pypfopt` | `Genesis Markdown/90-Graph/Tools/Tool — pypfopt.md` |  |  |
| `Tool — qlib` | `Genesis Markdown/90-Graph/Tools/Tool — qlib.md` |  |  |
| `Tool — research` | `Genesis Markdown/90-Graph/Tools/Tool — research.md` |  |  |
| `Tool — riskfolio` | `Genesis Markdown/90-Graph/Tools/Tool — riskfolio.md` |  |  |
| `Tool — sentiment` | `Genesis Markdown/90-Graph/Tools/Tool — sentiment.md` |  |  |
| `Tool — strategy` | `Genesis Markdown/90-Graph/Tools/Tool — strategy.md` |  |  |
| `Tool — system` | `Genesis Markdown/90-Graph/Tools/Tool — system.md` |  |  |
| `Tool — time` | `Genesis Markdown/90-Graph/Tools/Tool — time.md` |  |  |
| `Tool — tradingview` | `Genesis Markdown/90-Graph/Tools/Tool — tradingview.md` |  |  |
| `Tool — web` | `Genesis Markdown/90-Graph/Tools/Tool — web.md` |  |  |

## (root)

| Note | Path | | Implemented by |
|---|---|---|---|
| `ARCHITECTURE` | `Genesis Markdown/ARCHITECTURE.md` |  |  |
| `Agent Function Map` | `Genesis Markdown/Agent Function Map.md` |  |  |
| `Biological Design for Gensis Orchistrator` | `Genesis Markdown/Biological Design for Gensis Orchistrator.md` |  |  |
| `CLAUDE-DESIGN-PROMPT` | `Genesis Markdown/CLAUDE-DESIGN-PROMPT.md` |  |  |
| `CURRENTISSUES` | `Genesis Markdown/CURRENTISSUES.md` |  |  |
| `Genesis Agent — Home` | `Genesis Markdown/Genesis Agent — Home.md` |  | src/genesis/__init__.py |
| `Genesis Commands` | `Genesis Markdown/Genesis Commands.md` |  |  |
| `IBKR` | `Genesis Markdown/IBKR.md` |  |  |
| `Market Analyst Bugs` | `Genesis Markdown/Market Analyst Bugs.md` |  |  |
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
