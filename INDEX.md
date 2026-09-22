# Trading Corpus Index

Read-only reference library of cloned repos. **Read this file first.** Only open a
repo's real source when an entry here points you at a specific path. Never load a
whole repo, a notebook, or a full README into context. Cite `repo/path/file.py`
when you borrow an idea.

Legend: 🧱 framework · 🛡️ risk/portfolio · 🤖 AI/LLM/RL · 🔌 MCP server · 📚 link list

---

## 🧱 Backtesting / execution frameworks

### vectorbt
Vectorized backtesting on pandas/numpy — extremely fast for parameter sweeps and
large universes. Best for: research, signal grid search, indicator studies.
- `vectorbt/portfolio/` — Portfolio.from_signals / from_orders, the core engine
- `vectorbt/portfolio/nb.py` — numba order-fill logic, slippage, fees
- `vectorbt/generic/drawdowns.py` — drawdown records
- `vectorbt/indicators/factory.py` + `basic.py` — how to build parametrized indicators

### backtesting.py
Minimal, single-asset event backtester. Best for: quick strategy prototypes, teaching.
- `backtesting/backtesting.py` — Strategy/Backtest classes
- `backtesting/lib.py` — helpers (crossover, resample, SignalStrategy)
- `doc/examples/Parameter Heatmap & Optimization.py` — optimization pattern

### freqtrade
Full crypto trading bot: strategy API, backtest, hyperopt, live, protections. Best
for: production bot architecture, walk-forward, drawdown guards, FreqAI (ML).
- `freqtrade/optimize/backtesting.py` — backtest engine
- `freqtrade/optimize/hyperopt_tools.py` — hyperparameter optimization
- `freqtrade/plugins/protections/max_drawdown_protection.py` — stop trading on DD
- `freqtrade/plugins/protections/` — cooldown, stoploss-guard, low-profit-pairs
- `freqtrade/freqai/` — ML feature pipeline + model retraining

### nautilus_trader
Institutional event-driven platform, Rust core + Python API. Best for: correct
event architecture, order types, multi-venue, low-latency design.
- `python/nautilus_trader/risk/` — pre-trade risk engine
- `python/nautilus_trader/portfolio/` — position/PnL accounting
- `python/nautilus_trader/execution/` — order lifecycle
- `python/nautilus_trader/indicators/` — indicator implementations

### backtrader
Mature single-process framework, big community, many examples. Best for: readable
strategy/indicator/analyzer patterns.
- `backtrader/strategy.py`, `backtrader/cerebro.py` — core
- `backtrader/analyzers/` — Sharpe, drawdown, returns, tradeanalyzer
- `backtrader/sizers/` — position sizing plugins

### zipline
Quantopian's event-driven backtester (legacy but instructive). Best for: pipeline
API for cross-sectional factor strategies.
- `zipline/algorithm.py`, `zipline/pipeline/` — factor pipeline
- `zipline/finance/slippage.py`, `commission.py` — cost models

### hftbacktest
Tick-level HFT / market-making sim with order-queue position and feed+order latency.
Best for: microstructure, queue modeling, maker strategies. (Rust + Python)
- `py-hftbacktest/hftbacktest/` — Python API
- `hftbacktest/src/backtest/` — Rust matching/latency models
- `examples/` — Binance/Bybit market-making notebooks

### machine-learning-for-trading (Stefan Jansen book code)
27 chapters, end-to-end ML strategy pipelines. Best for: feature engineering,
alpha factors, backtesting ML signals, portfolio construction.
- `08_financial_features/` — factor construction + evaluation
- `16_strategy_simulation/` — backtesting, strategy evaluation
- `19_risk_management/` — risk metrics and controls
- `11_ml_pipeline/` — the full ML4T workflow
- `17_portfolio_construction/` — weights, constraints, rebalancing
- `data/equities/fundamentals/xbrl_download.py` — SEC EDGAR XBRL client: the
  mandatory contact `User-Agent` (SEC 403s anonymous clients), CIK-keyed
  caching, and the **fiscal-period-vs-filed-date** keying that prevents
  lookahead bias in statement data
- `22_rag_financial_research/` — retrieval over financial documents
- `23_knowledge_graphs/` — entity graphs over market data
- `24_autonomous_agents/` — LLM agents that research and trade
- `25_live_trading/`, `26_mlops_governance/` — paper→live, model governance

---

## 🛡️ Risk & portfolio

### Riskfolio-Lib
Portfolio optimization + risk modeling (mean-variance, CVaR, HRP, risk parity, 20+
risk measures). Best for: allocation, risk budgeting.
- `riskfolio/src/Portfolio.py` — optimization models
- `riskfolio/src/RiskFunctions.py` — VaR, CVaR, CDaR, max drawdown, ...
- `riskfolio/src/ParamsEstimation.py` — expected returns / covariance estimators

### PyPortfolioOpt
Practical portfolio optimization. Best for: efficient frontier, Black-Litterman,
converting weights to whole-share orders.
- `pypfopt/efficient_frontier/`, `pypfopt/expected_returns.py`, `pypfopt/risk_models.py`
- `pypfopt/discrete_allocation.py` — weights → integer share counts
- `pypfopt/black_litterman.py`, `hierarchical_portfolio.py`

### empyrical
Pure risk/performance metrics library. Best for: correct Sharpe, Sortino, Calmar,
max drawdown, alpha/beta, tail ratio formulas.
- `empyrical/stats.py` — every metric, single file

