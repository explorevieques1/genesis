---
title: Agent Index
tags: [moc, agent]
status: spec
implemented_by: []
---

# Agent Index

The full fleet — **30 agents in 5 families**. Every agent follows [[Agent Contract]].

Cadence key: `D` on-demand · `O` market-open · `C` market-closed · `X` cron · `E` event

---

## 🔍 [[Research Family]] — 7 agents

| Agent | Job | Cadence | Tier |
|---|---|---|---|
| [[Agent — Market Analyst]] | Top-down regime read: indices, breadth, sectors, rates, vol | X D | large |
| [[Agent — News And Catalyst]] | Headlines, filings, earnings, econ prints → tagged catalysts | O E | large |
| [[Agent — Sentiment]] | Social, options flow, put/call, funding; divergence detection | O | small |
| [[Agent — Fundamental]] | Valuation, growth, margins, guidance, insiders; factor screens | C | large |
| [[Agent — Screener]] | Runs saved scans across the universe | O | small |
| [[Agent — Idea Synthesizer]] | Fuses everything into ranked, structured trade ideas | O X E | large |
| [[Agent — Regime And Correlation]] | Rolling vol/correlation regimes; flags broken assumptions | C | large |

## 📈 [[Charting Family]] — 4 agents

| Agent | Job | Cadence | Tier |
|---|---|---|---|
| [[Agent — Chart Markup]] | Levels, zones, structure → [[Markup Spec]] + rendered chart | D E | large |
| [[Agent — Pattern Recognition]] | Classify structure and patterns; vision + rule cross-check | D | vision |
| [[Agent — Multi Timeframe]] | 4–5 timeframes, one composite, alignment score | D | vision |
| [[Agent — Level Watcher]] | Live watch on every level in every active spec | O E | none |

## 🧪 [[Strategy Family]] — 7 agents

| Agent | Job | Cadence | Tier |
|---|---|---|---|
| [[Agent — Strategy Author]] | Plain English → testable strategy object; PineScript output | D | large |
| [[Agent — Backtest Runner]] | Run history, return metrics + equity curve + trades | C D | none |
| [[Agent — Optimizer]] | Walk-forward parameter search with overfit guards | C | none |
| [[Agent — Risk Metrics]] | Canonical Sharpe/Sortino/Calmar/DD/tail for any curve | D | none |
| [[Agent — Portfolio And Allocation]] | Sizing and weights: risk parity, HRP, CVaR, Kelly cap | D E | none |
| [[Agent — ML Signal]] | Feature pipeline + model retrain; advisory only | C | large |
| [[Agent — Prop Firm Guard]] | Encodes FTMO/TopStep/Apex rule sets as hard constraints | O E | none |

## ⚡ [[Execution Family]] — 6 agents

| Agent | Job | Cadence | Tier |
|---|---|---|---|
| [[Pre-Trade Risk Engine]] | **The gate.** Every order, no exceptions | E | none |
| [[Agent — Order Manager]] | Place, modify, cancel; brackets, trailing, partials, OCO | E | none |
| [[Agent — Position And PnL Accountant]] | Real-time positions, P&L, exposure. Source of truth. | O E | none |
| [[Agent — Broker Adapter]] | Normalizes brokers behind one interface; paper == live path | E | none |
| [[Agent — Execution Quality]] | Slippage vs. arrival, fill rate, fees → journal | O E | none |
| [[Kill Switch]] | Cancel-all, optional flatten, mode → halt. LLM-free. | E | none |

## 📓 [[Journal Family]] — 6 agents

| Agent | Job | Cadence | Tier |
|---|---|---|---|
| [[Agent — Trade Journal]] | Every fill → a vault note with charts, thesis, R, tags | E | small |
| [[Agent — Performance Analyst]] | Tearsheets; edge by setup/session/symbol; weekly review | X C | large |
| [[Agent — Insight Miner]] | Mines journal + ledger for behavioural patterns → lessons | C | large |
| [[Agent — Backtest Vs Live Drift]] | Live vs. backtest expectation; alerts on divergence | C | large |
| [[Agent — Watchdog]] | Heartbeats everything; reconnects; reports | O C | small |
| [[Agent — Digest]] | Morning brief, evening recap; keeps memory from bloating | X | small |

---

## Cross-cutting views

### By tier ([[LLM Model Tiers]])
- **none (deterministic):** 10 agents — all of execution, plus backtest/metrics/allocation/level-watch. *Nothing safety-critical runs on an LLM.*
- **small:** 5 · **large:** 12 · **vision:** 2 · **embedding:** used by [[Memory Consolidation]]

### By family risk
- 🔴 **Execution family** touches money → [[Safety Invariants]] apply in full
- 🟡 **Strategy family** produces things that *become* orders → [[Paper To Live Promotion]]
- 🟢 **Research / Charting / Journal** cannot spend money

### Build sequence
Phase 4 → Analyst, News, Screener, Chart Markup, Idea Synthesizer
Phase 5 → Strategy Author, Backtest Runner, Risk Metrics, Optimizer
Phase 7 → Accountant, Risk Engine, Kill Switch, Broker Adapter, Order Manager
Phase 8 → Trade Journal, Performance Analyst, Insight Miner, Drift
Phase 10 → the rest
See [[Build Order]].

### Dataview (if the plugin is enabled)

```dataview
TABLE family, cadence, tier, status
FROM #agent
WHERE file.folder != "20-Agents"
SORT family ASC, file.name ASC
```

## Related

[[Agent Contract]] · [[Task Bus]] · [[Daemon And Cadence]] · [[MCP Gateway]] · [[System Overview]]
