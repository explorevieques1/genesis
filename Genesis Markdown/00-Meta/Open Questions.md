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

> **Decision (2026-08-30):** **Alpaca paper, US equities, for v1.** Takes the
> recommendation as written. [[Agent — Broker Adapter]] targets Alpaca paper keys;
> [[Daemon And Cadence]] uses the US equities session calendar; sizing is in whole
> shares, so no contract-size math in [[Agent — Portfolio And Allocation]] yet.
> Futures are deferred until the [[Pre-Trade Risk Engine]] gate is proven, at which
> point [[Futures Broker Options]] gets re-opened alongside §2.

**If futures:** see [[Futures Broker Options]] for the survey. Tradovate direct
API access is a dead end for prop accounts (excludes eval/funded balances
outright). The four paths that work — TopstepX, Sierra Chart DTC, Rithmic
R|API+, NinjaTrader ATI — are firm-dependent, so this decision is entangled with
§2 below; resolve them together.

---

### 2. Prop firm in play
Your corpus includes PropForge and NQ prop-firm Pine strategies. If you're trading
a funded account, [[Prop Firm Rules]] moves from Phase 10 to Phase 7 — the rule set
becomes a hard constraint in [[Pre-Trade Risk Engine]], not an add-on.

**Which firm(s):** FTMO / TopStep / Apex / none

> **Decision (2026-08-30):** **None for v1.** No funded account in play, so
> [[Prop Firm Rules]] stays in [[Build Order|Phase 10]] and [[Agent — Prop Firm Guard]]
> is out of scope. The [[Pre-Trade Risk Engine]] is built against [[Risk Envelope]]
> alone — but its rule evaluation stays pluggable, because prop rules become *hard
> constraints inside the gate* if this is ever revisited, not a layer bolted on top.

**Consequence for §1:** Topstep → build against TopstepX (official API, reference
MCP already exists). Apex or most others → target Sierra Chart DTC first, Rithmic
R|API+ as the lower-latency follow-on, NinjaTrader ATI as the NT8-only fallback.
Full detail in [[Futures Broker Options]].

---

### 3. Language split
**Recommendation:** Python core + Node/Electron dashboard.

- Python: the entire [[Trading Corpus Index|corpus]] is Python (vectorbt, freqtrade,
  nautilus, qlib, empyrical). Rewriting that math in Node is wasted effort.
- Node/Electron: [[Repo — gensis-agents]] and [[Repo — Gensis Terminal Official]]
  already have the orchestrator dashboard and widget grid working.
- Boundary: HTTP + WebSocket, defined by [[Event Schema]].

**Alternative:** all-Node with a Python sidecar only for backtests. Simpler deploy, worse ecosystem fit.

> **Decision (2026-08-30):** **Python core + Node/Electron dashboard.** Takes the
> recommendation as written. The boundary is **HTTP + WebSocket, defined by
> [[Event Schema]]** — the dashboard is a consumer of that contract and holds no
> business logic of its own. Nothing safety-critical crosses into Node.

---

### 4. Local LLM horsepower
GPU? VRAM? This sets how much of [[LLM Model Tiers]] stays offline.

- No GPU → nano/small tiers go hosted-cheap; latency budget for [[10-Architecture/Voice Stack]] tightens.
- 24GB+ → wake, intent, recall gate, tool routing, and summarisation all run local;
  only orchestrator reasoning and vision go hosted.

**Measured (2026-08-30):** Intel UHD Graphics (integrated, no CUDA, no usable VRAM),
7 GB system RAM with ~1 GB free, 12 CPU cores. This is the "No GPU" branch, and
harder than the branch assumed — there is not enough headroom to keep even a 3B
model resident alongside the Python core and the Electron dashboard.

> **Decision (2026-08-30):** **No local generative LLM. Hosted Claude for the
> small/large/vision tiers; nano stops being an LLM tier at all.** The tier table in
> [[LLM Model Tiers]] now names concrete models:
>
> - **nano → deterministic code, not a model.** A hosted round-trip is 300–800 ms at
>   best, so the `<100 ms` budget in [[10-Architecture/Voice Stack]] is unreachable by
>   any network call. Wake word, intent classification, echo detection and the
>   [[Recall Pathways|recall gate]] become keyword/regex plus a small ONNX classifier
>   on CPU. This *removes* an LLM from the hot path rather than relocating it.
> - **small → `claude-haiku-4-5`** ($1/$5 per MTok, 200K context). Tool routing,
>   planner step resolution, sentiment tagging, note formatting, summarisation.
>   Short prompts land inside the `<500 ms` budget.
> - **large → `claude-opus-5`** ($5/$25 per MTok, 1M context), adaptive thinking on,
>   `output_config.effort` tuned per agent — `low` for routine calls, `high`/`xhigh`
>   for [[Agent — Strategy Author|strategy authoring]] and risk debate.
> - **vision → `claude-opus-5`** as well; it is vision-capable, so
>   [[Agent — Pattern Recognition]] needs no second provider. Drop to
>   `claude-sonnet-5` if chart volume makes it expensive.
> - **embedding → stays local on CPU** — `bge-small-en-v1.5` or `all-MiniLM-L6-v2`
>   via ONNX runtime (~130 MB, fine on 12 cores). Anthropic exposes no embeddings
>   endpoint, and this is what feeds §9's retrieval engine either way.
>
> **Consequences.** Escalation is a model-string swap inside one SDK, not a provider
> swap, so `needs_escalation` in [[Agent Contract]] costs one line. The cost-control
> rules in [[LLM Model Tiers]] map onto real API features — prompt caching for
> "same symbol + same bar + same prompt", the Batch API (50% off) for closed-market
> work, and `output_config.task_budget` for the per-agent daily token budget.
> [[Error Handling And Degradation]] gains one case: `claude-opus-5` can return
> `stop_reason: "refusal"` on an HTTP 200, which is a silent hang in an autonomous
> loop unless checked before reading `content`.
>
> The **`none`** row of [[LLM Model Tiers]] is untouched. [[Pre-Trade Risk Engine]],
> [[Kill Switch]], [[Agent — Position And PnL Accountant]] and [[Agent — Risk Metrics]]
> have no model in their call path, whatever the tiers resolve to.
>
> **Revisit when** a GPU box (24 GB+ VRAM) enters the picture. At that point nano and
> small move back local per the original branch; nothing above changes shape, only
> the `Where` column.

