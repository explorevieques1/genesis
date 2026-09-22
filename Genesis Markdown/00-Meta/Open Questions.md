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

> **Decision (2026-09-04) — REVERSES the 2026-08-30 decision above.**
> **Interactive Brokers. CME futures, not Alpaca / US equities.**
>
> IBKR's non-professional US futures data bundle is roughly **$10/month**, often
> waived by commissions, and it delivers **data and execution over one
> connection**. That single fact is the argument: charts, signals and fills
> cannot disagree with each other, because they are not coming from different
> places. Every alternative splits the feed from the broker and buys a
> reconciliation problem to go with the saving.
>
> Tradovate stays a dead end for the reason [[Futures Broker Options]] already
> gives: its market-data API triggers a **$290–500/month CME sub-vendor
> licence**. That is not a price difference, it is a different business model.
>
> **Alpaca is not deleted from the vault.** It is demoted to a possible
> equities adapter later. The [[Market Data Plane]]'s adapter layer is what
> makes that a config edit rather than a rewrite.
>
> Consequences:
> - [[Agent — Broker Adapter]] targets IBKR (IB Gateway, paper, port 4002).
> - [[Daemon And Cadence]] needs the **CME** session calendar, not US equities
>   — nearly 24×5, with a daily maintenance break. Different shape entirely.
> - [[Agent — Portfolio And Allocation]] needs **contract-size math** after all.
>   An ES point is $50 and an NQ point is $20; sizing in whole shares is gone.
> - [[Agent — Prop Firm Guard]] is back in scope alongside §2.
> - Read-Only API stays **on** at the gateway until Phase 7 — see
>   `deploy/ib-gateway/README.md`. That makes the socket structurally incapable
>   of placing an order, which is `afferent ≠ efferent` enforced by the broker
>   rather than by our convention.

