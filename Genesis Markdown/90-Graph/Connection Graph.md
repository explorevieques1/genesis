---
title: Connection Graph
tags: [graph, moc]
status: built
implemented_by: [scripts/build_connection_graph.py]
---

# Connection Graph

How agents, tools and UI modules connect. **Generated** by
`python3 scripts/build_connection_graph.py` — do not edit these notes by hand;
change `ui/src/workspace/modules.ts`, an agent's `## Tools` section, or
`MODULE_LINKS` in the script, then re-run.

Open the graph view and filter with `path:90-Graph OR path:20-Agents` to see
only the connection graph. Colours: modules blue, tools amber, agents green.

`memory.*` and `taskbus.*` are left out on purpose: almost every agent holds
them, so they would pull the whole graph into one hub. See [[Memory Fabric]]
and [[Task Bus]].

## Modules (43)

- [[Module CH — Chart]]
- [[Module SR — Series]]
- [[Module WL — Watchlist]]
- [[Module CR — Candle Ranges]]
- [[Module IN — Instrument]]
- [[Module CV — Coverage]]
- [[Module MK — Markup]]
- [[Module HM — Heatmap]]
- [[Module PFM — Performance]]
- [[Module TV — TradingView]]
- [[Module SG — Strategy]]
- [[Module EQ — Equity]]
- [[Module ST — Statistics]]
- [[Module TR — Trades]]
- [[Module HI — History]]
- [[Module CA — Canvas]]
- [[Module RD — Research]]
- [[Module RN — Note]]
- [[Module CO — Company]]
- [[Module TS — Tools]]
- [[Module JG — Graph]]
- [[Module JE — Entries]]
- [[Module JM — Marks]]
- [[Module JP — Patterns]]
- [[Module NOT — Notebook]]
- [[Module NOD — Nodes]]
- [[Module CD — Running cadences]]
- [[Module WB — Workflow builder]]
- [[Module BM — Body map]]
- [[Module IS — Inspector]]
- [[Module EV — Events]]
- [[Module MM — Memory]]
- [[Module XP — Execution path]]
- [[Module TC — Trace]]
- [[Module CM — Capabilities]]
- [[Module AI — Ask Genesis]]
- [[Module HLT — Status]]
- [[Module TM — Tasks]]
- [[Module HLP — Help]]
- [[Module VO — Voice]]
- [[Module AG — Agents]]
- [[Module DA — Data]]
- [[Module AP — Approval]]
- [[Module MT — Model tiers]]

## Tools (29)

- [[Tool — backtesting]]
- [[Tool — calendar]]
- [[Tool — convert]]
- [[Tool — empyrical]]
- [[Tool — filings]]
- [[Tool — financial-datasets]]
- [[Tool — genesis-backtest]]
- [[Tool — genesis-charting]]
- [[Tool — genesis-execution]]
- [[Tool — macro]]
- [[Tool — market-data]]
- [[Tool — mcp]]
- [[Tool — mcp-market-data]]
- [[Tool — news]]
- [[Tool — obsidian]]
- [[Tool — options]]
- [[Tool — papers]]
- [[Tool — pine]]
- [[Tool — pyfolio]]
- [[Tool — pypfopt]]
- [[Tool — qlib]]
- [[Tool — research]]
- [[Tool — riskfolio]]
- [[Tool — sentiment]]
- [[Tool — strategy]]
- [[Tool — system]]
- [[Tool — time]]
- [[Tool — tradingview]]
- [[Tool — web]]

## Agents with no module yet (14)

Reachable only through Ask Genesis or the orchestrator — parity-rule gaps
([[Operating Model]]).

- [[Agent — Backtest Vs Live Drift]] (built)
- [[Agent — Broker Adapter]] (spec)
- [[Agent — Execution Quality]] (spec)
- [[Agent — ML Signal]] (optional)
- [[Agent — News And Catalyst]] (spec)
- [[Agent — Optimizer]] (spec)
- [[Agent — Performance Analyst]] (built)
- [[Agent — Portfolio And Allocation]] (spec)
- [[Agent — Position And PnL Accountant]] (spec)
- [[Agent — Prop Firm Guard]] (spec)
- [[Agent — Regime And Correlation]] (spec)
- [[Agent — Screener]] (spec)
- [[Agent — Sentiment]] (spec)
- [[Agent — Strategy Author]] (spec)

## Related

[[Agent Index]] · [[MCP Server Catalog]] · [[Workspaces]]
