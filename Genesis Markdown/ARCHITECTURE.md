# Genesis Agent — Architecture

> A JARVIS-style, always-on trading intelligence system. One voice-driven
> orchestrator commands a fleet of specialist agents that research markets,
> mark up charts, backtest ideas, write to your Obsidian vault, and execute
> trades — while the market is open **and** closed.

Status: **design only. No code in this repo yet.** This document is the blueprint
the build follows.

---

## 1. Design goals

| Goal | What it means concretely |
|---|---|
| **Voice-first, hands-free** | ElevenLabs in/out. Speak from anywhere in the room; the orchestrator does the rest. |
| **Always running** | A daemon that never sleeps. Market-open loop and market-closed loop are different behaviours, not on/off. |
| **Autonomous idea generation** | Agents proactively surface setups, news, regime shifts, and journal insights without being asked. |
| **Execute, not just advise** | Real broker connectivity behind a hard risk gate and a configurable approval mode. |
| **Memory that compounds** | Every idea, trade, chart, and lesson is captured, linked, and recalled. Obsidian is the human-readable layer; a graph + vector store is the machine layer. |
| **Token-disciplined** | Research digging happens in subagents. The orchestrator context stays lean. (Inherited rule from `CLAUDE.md` / `INDEX.md`.) |
| **Local-first where it matters** | Strategy logic, memory, and journal never require a cloud vendor. Cloud is used for voice, LLM inference (optional), and market data. |

---

## 2. System topology

```
                        ┌───────────────────────────────┐
              voice in  │        ORCHESTRATOR           │  voice out
        ┌───────────────►   (JARVIS — the main input)   ├───────────────┐
        │               │  • ElevenLabs STT / TTS       │               │
        │               │  • intent + task planner      │               ▼
   ┌────┴─────┐          │  • agent router / scheduler   │        ┌────────────┐
   │  User    │          │  • approval gate              │        │  Speakers  │
   │ (mic)    │          │  • conversation memory        │        └────────────┘
   └──────────┘          └───────────────┬───────────────┘
                                         │  task bus (queue + events)
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                ▼               ▼               ▼                 ▼
 ┌────────────┐   ┌────────────┐  ┌────────────┐  ┌────────────┐   ┌────────────┐
 │ Research   │   │ Chart /    │  │ Strategy / │  │ Execution  │   │ Journal /  │
 │ agents     │   │ Markup     │  │ Backtest   │  │ + Risk     │   │ Insight    │
 │            │   │ agents     │  │ agents     │  │ agents     │   │ agents     │
 └─────┬──────┘   └─────┬──────┘  └─────┬──────┘  └─────┬──────┘   └─────┬──────┘
       │                │               │               │                │
       └────────────────┴───────┬───────┴───────────────┴────────────────┘
                                ▼
                   ┌─────────────────────────┐        ┌──────────────────────┐
                   │   MCP GATEWAY           │◄──────►│  MCP servers          │
                   │  (tool registry +       │        │  market data, broker, │
                   │   smart tool selection) │        │  TradingView, news…   │
                   └───────────┬─────────────┘        └──────────────────────┘
                               ▼
        ┌───────────────────────────────────────────────────────────┐
        │                   MEMORY FABRIC                            │
        │  conversation buffer · episodic log · knowledge graph ·    │
        │  vector store · trade ledger · Obsidian vault (mirror)     │
        └───────────────────────────────────────────────────────────┘
                               ▲
        ┌──────────────────────┴───────────────────────┐
        │  TRADING CORPUS  (this folder — read-only)    │
        │  vectorbt · freqtrade · nautilus_trader ·     │
        │  TradingAgents · qlib · FinRL · … see INDEX.md│
        └──────────────────────────────────────────────┘
```

---

## 3. The Orchestrator

The orchestrator is the only thing the user talks to. It is a thin, always-warm
coordinator — **not** where heavy reasoning happens.

### 3.1 Responsibilities

