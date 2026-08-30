---
title: Open Questions
tags: [meta, decision]
---

# Open Questions

Answer these before [[Build Order|Phase 1]]. Each one changes code.

---

### 1. Broker and asset class for v1
**Options:** Alpaca (equities/options/crypto, best MCP support) · a futures broker
(NQ/ES — matches the Pine scripts in [[Repo — gensis-agents]] `New Downloads/`) · crypto (ccxt).

**Why it matters:** decides [[Agent — Broker Adapter]], the session calendar in
[[Daemon And Cadence]], contract-size math in [[Agent — Portfolio And Allocation]],
and whether [[Agent — Prop Firm Guard]] is in scope at all.

**Recommendation:** Alpaca paper for v1 — the official MCP server exists and is the
cleanest reference for tool schema/auth/error shape. Add futures once the gate is proven.

> **Decision:**

---

### 2. Prop firm in play
Your corpus includes PropForge and NQ prop-firm Pine strategies. If you're trading
a funded account, [[Prop Firm Rules]] moves from Phase 10 to Phase 7 — the rule set
becomes a hard constraint in [[Pre-Trade Risk Engine]], not an add-on.

**Which firm(s):** FTMO / TopStep / Apex / none

> **Decision:**

---

### 3. Language split
**Recommendation:** Python core + Node/Electron dashboard.

- Python: the entire [[Trading Corpus Index|corpus]] is Python (vectorbt, freqtrade,
  nautilus, qlib, empyrical). Rewriting that math in Node is wasted effort.
- Node/Electron: [[Repo — gensis-agents]] and [[Repo — Gensis Terminal Official]]
  already have the orchestrator dashboard and widget grid working.
- Boundary: HTTP + WebSocket, defined by [[Event Schema]].

**Alternative:** all-Node with a Python sidecar only for backtests. Simpler deploy, worse ecosystem fit.

> **Decision:**

---

### 4. Local LLM horsepower
GPU? VRAM? This sets how much of [[LLM Model Tiers]] stays offline.

- No GPU → nano/small tiers go hosted-cheap; latency budget for [[Voice Stack]] tightens.
- 24GB+ → wake, intent, recall gate, tool routing, and summarisation all run local;
  only orchestrator reasoning and vision go hosted.

> **Decision:**

---

### 5. Obsidian vault location
New dedicated `GenesisVault/` vs. a folder inside an existing vault.

**Recommendation:** dedicated vault. [[Agent — Trade Journal]] and
[[Memory Consolidation]] write frequently and would churn an existing vault's
sync/graph. See [[Obsidian Vault Schema]].

> **Decision:**

---

### 6. Market data feed
Free (yfinance, Alpaca IEX) is fine for research and closed-market work, and
insufficient for [[Agent — Level Watcher]] and intraday [[Agent — Screener]].

**Question:** budget for a real-time feed (Polygon / Databento / Alpaca SIP)?

**Consequence:** without it, drop [[Agent — Level Watcher]] to a 1-minute poll and
mark intraday ideas as delayed in [[Idea Schema]].

> **Decision (2026-08-29):** Read the **existing TradingView live subscription**
> through [[genesis-tradingview-mcp]] rather than buying the same ticks twice.
> That covers tier 2 in [[Market Data Sources]] — quotes, session H/L, and bars
> for local computation.
>
> **Still open:** tier 1. [[Pre-Trade Risk Engine]] may only read the broker's own
> feed ([[Safety Invariants]] §11), so this depends on §1. A broker feed may make
> a separate real-time subscription unnecessary — decide after §1.
>
> Also: cache every closed bar locally on first sight. Bars are immutable, so over
> months this becomes a private history that makes backtests free.

---

### 7. ElevenLabs vs. local voice
[[Repo — jarvis]]'s `CLAUDE.md` bans ElevenLabs on offline-first principle. Genesis
deliberately diverges — you asked for ElevenLabs. Confirm the trade:

- Cloud voice = better quality, streaming, custom voice; audio leaves the machine.
- Everything else (strategy, memory, journal, risk) stays local either way.
- Fallback: local Piper/Kokoro TTS when offline, so [[Voice Stack]] degrades rather than breaks.

> **Decision:**

---

### 8. Universe size
50 tickers, 500, or "everything"? Drives [[Agent — Screener]] cost, data bill,
[[Vector Store]] size, and whether the scan is vectorized (vectorbt) or event-driven.

> **Decision:**

---

### 9. Retrieval engine
Build the [[Vector Store]] fresh, or run [[Repo — Lithium Codebase]] as the
retrieval engine? Lithium already does discovery → chunk → embed → index → hybrid
search → MCP, in Rust, locally.

**Recommendation:** use Lithium for corpus/code retrieval, build a small purpose-made
store for [[Memory Fabric]] recall. Different access patterns.

> **Decision:**

---

### 10. Multi-account
One account or several (personal + funded + paper) in parallel? Multi-account means
[[Trade Ledger]] and [[Risk Envelope]] key on `account_id` from day one — cheap now,
expensive to retrofit.

> **Decision:**

---

### 11. Charting surface — RESOLVED
Where do marked-up charts actually appear?

> **Decision (2026-08-29):** **TradingView Desktop is the primary surface.** It is
> already the daily charting app with a live subscription, so Genesis runs
> alongside it and drives it via [[genesis-tradingview-mcp]] rather than trying to
> replace it.
>
> The headless renderers in [[Charting Engine]] stay — they cover vault notes,
> journal snapshots, vision input, and the [[Dashboard]]. Nothing autonomous may
> depend on a GUI being open.
>
> [[Markup Spec]] remains canonical. TradingView is a *renderer*, never the source
> of truth — otherwise level-outcome tracking in [[Knowledge Graph]] dies, and
> that is the capability no charting platform can give us.

**Still open:** does the CDP remote-debugging port actually open on TradingView
Desktop? A 30-minute spike gates the whole server — see
[[genesis-tradingview-mcp]]. If that door is shut, fall back to embedding
lightweight-charts in the [[Dashboard]] and applying markup by hand.
