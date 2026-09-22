---
title: Agent Index
tags: [moc, agent]
status: building
implemented_by: [ui/src/data/roster.ts, evals/corpora/requests.py, evals/test_request_coverage.py, src/genesis/server/fleet.py]
---

# Agent Index

The full fleet — **32 agents in 5 families**. Every agent follows [[Agent Contract]].

Cadence key: `D` on-demand · `O` market-open · `C` market-closed · `X` cron · `E` event

---

## 🔍 [[Research Family]] — 9 agents

| Agent | Job | Cadence | Tier |
|---|---|---|---|
| [[Agent — Topic Researcher]] | Deep web research on a subject, not a symbol; saves a cited note | D | large |
| [[Agent — Market Analyst]] | Top-down regime read: indices, breadth, sectors, rates, vol | X D | large |
| [[Agent — News And Catalyst]] | Headlines, filings, earnings, econ prints → tagged catalysts | O E | large |
| [[Agent — News Collector]] | Gathers yfinance headlines into `news.db` for [[News]] — reflex, no model | O C D | none |
| [[Agent — Sentiment]] | Social, options flow, put/call, funding; divergence detection | O | small |
| [[Agent — Fundamental]] | Valuation, growth, margins, guidance, insiders; factor screens | C | large |
| [[Agent — Screener]] | Runs saved scans across the universe | O | small |
| [[Agent — Idea Synthesizer]] | Fuses everything into ranked, structured trade ideas | O X E | large |
| [[Agent — Regime And Correlation]] | Rolling vol/correlation regimes; flags broken assumptions | C | large |
| [[Agent — Session Plan]] | Your ideas in; a ranked plan out, sized by the risk gate | D | none |

## 📈 [[Charting Family]] — 5 agents

| Agent | Job | Cadence | Tier |
|---|---|---|---|
| [[Agent — Chart Markup]] | Levels, zones, structure → [[Markup Spec]] + rendered chart | D E | large |
| [[Agent — Pattern Recognition]] | Classify structure and patterns; vision + rule cross-check | D | vision |
| [[Agent — Multi Timeframe]] | 4–5 timeframes, one composite, alignment score | D E | vision |
| [[Agent — Level Watcher]] | Live watch on every level in every active spec | O E | none |
| [[Agent — Data Viz]] | Non-price charts: sector rankings, macro series, correlation | D | large |

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
| [[Agent — Watchdog]] | Heartbeats everything; reconnects; reports | O C E | none |
| [[Agent — Digest]] | Morning brief, evening recap; keeps memory from bloating | X | small |

---

## Cross-cutting views

### By tier ([[LLM Model Tiers]])
- **none (deterministic):** 13 agents — all six of execution, the five `tier: none`
  strategy agents (backtest, optimizer, metrics, allocation, prop-firm guard),
  plus [[Agent — Level Watcher]] and [[Agent — Watchdog]].
  *Nothing safety-critical runs on an LLM.*
- **small:** 4 · **large:** 12 · **vision:** 2 · **embedding:** used by [[Memory Consolidation]]

[[Agent — Watchdog]] moved from `small` to `none` when it was built: the component
whose answer to *"is the system healthy"* has to be believed is the last one that
should depend on a language model being reachable. Every verdict it makes is a
comparison.

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

### Built so far — 14 of 32, as of 2026-09-06

**[[Charting Family]], all five.** Chart Markup, Pattern Recognition, Multi
Timeframe, Level Watcher, Data Viz. Data Viz is a sixth Phase-4 agent and a
deliberate deviation — see [[Build Order]].

**[[Journal Family]], all six**, built out of order (Phase 8 during Phase 4).
The reason is in [[Journal Family]]: history only accumulates if something is
writing it down, so the store has to exist *before* the data it will hold.

**[[Research Family]], three of eight, a fourth building.** [[Agent — Topic Researcher]] (the eighth
agent, added — see [[Research Family]]), [[Agent — Market Analyst]] and
[[Agent — Idea Synthesizer]], over the [[Research Directory]].

The three were chosen together because they are the shortest path to a research
loop that closes: the Topic Researcher and the Market Analyst *produce* evidence
from two different worlds — the web and the tape — and the Idea Synthesizer is the
only agent that reads evidence back and decides. Building a producer without the
consumer would fill a directory nothing reads; building the consumer without a
producer would give it nothing to fuse.

Built: [[Agent — Topic Researcher]], [[Agent — Market Analyst]],
[[Agent — Idea Synthesizer]], [[Agent — News Collector]].
Building: [[Agent — Screener]], [[Agent — Fundamental]],
[[Agent — News And Catalyst]], [[Agent — Session Plan]].
Not built: [[Agent — Sentiment]], [[Agent — Regime And Correlation]].
Strategy has the [[Agent — Backtest Runner]] in progress and the rest in spec;
all four Execution agents are building, trading on IBKR paper. Charting and
Journal are complete. See [[Build Order]].

### Dataview (if the plugin is enabled)

```dataview
TABLE family, cadence, tier, status
FROM #agent
WHERE file.folder != "20-Agents"
SORT family ASC, file.name ASC
```

## Related

[[Agent Contract]] · [[Task Bus]] · [[Daemon And Cadence]] · [[MCP Gateway]] · [[System Overview]]