1. **Listen** — wake-word + open-mic listening, echo rejection, VAD. (Pattern
   reference: `jarvis/src/jarvis/listening/` — wake detection, intent judge,
   transcript buffer, state manager.)
2. **Understand intent** — classify each utterance: `directed` command,
   `ambient` chatter to ignore, `follow-up`, or `interrupt/stop`.
3. **Plan** — decompose a request into a task list; decide which agent(s) own
   each step. (Pattern reference: `jarvis/src/jarvis/reply/planner.py`.)
4. **Route & schedule** — dispatch tasks onto the task bus; hold recurring jobs
   (pre-market brief, hourly scan, EOD journal) on a cron.
5. **Gate** — anything that spends money or places an order passes the approval
   policy before it leaves the building.
6. **Speak** — stream a spoken summary back; keep spoken replies short, push
   detail to the dashboard and the vault.
7. **Remember** — write the conversation, decisions, and outcomes to the memory
   fabric.

### 3.2 Voice stack (ElevenLabs)

| Stage | Component | Notes |
|---|---|---|
| Capture | local mic → VAD → ring buffer | barge-in supported; user can talk over TTS |
| Wake | local wake-word ("Genesis" / "Jarvis") | runs on-device, no audio leaves until woken |
| STT | **ElevenLabs Scribe** (streaming) | partials drive the planner early |
| Intent | small LLM classifier | directed / ambient / follow-up / stop |
| Reason | orchestrator LLM (large) + agents | see §7 model tiers |
| TTS | **ElevenLabs** streaming TTS, custom voice ID | SSML for numbers, tickers, prices; interruptible |
| Earcons | short tones for "heard", "working", "done", "trade placed", "risk blocked" | non-verbal status (pattern: `jarvis/src/jarvis/output/tune_player.py`) |

Persona: calm, concise, British-butler register. Confirms before risk. Never
hypes. Reads P&L and levels precisely. A configurable **"brief me" verbosity**
(one-liner ↔ full narrative).

### 3.3 Approval modes

| Mode | Behaviour |
|---|---|
| `advisory` | Agents may research, chart, backtest, draft orders. **No** live orders. |
| `confirm` (default) | Live orders require a spoken "yes" naming the ticker + size. Time-boxed (confirmation expires in 60 s). |
| `auto-within-limits` | Orders execute automatically **iff** inside a signed risk envelope (max position, max daily loss, allowed symbols, session). Everything logged + spoken after the fact. |
| `halt` | Kill switch. Flatten-all optional. No new orders, agents drop to research-only. |

---

## 4. The agent fleet

Every agent is a focused specialist with its own system prompt, its own tool
allow-list, its own memory namespace, and a declared **cadence** (on-demand,
market-open loop, market-closed loop, or cron). Agents talk to each other only
through the task bus and the memory fabric — never directly.

Base contract (pattern reference: `gensis-agents/shared/agent-base.js` —
start/stop/status/runTask; `TradingAgents/tradingagents/graph/` — agent graph
control flow).

### 4.1 Research & Insight

| Agent | Job | Key tools / sources | Cadence |
|---|---|---|---|
| **Market Analyst** | Top-down read: indices, breadth, sectors, rates, DXY, VIX term structure, risk-on/off. Produces the daily regime label. | market-data MCP, TradingView MCP, macro feeds | pre-market cron + on-demand |
| **News & Catalyst** | Scans headlines, filings, earnings calendar, Fed speak, econ prints. Tags each item: ticker, direction, confidence, half-life. Fences all web text as untrusted data. | news MCP, financial-datasets MCP, web search, economic calendar | market-open loop (5–15 min) + event-driven |
| **Sentiment** | Social + options-flow + put/call + funding rates. Divergence detector (price vs. sentiment). | FinGPT-style sentiment (`fingpt/FinGPT_Sentiment_Analysis*`), options-flow MCP | hourly |
| **Fundamental** | Valuation, growth, margins, guidance vs. consensus, insider activity. Screens the universe on factor sets. | financial-datasets MCP, qlib Alpha158/360 factors (`qlib/contrib/data/`) | daily (closed) |
| **Screener / Scanner** | Runs saved scans across the universe: breakouts, unusual volume, gap-and-go, mean-reversion bands, 52-wk, ORB, fair-value-gap. | `mcp-market-data-server` (volume profile, ORB, FVG, 15+ indicators), vectorbt for the sweep | market-open loop (1–5 min) |
| **Idea Synthesizer** | Fuses analyst + news + sentiment + scanner output into ranked, structured trade ideas with thesis, invalidation, timeframe, and a confidence score. Writes each to the vault. | reads memory fabric; LLM | every 15 min open, once closed |
| **Regime / Correlation** | Rolling correlation & volatility regimes; flags when a strategy's assumed regime no longer holds. | empyrical (`empyrical/stats.py`), qlib | daily |

