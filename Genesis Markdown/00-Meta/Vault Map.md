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

**97 notes.** Status: ○ spec · ◐ building · ● built


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
| `Approval Modes` | `Genesis Markdown/10-Architecture/Approval Modes.md` | ○ |  |
| `Charting Engine` | `Genesis Markdown/10-Architecture/Charting Engine.md` | ○ |  |
| `Config And Secrets` | `Genesis Markdown/10-Architecture/Config And Secrets.md` | ◐ | [src/genesis/config.py, src/genesis/default_config.yaml, tests/test_config.py] |
| `Daemon And Cadence` | `Genesis Markdown/10-Architecture/Daemon And Cadence.md` | ◐ | [src/genesis/daemon/daemon.py, src/genesis/daemon/calendar.py, src/genesis/daemon/scheduler.py, src/genesis/daemon/supervisor.py, tests/daemon/] |
| `Error Handling And Degradation` | `Genesis Markdown/10-Architecture/Error Handling And Degradation.md` | ◐ | [src/genesis/errors.py, src/genesis/bus/bus.py] |
| `LLM Model Tiers` | `Genesis Markdown/10-Architecture/LLM Model Tiers.md` | ○ |  |
| `Market Data Sources` | `Genesis Markdown/10-Architecture/Market Data Sources.md` | ○ |  |
| `Markup Spec` | `Genesis Markdown/10-Architecture/Markup Spec.md` | ○ |  |
| `Observability` | `Genesis Markdown/10-Architecture/Observability.md` | ◐ | [src/genesis/observability.py, src/genesis/cli.py, tests/test_observability.py] |
| `Orchestrator Tools` | `Genesis Markdown/10-Architecture/Orchestrator Tools.md` | ○ |  |
| `Orchestrator` | `Genesis Markdown/10-Architecture/Orchestrator.md` | ○ |  |
| `System Overview` | `Genesis Markdown/10-Architecture/System Overview.md` | ○ |  |
| `Task Bus` | `Genesis Markdown/10-Architecture/Task Bus.md` | ◐ | [src/genesis/bus/bus.py, src/genesis/bus/task.py, tests/bus/test_task_bus.py] |
| `Voice Stack` | `Genesis Markdown/10-Architecture/Voice Stack.md` | ○ |  |

## 20-Agents