> **Decision (2026-09-13) — Phase 7 opens on paper.** Read-Only API is **off**
> for paper logins (`IB_READ_ONLY_API=no`, written by the Connections panel
> when the trading mode is paper) and stays **on** for live ones: going live is
> [[Paper To Live Promotion]], never a side effect of saving a login. Orders go
> through a separate client (`execution.client_id`), never the data
> connections, which stay read-only. Delayed data is accepted on paper: the
> fat-finger and stop-side checks may use IBKR's delayed quote while
> `brokers.primary.mode` is `paper` ([[Safety Invariants]] #11 exception).
> One-click trading is `auto-within-limits` for the trader's own paper orders,
> switched on only from the trade panel ([[Approval Modes]]). Futures risk
> limits: 2 contracts per symbol, $2,000 daily loss, allow-list ES NQ MES MNQ
> RTY M2K YM MYM ([[Risk Envelope]]).

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

**Correction (2026-09-07):** the sentence *"there is not enough headroom to keep even
a 3B model resident"* was wrong, and the decision above still stands anyway.

`qwen2.5:3b` (1.93 GB, Q4_K_M) loads and runs on this box with ~2.7 GB available.
Measured warm: **352 ms p50** for a short classification, against the 1.3–6.5 s the
original Ollama measurement recorded. Cold load is 16.5 s, which is the number that
actually matters — it is why this stays off the voice path and why the user unit sets
`OLLAMA_MAX_LOADED_MODELS=1`.

Two things this changes and one it does not:

- **`small` is viable locally for development.** Tool routing, summarisation and note
  formatting at 352 ms is inside the `<500 ms` budget in [[LLM Model Tiers]].
- **A local dev tier exists at all**, which is the point — see
  [[LLM Model Tiers]] §Development tiers.
- **The production assignment does not change.** `large` and `vision` need reasoning a
  3B model does not have, and a second resident model would swap against the daemon.
  Nothing here reopens the nano decision: a 352 ms round trip is still four times the
  `<100 ms` budget, and intent classification stays deterministic code.

Also worth recording, because it cost an hour: the packaged Ollama systemd unit runs
`User=ollama` and reads `/usr/share/ollama/.ollama/models`, while a `ollama pull` run
as the operator writes `~/.ollama/models`. `/home/<user>` is mode 700, so the service
account cannot traverse into it and `OLLAMA_MODELS` does not help. The fix is a user
unit (`~/.config/systemd/user/ollama.service`) with the system one disabled.

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

> **Decision (2026-09-04) — RESOLVED. No separate real-time subscription is
> bought.**
>
> §1 landed on IBKR, and that closes the tier-1 half this question was waiting
> on: **the IBKR feed is tier 1 and serves both real-time and execution
> truth.** One connection, one number, no reconciliation between what the chart
> showed and what the fill happened at.
>
> **Databento is bought as HISTORICAL ONLY**, on free credits, and it is bought
> because IBKR *cannot* serve backtests — not as a preference:
>
> 1. **Expired futures contracts more than ~2 years past expiry are simply
>    unavailable** from IBKR. Ten years of ES history cannot be assembled from
>    it at any request rate.
> 2. **Its historical endpoint paces at 60 requests per 10 minutes**, plus a
>    15-second identical-request cooldown and 6-per-contract-per-2-seconds. A
>    backfill measured in thousands of requests is measured in days.
>
> Neither is a limit that money or patience removes.
>
> **This split — Databento for history, IBKR for live — is the single most
> important constraint on [[Market Data Plane]], and it is why the plane is
> adapter-shaped.** One vendor answers "what happened in 2019" and a different
> one answers "what is happening now". No single-vendor design would have been
> drawn this way, and retrofitting the seam later would mean reshaping the
> store's provenance columns after history had accumulated.
>
> Practical consequences, all live now:
> - `marketdata.adapters` in config carries per-vendor tier and
>   `historical_only`. Adding IBKR is a **config edit, not a code change**.
> - `budget.py` expresses IBKR's three pacing rules today, with no IBKR adapter
>   present. There are tests.
> - IBKR arrives at **tier 3**, not tier 1. Promotion requires the
>   reconciliation described in [[Market Data Sources]] — measured, recorded,
>   and made a test. "It connected" is not evidence of execution truth.

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

> **Decision (2026-09-14, for the [[Agent — Screener]]):** **The S&P 500**, from
> SPY's daily holdings. Fundamentals come from a nightly yfinance snapshot; 500
> rows filter in memory, so no vectorbt. Technical intraday scans and the other
> agents' universes are still open.

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

---

### 13. Futures symbol identity and roll policy — OPEN, blocking

`ES`, `ESZ6`, `ES1!` and a back-adjusted continuous series are **four different
things**. They differ in price, and one of them changes retroactively. A store
that calls them all "ES" corrupts every backtest silently and is close to
unrecoverable once history has accumulated under the wrong convention — there is
no repair, because the information needed to undo it was never written down.

This is the highest-cost-of-being-wrong decision in the [[Market Data Plane]],
which is why it is asked rather than assumed.

**Three sub-decisions, entangled:**

1. **Canonical id.** Implemented and in use: `FUT:CME:ES:2025-12` for a dated
   contract, `EQ:XNAS:AAPL` for an equity. The dated form is unambiguous
   forever, and it is what the store writes today. The continuous form is
   *reserved but refused* — `continuous_id()` fixes the spelling,
   `BarStore.write` rejects it.
2. **Roll rule** — when does the continuous series switch contracts?
3. **Adjustment method** — what happens to the price seam at the roll?

**Roll rule options:**

| Option | Rolls when | For | Against |
|---|---|---|---|
| **Volume** | front month's volume is exceeded by the next | Matches where liquidity actually is; what most traders see | Can oscillate across the crossover for a day or two |
| **Open interest** | OI crosses over | Smoother, less oscillation | Lags actual trading activity by a day or so |
| **Calendar** | fixed offset from expiry (e.g. 5 days) | Perfectly reproducible, no data needed | Sometimes rolls when nobody has rolled; wrong during unusual expiries |

**Adjustment options:**

| Option | Method | For | Against |
|---|---|---|---|
| **Back-adjusted** | subtract the roll gap from all prior bars | Returns and gaps are continuous; standard for backtesting | **Prices are not real.** Old ES bars can go negative. Historical levels are meaningless as prices |
| **Ratio** | multiply prior bars by a ratio | Percentage returns exact, prices stay positive | Absolute prices still fictional; compounding drift over many rolls |
| **None (stitched)** | just concatenate | Every price is a real traded price | A gap at every roll that is not a real market move — ruins any gap-based or level-based analysis |

**My recommendation, for when you decide:**

> **Volume roll, back-adjusted, stored as a separate derived series that never
> replaces the dated contracts.**
>
> Volume because Genesis reads *structure* — levels, ranges, patterns — and
> those live where the volume is. Back-adjusted because [[Agent — Backtest
> Runner]] needs continuous returns and that is the standard the corpus
> (vectorbt, backtrader) assumes.
>
> But the load-bearing half is the third clause: **derived, never a
> replacement.** Dated contracts stay the base truth in the store; a continuous
> series is computed from them, tagged with its roll rule and adjustment method
> in its own id (`CONT:CME:ES:volume:back`), and can be **rebuilt or thrown
> away** without touching history. That converts this from an unrecoverable
> decision into a reversible one, which is worth more than getting the roll rule
> right first time.
>
> One caveat to weigh: back-adjusted prices are **not real prices**, and
> [[Agent — Chart Markup]] draws levels *as prices*. A level from a
> back-adjusted 2019 ES bar is not a number anyone can trade against. Charts and
> level-watching should read dated contracts; only backtests should read the
> continuous series. If that split feels wrong, ratio adjustment is the
> compromise.

**Until this is answered:** the store writes **dated contracts only**, which is
always correct and never needs migrating. `BarStore.write` raises on a `CONT:`
id, `resolve_symbol` refuses a bare `ES` and says what it might have meant, and
the yfinance adapter refuses futures outright because its `ES=F` *is* a
continuous series with an undocumented roll.

Not blocking [[Build Order|Phase 4]]. Blocking [[Agent — Backtest Runner]] and
any multi-year futures study.

> **Decision:**

---

### 14. Cross-currency company data — OPEN, low urgency

yfinance reports `currency` and `financialCurrency` separately, and for ADRs and
foreign issuers **they differ**: the price is in USD, the statements are in the
home currency. A price-to-sales ratio computed across the two is a number with
no meaning, and it looks entirely normal — no error, no NaN, just a plausible
multiple that is wrong by the exchange rate.

**Nothing in the trading corpus guards this.** It was checked; there is no
pattern to copy.

**Current behaviour:** [[Company Data Model]] stores both currencies and exposes
`CompanyProfile.currency_mismatch`. The CLI warns. Nothing yet *refuses* to
compute the ratio, because the ratios come pre-computed from yfinance — which
means **yfinance may already be mixing them**, and we cannot tell from the
outside.

**Options:**

1. **Refuse.** Suppress derived cross-currency fields when the currencies
   differ. Honest, and it makes ADRs visibly less useful than domestic issuers.
2. **Convert.** Add an FX source and normalise everything to USD. Correct, and
   it means a rate as of *the filing date* for statements and *now* for price —
   two different rates in one ratio, which is its own subtlety.
3. **Label and pass through.** Keep the vendor's number, mark it, let the
   consumer decide. Cheapest, and it relies on every consumer remembering.

**Recommendation: (1) now, (2) when a foreign issuer is actually in the
universe.** Refusing costs nothing today — the universe is US futures and US
equities — and it converts a silent wrongness into a visible gap. Option 2 is
real work for a case that does not yet exist.

Not blocking anything. Becomes blocking the first time an ADR enters the
watchlist.

> **Decision:**

---

### 15. Restatements in as-filed history — OPEN, low urgency

A 10-K restates the prior two years as comparatives, so one fiscal period
appears in three filings with three filed dates and possibly three *values*.

[[Company Data Model]] currently keeps the **earliest** filing for a period,
because `filed_date` answers *"when did this become public"* and the honest
answer is the first time it was filed. Preferring the latest tags every
historical period with a recent filed date, and every as-of query then truncates
to almost nothing — observed during the build: a query for 2024-01-01 returned
FY2021 before this was fixed.

The cost of that choice: when a figure is genuinely **restated**, we hold the
original rather than the correction. For an as-of query that is right — the
original is what was known then. For "what is NVDA's FY2024 revenue" it is
wrong, and quietly.

**The real answer is to keep both** — original and restatement, keyed by filed
date, the way [[Market Data Plane]]'s store keeps a superseded bar. Not built,
because restatements are rare and the availability-date bug broke *every* query
while this one breaks a few.

Not blocking. Becomes blocking when [[Agent — Backtest Runner]] runs on
fundamentals.

> **Decision:**


---

### 16. The landing canvas — what does an empty screen offer? — OPEN, blocking UI-0

[[Operating Model]] §3 settles that the shell opens empty. It does not settle
what makes that emptiness usable, and the failure mode is real in both
directions: a screen with a cursor and nothing else is a dead end, and anything
added to fix that is the unrequested telemetry the rule exists to prevent.

**Options:**

1. **Cursor and nothing.** The command line, focused, with placeholder text.
   Purest, and it teaches nothing — the operator has 131 tools and no idea that
   any of them exist.
2. **Cursor plus the last session.** Recently-used panels and symbols as
   suggestions in the palette, revealed on first keystroke, never rendered as
   panels. Discoverability that costs no pixels when idle.
3. **Cursor plus a starter row.** A handful of literal example commands —
   *"why is NVDA down today"*, *"backtest my last idea"* — as buttons under the
   input. Teaches the *shape* of a request, which is what a new operator
   actually lacks.

**Recommendation: (2) and (3) together, and neither as a panel.** They occupy
the input's own space, disappear on the first character, and hold no data — so
the rule is intact. (1) is the trap this whole note was written about: the
current surface's problem is not that it shows too much, it is that it shows the
wrong thing and hides the right one.

Blocks the `home` category. Cheap to change afterwards.

> **Decision: (2) + (3) — recent work *and* example commands, 2026-09-06.**
> Both live in the input's own space and vanish on the first keystroke, so
> neither is a panel and the §3 rule is intact. Examples teach the *shape* of a
> request, which is what a new operator lacks; recents are the fastest path back
> to yesterday's work. Implemented in [[UI-0 Build Order]] step 2.

---

### 17. Name → ticker source — OPEN, blocking UI-0

[[Operating Model]] §7 requires deterministic name resolution. Which list?

1. **EDGAR `company_tickers.json`.** Already a provider in
   [[Company Data Model]], free, no key, authoritative for US issuers.
   ~10k names, refreshes daily, and it carries the CIK — which the filings path
   needs anyway. Misses ETFs, futures, and anything not SEC-registered.
2. **The exchange listing** (Nasdaq/NYSE symbol directories). Broader on ETFs,
   another fetch path to maintain, no CIK.
3. **The market-data vendor's own search endpoint.** One call, covers every
   instrument class, and it is a network round trip on the hot path of every
   spoken request — plus the vendor decides what "Nvidia" means.

**Recommendation: (1), cached locally, with futures handled separately.** Most
questions are about US equities, and the CIK it hands back is required by the
next hop regardless. Futures identity is its own unsolved problem — see §13 —
and folding it into name resolution would hide it.

Aliases the list will not have (*"the semis"*, *"spoos"*, *"my usual"*) belong
in a small hand-kept alias table, not in a model call.

> **Decision: (1) EDGAR `company_tickers.json`, 2026-09-06.**
> Already a provider here, free, no key, and the CIK it returns is required by
> the next hop regardless. Cached to disk, refreshed daily. ETFs and futures are
> **not** folded in — futures identity is §13 and hiding it inside name
> resolution would bury an unsolved problem. Aliases go in a hand-kept table.
> Implemented in [[UI-0 Build Order]] step 1.

---

### 18. Watchlist — Genesis's write access, and Screener universes — OPEN

The `WL` panel shipped ([[Watchlist Store]]): user-owned lists, sections,
tier-3 day change, pick-to-chart. Two gaps left open on purpose.

1. **Can Genesis edit a watchlist?** **Decided 2026-09-14: yes**, through a
   `watchlist` entry in `commands.py` — the trader's own list, edited only when
   the trader asks, so no approval step. Save the last screen or named tickers;
   auto-named; a named list that exists is added to. See [[Watchlist Store]]
   §Parity.
2. **Watchlist as a Screener universe.** [[Agent — Screener]] emits
   `universe: watchlist(52)` and lists watchlist as a universe source. Nothing
   wires the two yet. Blocked on §8 (universe size) as much as on §18.1.

No decision needed to keep shipping panels; needed before the Screener wiring.

### 19. Sentiment inputs and the morning brief — OPEN, blocking Sentiment

Data access was verified live on 2026-09-10 (see [[Agent — Sentiment]] §Data
access). Options, short interest, VIX term structure and headlines are free and
working. Social is not: Finnhub news/social sentiment is premium (403), Reddit
blocks the tradingview scraper, CNN Fear & Greed blocks bots.

1. **Headline scoring** — small-tier model (batched, cached by symbol+hour) or
   local FinBERT on the already-installed `onnxruntime` (no model call, one
   download)?
2. **Social feed** — pay later (Finnhub premium, StockTwits, Reddit OAuth), or
   make `degraded` (options + positioning + news) the permanent design?
3. **Digest context** — [[Agent — Digest]] calls `morning()` with no context, so
   no research reaches the brief. Fix: Digest reads overnight research from
   memory (`sentiment`, `regime`, `news-catalyst`) at 07:00. Needed before any
   research agent can appear in the brief.

### 20. Automation — who may author, and what a workflow may trigger — OPEN, blocking WB

[[Automation]] proposes answers to its own Q1–Q4. Three things it cannot settle
from the vault:

1. **May the orchestrator author a workflow?** Parity says the analyst drives
   the same routes the operator does. [[Safety Invariants]] #9 says loosening
   autonomy is a human act — and a standing workflow is standing autonomy.
   Options: (a) operator only; (b) orchestrator may draft, saved disabled until
   the operator enables it; (c) both, equally. **Recommend (b).**
2. **`event` triggers in v1?** The `Cadence` model allows them for free, but a
   workflow on a noisy event (`news.spike`) can flood the research lane.
   Options: allow; allow with a per-workflow min interval; defer.
   **Recommend defer** — cron and intervals cover every v1 case named.
3. **Where does a `gather` result go beyond the run record?** Options: run record
   only; also into the [[Research Directory]] as a sourced note. **Recommend run
   record only** — `run topic-researcher` already writes the directory, with
   sources, and a second writer would be a second answer to "what do we know".

### 21. Automation's node library — two calls for the operator — OPEN

The library shipped 2026-09-13 ([[Automation]] §Node library). Two nodes were
built on a reading of existing notes, not a decision:

1. **Add / remove watchlist symbols.** §18.1 says Genesis has no watchlist-write
   capability. These nodes write the trader's watchlists — but only from a
   workflow the operator enabled, so the act is the operator's, not the
   orchestrator's. Options: (a) keep; (b) remove until §18.1 is decided;
   (c) keep, but refuse them in orchestrator drafts. **Recommend (c).**
2. **Voice for alerts.** Alerts are stored and shown on the dashboard; the voice
   loop runs in another process and nothing carries `automation.alert` to it.
   Options: the voice loop polls `workflow_alerts`; or the daemon bridges the
   Episodic Log to the UI event bus and the voice loop subscribes. **Recommend
   the poll** — one query, no new transport.