### 4.2 Charting & Markup

| Agent | Job | Tools |
|---|---|---|
| **Chart Markup** | Given a ticker + timeframe: pull OHLCV, compute levels (S/R, VWAP, anchored VWAP, ORB, prior-day H/L, FVGs, order blocks, trendlines, Fib), and render an annotated chart image. Produces both a PNG (for voice-reply attachment / dashboard) and a spec object (for the vault + re-render). | charting engine (§8), `mcp-market-data-server`, TradingView MCP |
| **Pattern Recognition** | Classify structure: trend/range, HH-HL / LH-LL, wedges, flags, H&S, double tops, liquidity sweeps. Confidence + annotated overlay. | vision LLM on rendered chart + rule engine |
| **Multi-timeframe** | Same ticker across 4–5 timeframes, one composite image, alignment score. | charting engine |
| **Level Watcher** | Holds a live list of "price near level" alerts derived from markup specs; fires an event onto the bus when touched. | market-data MCP stream |

### 4.3 Strategy, Backtest & Optimization

| Agent | Job | Corpus references |
|---|---|---|
| **Strategy Author** | Turn a plain-English idea into a testable strategy object (entries, exits, sizing, filters). Can emit PineScript alerts too. | `gensis-agents/agents/alert-agent` (condition builder, filters, PineScript), `backtesting.py/lib.py` |
| **Backtest Runner** | Run the strategy over history; return metrics + equity curve + trade list + tearsheet. Vectorized sweep first, event-driven confirm second. | vectorbt (`vectorbt/portfolio/`), `backtesting.py`, freqtrade (`freqtrade/optimize/backtesting.py`) |
| **Optimizer** | Parameter search with walk-forward + out-of-sample holdout; guards against overfitting (parameter-sensitivity heatmaps, deflated Sharpe). | freqtrade hyperopt (`freqtrade/optimize/hyperopt_tools.py`), `backtesting.py` heatmap example |
| **Risk Metrics** | Canonical Sharpe / Sortino / Calmar / max-DD / tail ratio / alpha-beta for any equity curve. | `empyrical/stats.py` (single file, correct formulas) |
| **Portfolio / Allocation** | Position sizing and portfolio weights: risk parity, HRP, mean-CVaR, Kelly-fraction cap, whole-share conversion. | Riskfolio-Lib (`riskfolio/src/Portfolio.py`), PyPortfolioOpt (`discrete_allocation.py`) |
| **ML Signal (optional)** | Feature pipeline + model retrain for predictive signals; kept advisory. | `machine-learning-for-trading/04_alpha_factor_research/`, qlib model zoo, FinRL envs |
| **Prop-firm Guard** | Encodes FTMO / TopStep / Apex rule sets: daily loss, trailing max DD, profit target, consistency. Blocks orders that would breach. | PropForge rule sets |

### 4.4 Execution & Risk