---

### 5. Obsidian vault location
New dedicated `GenesisVault/` vs. a folder inside an existing vault.

**Recommendation:** dedicated vault. [[Agent — Trade Journal]] and
[[Memory Consolidation]] write frequently and would churn an existing vault's
sync/graph. See [[Obsidian Vault Schema]].

> **Decision (2026-08-30):** **Dedicated vault at `~/GenesisVault/`.** Matches the
> `memory.vault_path` default already in the [[Config And Secrets]] sketch. Note
> this is the *agent-written* vault — distinct from `Genesis Markdown/`, which is
> the hand-written system spec and stays in the repo.

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
- Fallback: local Piper/Kokoro TTS when offline, so [[10-Architecture/Voice Stack]] degrades rather than breaks.

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

### 10. Multi-account — RESOLVED
One account or several (personal + funded + paper) in parallel? Multi-account means
[[Trade Ledger]] and [[Risk Envelope]] key on `account_id` from day one — cheap now,
expensive to retrofit.

> **Decision (2026-08-30):** **Multi-account. `account_id` is a first-class key
> from day one.**
>
> Even though §1 and §2 land on a single Alpaca paper account for v1, the
> [[Trade Ledger]] is append-only: retrofitting a key onto it later would mean
> rewriting the one structure in the system that cannot be rewritten in place.
> The cost asymmetry is worse than "cheap now, expensive later" — it is "cheap
> now, or a migration of immutable history".
>
> Consequences, all live as of Phase 1:
> - `fills`, `orders`, `entries`, `cash_flows`, `positions` and
>   `equity_snapshots` all carry `account_id`.
> - Fill idempotency is `UNIQUE (account_id, broker_fill_id)` — the same broker
>   fill id in two accounts is two different fills.
> - `rebuild_positions()` keys on `(account_id, symbol)`.
> - [[Order And Fill Schema]] carries `account_id` on the order and the fill,
>   not just `account` on the proposal.
> - [[Risk Envelope]] limits are evaluated per account when it is built.

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

**CDP spike (2026-08-30): YES — qualifier: transport is raw CDP, not Playwright.**

The remote-debugging port opens and a full CDP attach works against the live,
signed-in app (TradingView Desktop 3.3.0 / Electron 38.2.2 / Chromium 140).
`Runtime.evaluate` read the active symbol off the real chart. [[genesis-tradingview-mcp]]
is viable, the decision above stands, and the lightweight-charts fallback is **not**
needed as the primary surface — it remains only the headless/no-GUI path.

Two qualifiers, both recorded in full in [[genesis-tradingview-mcp]]:

1. **Raw CDP websocket, not Playwright.** `connect_over_cdp` connects the socket
   then hangs to a 180 s timeout; raw CDP on the same endpoint answers in
   milliseconds.
2. **`ELECTRON_RUN_AS_NODE` must be unset when spawning the app**, or the launch
   fails in a way that impersonates the NO answer. See
   [[Error Handling And Degradation]].

---

### 12. Self-model retrieval — how far does interoception go?
[[Biological Design]] establishes that **this vault is the system's body map**:
when an agent needs to know how a component behaves it should *read* rather than
*infer*. The principle is settled. The mechanism is not.

**Open:**

1. **Who may read the self-model?** Every agent, or only the [[Orchestrator]]?
   Broad access is more capable and much more expensive per call.
2. **Retrieved how?** The vault is markdown on disk, so `Glob` + `Grep` already
   work. The alternatives are indexing it into the [[Vector Store]], or running
   [[Repo — Lithium Codebase]] over it (§9). Entangled with §9 — decide together.
3. **Does the self-model reach the system prompt, or only retrieval?** A standing
   summary of the anatomy costs tokens on every call; retrieval costs latency on
   the calls that need it. [[Recall Pathways]]' gate exists for exactly this
   trade.
4. **Is the map ever written by the system?** Dangerous and interesting. An agent
   that can edit its own body map can make the map lie, which is proprioceptive
   drift by another route. Default: **read-only to agents**, humans and the
   `/impl` command write it. Revisit only with a strong reason.

Not blocking [[Build Order|Phase 2]]. Blocking Phase 4, when read-only agents
first need to reason about components they did not write.

> **Decision:**