| Note | Path | | Implemented by |
|---|---|---|---|
| `Agent Index` | `Genesis Markdown/20-Agents/Agent Index.md` | ○ |  |
| `Agent — Chart Markup` | `Genesis Markdown/20-Agents/Charting/Agent — Chart Markup.md` | ○ |  |
| `Agent — Level Watcher` | `Genesis Markdown/20-Agents/Charting/Agent — Level Watcher.md` | ○ |  |
| `Agent — Multi Timeframe` | `Genesis Markdown/20-Agents/Charting/Agent — Multi Timeframe.md` | ○ |  |
| `Agent — Pattern Recognition` | `Genesis Markdown/20-Agents/Charting/Agent — Pattern Recognition.md` | ○ |  |
| `Charting Family` | `Genesis Markdown/20-Agents/Charting/Charting Family.md` | ○ |  |
| `Agent — Broker Adapter` | `Genesis Markdown/20-Agents/Execution/Agent — Broker Adapter.md` | ○ |  |
| `Agent — Execution Quality` | `Genesis Markdown/20-Agents/Execution/Agent — Execution Quality.md` | ○ |  |
| `Agent — Order Manager` | `Genesis Markdown/20-Agents/Execution/Agent — Order Manager.md` | ○ |  |
| `Agent — Position And PnL Accountant` | `Genesis Markdown/20-Agents/Execution/Agent — Position And PnL Accountant.md` | ○ |  |
| `Execution Family` | `Genesis Markdown/20-Agents/Execution/Execution Family.md` | ○ |  |
| `Futures Broker Options` | `Genesis Markdown/20-Agents/Execution/Futures Broker Options.md` | ○ |  |
| `Agent — Backtest Vs Live Drift` | `Genesis Markdown/20-Agents/Journal/Agent — Backtest Vs Live Drift.md` | ○ |  |
| `Agent — Digest` | `Genesis Markdown/20-Agents/Journal/Agent — Digest.md` | ○ |  |
| `Agent — Insight Miner` | `Genesis Markdown/20-Agents/Journal/Agent — Insight Miner.md` | ○ |  |
| `Agent — Performance Analyst` | `Genesis Markdown/20-Agents/Journal/Agent — Performance Analyst.md` | ○ |  |
| `Agent — Trade Journal` | `Genesis Markdown/20-Agents/Journal/Agent — Trade Journal.md` | ○ |  |
| `Agent — Watchdog` | `Genesis Markdown/20-Agents/Journal/Agent — Watchdog.md` | ○ |  |
| `Journal Family` | `Genesis Markdown/20-Agents/Journal/Journal Family.md` | ○ |  |
| `Agent — Fundamental` | `Genesis Markdown/20-Agents/Research/Agent — Fundamental.md` | ○ |  |
| `Agent — Idea Synthesizer` | `Genesis Markdown/20-Agents/Research/Agent — Idea Synthesizer.md` | ○ |  |
| `Agent — Market Analyst` | `Genesis Markdown/20-Agents/Research/Agent — Market Analyst.md` | ○ |  |
| `Agent — News And Catalyst` | `Genesis Markdown/20-Agents/Research/Agent — News And Catalyst.md` | ○ |  |
| `Agent — Regime And Correlation` | `Genesis Markdown/20-Agents/Research/Agent — Regime And Correlation.md` | ○ |  |
| `Agent — Screener` | `Genesis Markdown/20-Agents/Research/Agent — Screener.md` | ○ |  |
| `Agent — Sentiment` | `Genesis Markdown/20-Agents/Research/Agent — Sentiment.md` | ○ |  |
| `Research Family` | `Genesis Markdown/20-Agents/Research/Research Family.md` | ○ |  |
| `Agent — Backtest Runner` | `Genesis Markdown/20-Agents/Strategy/Agent — Backtest Runner.md` | ○ |  |
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
| `MCP Gateway` | `Genesis Markdown/30-MCP/MCP Gateway.md` | ○ |  |
| `MCP Server Catalog` | `Genesis Markdown/30-MCP/MCP Server Catalog.md` | ○ |  |
| `genesis-backtest-mcp` | `Genesis Markdown/30-MCP/genesis-backtest-mcp.md` | ○ |  |
| `genesis-charting-mcp` | `Genesis Markdown/30-MCP/genesis-charting-mcp.md` | ○ |  |
| `genesis-execution-mcp` | `Genesis Markdown/30-MCP/genesis-execution-mcp.md` | ○ |  |
| `genesis-memory-mcp` | `Genesis Markdown/30-MCP/genesis-memory-mcp.md` | ○ |  |
| `genesis-tradingview-mcp` | `Genesis Markdown/30-MCP/genesis-tradingview-mcp.md` | ○ |  |

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
| `Working Memory` | `Genesis Markdown/40-Memory/Working Memory.md` | ○ |  |

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
| `Dashboard` | `Genesis Markdown/60-UI/Dashboard.md` | ○ |  |
| `Desktop Shell` | `Genesis Markdown/60-UI/Desktop Shell.md` |  |  |
| `Voice UX` | `Genesis Markdown/60-UI/Voice UX.md` | ○ |  |
| `Widget Catalog` | `Genesis Markdown/60-UI/Widget Catalog.md` | ○ |  |

## 70-Schemas

| Note | Path | | Implemented by |
|---|---|---|---|
| `Data Model Overview` | `Genesis Markdown/70-Schemas/Data Model Overview.md` | ○ |  |
| `Event Schema` | `Genesis Markdown/70-Schemas/Event Schema.md` | ○ |  |
| `Idea Schema` | `Genesis Markdown/70-Schemas/Idea Schema.md` | ○ |  |
| `Markup Spec Schema` | `Genesis Markdown/70-Schemas/Markup Spec Schema.md` | ○ |  |
| `Order And Fill Schema` | `Genesis Markdown/70-Schemas/Order And Fill Schema.md` | ◐ | [src/genesis/memory/ledger.py] |
| `Strategy Schema` | `Genesis Markdown/70-Schemas/Strategy Schema.md` | ○ |  |
| `Trade Journal Schema` | `Genesis Markdown/70-Schemas/Trade Journal Schema.md` | ○ |  |

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

---

## Build status

```dataview
TABLE status, implemented_by
FROM "10-Architecture" OR "20-Agents" OR "30-MCP" OR "40-Memory" OR "50-Risk" OR "60-UI" OR "70-Schemas"
WHERE status != null
SORT status ASC, file.name ASC
```