| Agent | Job | Notes |
|---|---|---|
| **Pre-Trade Risk Engine** | Every order proposal passes here first: symbol allow-list, max position %, max portfolio heat, max daily loss, correlation cap, session window, prop-firm rules, duplicate/fat-finger check. Returns `approve` / `resize` / `reject` + reason. | pattern: `nautilus_trader/risk/`; `freqtrade/plugins/protections/` |
| **Order Manager** | Places, modifies, cancels orders; manages brackets (stop + target), trailing stops, partial exits, OCO. Tracks lifecycle. | pattern: `nautilus_trader/execution/` |
| **Position / P&L Accountant** | Real-time position, average price, realized/unrealized P&L, exposure by sector/factor. Source of truth for the risk engine. | pattern: `nautilus_trader/portfolio/` |
| **Broker Adapter(s)** | Normalizes across brokers behind one interface (Alpaca first; others pluggable). Paper and live are the same code path, different keys. | `alpaca-mcp-server` as reference impl for tool schema/auth/error shape |
| **Execution Quality** | Post-trade: slippage vs. arrival, fill rate, fees; feeds the journal. | slippage/commission models from zipline / vectorbt for expectations |
| **Kill Switch** | Standalone. Voice command "Genesis, halt" or a breached hard limit → cancel-all, optional flatten-all, mode → `halt`. | independent of the LLM path |

### 4.5 Journal, Learning & Ops

| Agent | Job |
|---|---|
| **Trade Journal** | Every fill → a vault note: entry/exit, thesis (pulled from the idea it came from), chart snapshots at entry and exit, R multiple, emotions prompt, tags. |
| **Performance Analyst** | Rolling tearsheet, per-strategy / per-setup / per-session / per-symbol edge; win rate, expectancy, MAE/MFE. Weekly spoken review. |
| **Insight Miner** | Mines the journal + ledger for patterns: "you lose on Fridays after 2pm", "your breakout setup's edge decayed since March", "oversized 3 of last 5 losers". Writes lessons to memory as high-priority recall. |
| **Backtest-vs-Live Drift** | Compares live results to the strategy's backtest expectation; alerts on divergence (regime change or implementation bug). |
| **Watchdog / Health** | Heartbeats every agent, MCP server, data feed, broker session. Reconnects, retries, and tells you when something's down. |
| **Digest / Summariser** | Compresses the day's activity into a morning brief and an evening recap; keeps memory from bloating (pattern: `jarvis` diary summariser + recall gate). |

### 4.6 Cadence summary

| Cadence | Agents active |
|---|---|
| **Market-open loop** | News/Catalyst, Sentiment, Screener, Level Watcher, Idea Synthesizer, Position/P&L, Execution Quality, Watchdog |
| **Market-closed loop** | Fundamental, Regime/Correlation, Backtest Runner, Optimizer, Insight Miner, Performance Analyst, Drift, Digest |
| **Cron** | Pre-market brief (analyst + calendar), EOD journal sweep, weekly review, nightly memory consolidation, weekly corpus re-index (`build_index.sh`) |
| **Event-driven** | Level touched, order filled, risk breach, news spike, agent down |
| **On-demand** | Any agent, via the orchestrator |

---

## 5. MCP layer

### 5.1 MCP Gateway

A single gateway sits between agents and all MCP servers:

- **Unified tool registry** — every MCP tool + every built-in tool in one
  searchable catalogue (pattern: `jarvis/src/jarvis/tools/registry.py`).
- **Smart tool selection** — a router picks the ~N relevant tools per task so
  adding servers never causes "context rot" (pattern:
  `jarvis/src/jarvis/tools/selection.py` + `tool_search.py` escape hatch).
- **Persistent runtime** — one long-lived session per server, queue-based
  dispatch, retry on transient session loss (pattern:
  `jarvis/src/jarvis/tools/external/mcp_runtime.py`).
- **Untrusted-content fence** — any text returned from web/news/social MCPs is
  wrapped as data, never interpreted as instructions (pattern:
  `jarvis/src/jarvis/tools/builtin/web_search.spec.md`).
- **Per-agent allow-lists** — the Execution agent can reach the broker MCP; the
  News agent cannot.

### 5.2 MCP servers to integrate