### pyfolio
Tearsheet generation over returns/positions/transactions. Best for: reporting,
rolling risk, drawdown tables.
- `pyfolio/tears.py`, `pyfolio/timeseries.py`, `pyfolio/perf_attrib.py`

### FinancePy
Derivatives pricing + risk (rates, FX, equity, credit). Best for: option greeks,
curve building, bond math.
- `financepy/products/`, `financepy/models/`

---

## 🤖 AI / LLM / RL for trading

### TradingAgents
Multi-agent LLM trading firm: analyst / researcher / trader / risk-team debate loop.
Best for: agent orchestration design, prompt structure, risk-debate pattern.
- `tradingagents/graph/` — the agent graph / control flow
- `tradingagents/agents/risk_mgmt/` — aggressive/conservative/neutral debators
- `tradingagents/agents/managers/` — research + portfolio manager
- `tradingagents/dataflows/` — **the multi-vendor data layer**, and the best
  reference in the corpus for a yfinance-primary company-data stack:
  - `interface.py` — `VENDOR_METHODS` chain-of-vendors with typed per-vendor
    errors, walked in configured order; no silent fallback to an unconfigured
    vendor
  - `stockstats_utils.py` — `yf_retry`: backoff on rate limits ONLY, everything
    else propagates; plus a present-but-stale frame guard
  - `symbol_utils.py` — ticker normalisation and the `NoMarketDataError`
    taxonomy (yfinance returns a truthy dict for a nonexistent symbol)
  - `fred.py` — small clean client shape for a keyed free API

### FinRL
Financial reinforcement learning: gym-style market envs + DRL agents. Best for:
RL env design, state/reward shaping, portfolio-allocation envs.
- `finrl/meta/env_stock_trading/` — trading env (state, action, reward)
- `finrl/meta/env_portfolio_optimization/` — allocation env
- `finrl/agents/` — SB3 / ElegantRL / RLlib wrappers

### FinRL-Meta
Data pipelines + hundreds of market environments for FinRL. Best for: data
processors (yfinance, alpaca, ccxt), benchmark envs.
- `meta/data_processors/` — yfinance, alpaca, ccxt adapters
- `meta/env_stock_trading/`, `meta/env_portfolio_allocation/` — benchmark envs

### FinGPT
Open financial LLMs — sentiment, forecasting, RAG, fine-tuning recipes. Best for:
news/sentiment signal generation, LLM fine-tune pipelines.
- `fingpt/FinGPT_Sentiment_Analysis*/`, `fingpt/FinGPT_Forecaster/`

### qlib (Microsoft)
AI-oriented quant platform: data server, alpha models, backtest. Best for:
Alpha158/360 factor sets, model zoo, rolling retrain.
- `qlib/contrib/model/` — GBDT, LSTM, Transformer, etc.
- `qlib/contrib/strategy/` — TopkDropout, weight strategies
- `qlib/contrib/strategy/optimizer/` — enhanced indexing, portfolio optimizer
- `qlib/backtest/` — executor, position, account

---

## 🔌 MCP servers (AI ↔ data / execution)

### alpaca-mcp-server (official)
FastMCP + OpenAPI. Stocks/options/crypto data + order placement via natural language.
- `src/` — 16 py files; tool defs, auth, order/position tools

### jesse-mcp
MCP bridge to the Jesse crypto trading framework.

### tradingview-mcp
Real-time data, technical analysis, screeners, backtesting via TradingView.

### mcp-market-data-server (fintools-ai)
Volume profile, 15+ indicators, ORB, fair-value-gap analysis for AI trading agents.

### mcp-server (financial-datasets)
Financial Datasets stock market API (fundamentals, prices, news).

### StockMCP
Yahoo Finance real-time data + basic analysis, FastAPI-based.

Use these as **reference implementations** for writing your own MCP tools (tool
schema, auth handling, error shape) — not necessarily as running dependencies.

---

## 📚 Link lists (read the README section relevant to the task, then stop)

- **awesome-quant** — libs by category: indicators, pricing, backtesting, risk, data sources
- **awesome-systematic-trading** — 100+ libs + coded strategies from papers with Sharpe ratios
- **awesome-ai-in-finance** — LLM/DL strategies, agents, MCP servers, papers
- **awesome-trading-agents** — LLM trading agents, MCP servers, agent skills
- **best-of-algorithmic-trading** — ranked OSS list, updated weekly

---

## 🏦 Prop firm

### PropForge
Browser-based prop-firm challenge simulator (FTMO / TopStep / Apex rules: phases,
daily loss, max drawdown, profit target). Best for: encoding prop-firm rule sets
and evaluation logic.

---

## Quick routing table

| You need… | Look at |
|---|---|
| Fast parameter sweep / signal research | vectorbt, qlib |
| Production bot architecture | freqtrade, nautilus_trader |
| Correct risk metric formulas | empyrical/stats.py |
| Position sizing / allocation | PyPortfolioOpt, Riskfolio-Lib, backtrader/sizers |
| Drawdown / stop-trading guards | freqtrade/plugins/protections, PropForge |
| Order/latency/queue microstructure | hftbacktest, nautilus_trader/execution |
| LLM agent orchestration | TradingAgents, awesome-trading-agents |
| RL env design | FinRL, FinRL-Meta |
| News/sentiment signals | FinGPT |
| Alpha factor libraries | machine-learning-for-trading, qlib (Alpha158/360) |
| Writing an MCP data/trade tool | alpaca-mcp-server, mcp-market-data-server |
| Where else to look | the 📚 link lists |