| Category | Server | Use |
|---|---|---|
| Broker / execution | **alpaca-mcp-server** (official) | stocks/options/crypto data + order placement |
| | jesse-mcp | crypto framework bridge (optional) |
| Market data / TA | **mcp-market-data-server** (fintools-ai) | volume profile, ORB, FVG, 15+ indicators |
| | **tradingview-mcp** | real-time data, TA, screeners |
| | StockMCP | Yahoo Finance real-time + basic analysis |
| Fundamentals / news | **financial-datasets mcp-server** | fundamentals, prices, news |
| Knowledge | **Obsidian MCP** | read/write the vault (notes, links, dataview) |
| | **Lithium MCP** (`/home/gzacc2002/Projects/Lithium Codebase`) | hybrid search over the cloned engineering/trading corpus |
| Backtest | jesse-mcp / custom | run a backtest by tool call |
| Utility | filesystem, git, fetch, time, sqlite | housekeeping |

Reference implementations for **writing our own** MCP tools (schema, auth, error
shape): `alpaca-mcp-server/src/`, `mcp-market-data-server`. Do **not** assume
every server above runs as a live dependency — several are studied, not shipped.

### 5.3 Custom MCP servers to build

1. **genesis-execution-mcp** — our normalized multi-broker order interface with
   the risk gate baked in (no agent bypasses it).
2. **genesis-charting-mcp** — "render this markup spec to a PNG" + "compute
   levels for ticker/timeframe".
3. **genesis-memory-mcp** — query/write the memory fabric (graph + vector +
   ledger) from any agent or from Claude Code.
4. **genesis-backtest-mcp** — one call runs vectorbt/backtesting.py/freqtrade and
   returns metrics + tearsheet + equity curve.

---

## 6. Memory fabric

Five layers, each with a distinct job. Obsidian is the **human** view; the graph
+ vector store is the **machine** view; they are kept in sync.

| Layer | Store | Contents | Lifetime |
|---|---|---|---|
| **Working / conversation** | in-memory ring + SQLite | last N turns, current task list, what's on screen | minutes–hours; rolls off |
| **Episodic log** | SQLite (append-only) | every request, agent run, tool call, decision, outcome, spoken reply | forever; summarised, never deleted |
| **Knowledge graph** | SQLite / embedded graph | entities (tickers, setups, strategies, levels, theses, lessons) + typed edges (`invalidated_by`, `derived_from`, `traded_as`, `contradicts`) | forever; consolidated nightly (pattern: `jarvis/src/jarvis/memory/graph.py`, `graph_ops.py`) |
| **Vector store** | local (e.g. sqlite-vec / LanceDB) | embeddings of ideas, journal notes, research snippets, chart descriptions, corpus chunks | forever; re-embed on model change |
| **Trade ledger** | SQLite (double-entry) | orders, fills, positions, P&L, fees — the financial source of truth | forever; reconciled against broker daily |

### 6.1 Recall pathways

- **Recall gate** — before answering, a cheap classifier decides *whether* memory
  is even needed, and *which* layer (pattern:
  `jarvis/src/jarvis/memory/recall_gate.py`). Keeps the orchestrator fast.
- **Hybrid retrieval** — vector similarity + graph neighbourhood + recency +
  explicit priority (lessons and active invalidations always surface).
- **Recency / superseding** — a newer fact about the same entity outranks and
  marks the old one stale (pattern: `jarvis` recency-superseding evals).
- **Scoped namespaces** — each agent recalls from its own namespace + shared;
  the Execution agent never trains on News chatter.
- **Consolidation** — nightly job merges duplicate entities, promotes repeated
  observations to "beliefs", writes the digest, prunes working memory.

### 6.2 Obsidian vault layout

```
GenesisVault/
├── 00-Inbox/                 # raw capture, unprocessed
├── 10-Ideas/                 # one note per trade idea (thesis, invalidation, confidence, status)
│   └── YYYY/MM/
├── 20-Charts/                # markup PNGs + specs, linked from ideas & journal
├── 30-Journal/               # one note per trade; entry/exit chart, R, tags, emotions
│   └── YYYY/MM/
├── 40-Strategies/            # strategy definitions, backtest reports, param history
├── 50-Research/              # analyst notes, news digests, sentiment reads
│   └── daily/YYYY-MM-DD.md   # the daily brief
├── 60-Lessons/               # Insight Miner output — high-priority recall
├── 70-Watchlists/            # dynamic, agent-maintained
├── 90-Meta/                  # regime log, correlation matrices, system health
└── templates/                # note templates the agents fill
```

Dataview queries power dashboards inside Obsidian (open ideas by confidence,
this week's journal, strategy leaderboard). The `Idea` and `Journal` note
schemas are frontmatter-typed so both humans and agents can query them.
Reference prompt: `Gensis Terminal Official/OBSIDIAN-VAULT-PROMPT.md`.

---

## 7. LLM model tiers

Route by task cost, not by habit (pattern: `jarvis/src/jarvis/llm/tiers.py`).

| Tier | Used for | Example model class |
|---|---|---|
| **Nano** (local) | wake/intent classification, recall gate, echo detection | small local (Ollama) |
| **Small** (local or cheap) | tool routing, planner step resolution, note formatting, summarisation | mid local / small hosted |
| **Large** | orchestrator reasoning, idea synthesis, risk-debate, strategy authoring | Claude (Sonnet/Opus class) |
| **Vision** | chart pattern recognition, screenshot reading | vision-capable large |
| **Embedding** | memory vector store, corpus search | local embedding model |

All hosted LLM calls are optional/pluggable — the system degrades to
local-only for everything except ElevenLabs voice and market data. Web/market
data and broker calls are the only hard external dependencies for live trading.

---

## 8. Charting engine

| Concern | Choice |
|---|---|
| Server-side render (for voice attachments, vault, dashboard) | headless candlestick renderer producing PNG/SVG from an OHLCV frame + a **markup spec** (levels, zones, lines, labels, annotations) |
| Live interactive chart (dashboard) | `price-chart.html` widget lineage from `Gensis Terminal Official/widgets/` — lightweight-charts style |
| Indicators & structure math | `mcp-market-data-server` (volume profile, ORB, FVG), plus in-house S/R, VWAP/AVWAP, Fib, order blocks |
| PineScript output | Alert Agent path — `gensis-agents/agents/alert-agent` condition builder → compiled Pine |
| Pattern vision | rendered PNG → vision LLM + rule engine cross-check |

The **markup spec** is a first-class object: stored in the vault, re-renderable,
diffable ("show me how this level held up"), and the input to the Level Watcher.

---

## 9. User interface

Three surfaces, one system:

### 9.1 Voice (primary)
Ambient listening, barge-in, earcons, short spoken replies. This is the JARVIS
surface — you should be able to run the whole day without touching a screen.

### 9.2 Orchestrator dashboard (web)
Lineage: `gensis-agents/orchestrator` + `Gensis Terminal Official` widget grid.

- **Agent grid** — live status per agent (idle / working / blocked / error),
  last action, next scheduled run; start/stop/restart.
- **Activity feed** — streaming log of what every agent is doing, plain-English.
- **Idea board** — ranked live ideas with thesis, chart thumbnail, confidence,
  age, status; one click to "chart it", "backtest it", "draft order".
- **Positions & risk** — live P&L, exposure, portfolio heat, daily-loss gauge,
  prop-firm rule bars.
- **Order ticket** — the only place a human places a manual order; same risk gate.
- **Chart pane** — interactive chart + latest agent markup overlay.
- **Approval queue** — pending order proposals awaiting `confirm`.
- **Transcript** — full conversation history, searchable.
- **Memory viewer** — browse the knowledge graph, journal, lessons (pattern:
  `jarvis/src/desktop_app/memory_viewer.py`).

### 9.3 Obsidian (the record)
The durable, human-editable knowledge base. Edits you make in Obsidian flow back
into memory on the next consolidation pass.

### 9.4 Desktop shell (optional)
A tray app / face widget like `jarvis/src/desktop_app/` — animated state face
(idle/listening/speaking/trading), global hotkey, settings window, quick-glance
P&L.

---

## 10. Always-on daemon

```
loop forever:
    tick = now()
    if market.is_open(tick):
        run market-open cadence agents (respecting per-agent interval)
        stream: fills, level touches, news spikes → event handlers
    else:
        run market-closed cadence agents
    run any cron jobs due at tick
    process task bus (user + agent-generated tasks)
    if memory.working.too_big(): summarise()
    health.heartbeat_all()
    sleep(short)
```

- **Supervision** — each agent runs as a supervised worker; crash → restart with
  backoff; repeated crash → mark degraded, tell the user (pattern:
  `gensis-agents/scripts/dev.js` process manager, `jarvis` daemon).
- **Backpressure** — the task bus has priority lanes (execution > risk > user >
  research); research is shed first under load.
- **Persistence** — task list, schedules, and open proposals survive a restart.
- **Observability** — structured logs with a leading emoji per line and indented
  hierarchy (house style from `jarvis/CLAUDE.md`); metrics on agent latency,
  tool error rate, idea→trade conversion, live-vs-backtest drift.

---

## 11. Safety & risk (non-negotiable)

1. **One gate, no bypass** — every order (agent *or* human) goes through the
   Pre-Trade Risk Engine. It is a separate process from the LLM path.
2. **Signed risk envelope** — max position size, max portfolio heat, max daily
   loss, symbol allow-list, session window, correlation cap, prop-firm rules.
   Changing it requires an explicit, logged action.
3. **Approval modes** (§3.3) default to `confirm`.
4. **Kill switch** — voice or breach triggers cancel-all + mode `halt`.
5. **Paper first** — identical code path; a new strategy trades paper for a
   configured period and must beat its own backtest expectation before it's
   eligible for live.
6. **Untrusted data fence** — news/social/web content can never issue commands.
7. **Idempotent orders** — client order IDs; no double-sends on retry.
8. **Reconciliation** — the ledger is reconciled against the broker every day;
   mismatch → `halt` + alert.
9. **Audit trail** — every decision links back through the idea, the research,
   and the conversation turn that produced it.
10. **No cloud lock-in for logic/memory** — strategy, journal, and memory run
    locally; losing internet degrades to research-only, never to a broken state.

---

## 12. Related repos & assets (this machine)

| Path | Role in Genesis Agent |
|---|---|
| `/home/gzacc2002/Projects/Genesis Agent/` | **this folder** — trading corpus index. `INDEX.md` (curated), `INDEX.auto.md` (generated), `build_index.sh`, `CLAUDE.md` working rules. Read-only reference library. |
| `/home/gzacc2002/Projects/INDEX.md` + `CLAUDE.md` | Same corpus rules at the Projects root. |
| `/home/gzacc2002/Work/jarvis/` | **Voice-assistant reference architecture.** Listening pipeline, wake/intent, planner, tool registry + smart selection, persistent MCP runtime, memory graph + recall gate, TTS/earcons, desktop face app, evals harness (`EVALS.md`). The blueprint for the orchestrator shell. |
| `/home/gzacc2002/Projects/gensis-agents/` | **"Trading OS" prototype.** Orchestrator dashboard + agent-base contract + task queue + Alert Agent (PineScript condition builder, filters, three-category notebook). Direct lineage for §4 and §9.2. Also holds `INDEX.md` (corpus copy) and `New Downloads/` (Pine scripts, prop-firm strategies, design-system zips). |
| `/home/gzacc2002/Projects/Gensis Terminal Official/` | **Widget-grid terminal UI.** Electron shell + widgets (price-chart, ticker-manager, trade-calendar, account-stats, consistency-calc, strategy/indicator libraries). `OBSIDIAN-VAULT-PROMPT.md`, `COMMERCIALIZATION-PLAN.md`, `rewrite.md`. Source for the dashboard widgets and Obsidian vault design. |
| `/home/gzacc2002/Projects/Lithium Codebase/` | **Local-first knowledge-base engine** (Rust, 10 crates): discovery → clone → analyse → chunk → embed → index → hybrid search → MCP. Use as the retrieval engine over the trading corpus and as a memory-fabric building block. See its `docs/ARCHITECTURE.md`. |
| `/home/gzacc2002/Projects/Nautilus/nautilus_trader/` | Vendored `nautilus_trader` — execution / risk / portfolio patterns (§4.4). |
| `/home/gzacc2002/Projects/backtrader-ide/`, `pine-forge/`, `red_diamond/` | Node projects — charting/IDE and Pine tooling; mine for UI and Pine-generation patterns. |
| `/home/gzacc2002/Projects/Vieques AI/`, `Vieques-AI/`, `Zillow Sheets/`, `Cyber Safely/` | Adjacent projects; not core, but available for shared UI components / infra patterns. |

### Corpus quick-routing (from `INDEX.md`)

| Need | Repo |
|---|---|
| Fast parameter sweep / signal research | vectorbt, qlib |
| Production bot architecture | freqtrade, nautilus_trader |
| Correct risk-metric formulas | `empyrical/stats.py` |
| Position sizing / allocation | PyPortfolioOpt, Riskfolio-Lib, `backtrader/sizers` |
| Drawdown / stop-trading guards | `freqtrade/plugins/protections`, PropForge |
| Order / latency / queue microstructure | hftbacktest, `nautilus_trader/execution` |
| LLM agent orchestration | TradingAgents, awesome-trading-agents |
| RL env design | FinRL, FinRL-Meta |
| News / sentiment signals | FinGPT |
| Alpha-factor libraries | machine-learning-for-trading, qlib (Alpha158/360) |
| Writing an MCP data/trade tool | alpaca-mcp-server, mcp-market-data-server |

**Working rule (inherited):** never load a whole repo/notebook/README into
context. `INDEX.md` → targeted `grep` → read one file. Delegate deep digging to
the `trading-researcher` subagent. Never modify a cloned repo — new code lives
under `_projects/<name>/`.

---

## 13. Build order (suggested)

1. **Skeleton** — daemon + task bus + agent-base + memory fabric (SQLite) +
   config. Port the jarvis daemon/planner/registry patterns.
2. **Orchestrator voice loop** — ElevenLabs STT/TTS + wake/intent + spoken
   summaries. No agents yet, just "talk to it".
3. **MCP gateway** — registry + smart selection + persistent runtime; wire
   market-data + Obsidian MCPs.
4. **Read-only agents** — Market Analyst, News, Screener, Idea Synthesizer,
   Chart Markup. Prove autonomous idea generation into the vault.
5. **Backtest agents** — Strategy Author + Backtest Runner + Risk Metrics via
   `genesis-backtest-mcp`.
6. **Dashboard** — agent grid + activity feed + idea board + chart pane.
7. **Execution (paper)** — risk engine + order manager + broker adapter +
   ledger, `advisory` → `confirm` mode. Paper only.
8. **Journal + Insight** — auto-journal every fill; weekly review; lesson mining.
9. **Go live** — flip a vetted strategy to live under `confirm`, tight envelope.
10. **Autonomy** — `auto-within-limits` for proven setups; expand the fleet.

---

## 14. Open questions to resolve before coding

- Primary broker + asset classes for v1 (Alpaca equities? futures? crypto?).
- Prop-firm constraints in play (which firm's rule set)?
- Language: Python core (matches the corpus) vs. Node (matches gensis-agents /
  Gensis Terminal)? — recommend **Python core + Node/Electron dashboard**.
- Local LLM horsepower available (GPU?) — sets how much stays offline.
- Obsidian vault: new dedicated vault vs. folder in an existing one.
- Data budget — which paid market-data feed for real-time.
