---
title: Market Data Plane
tags: [architecture, data]
status: built
implemented_by: [src/genesis/marketdata/normalize.py, src/genesis/marketdata/interface.py, src/genesis/marketdata/budget.py, src/genesis/marketdata/store.py, src/genesis/marketdata/staleness.py, src/genesis/marketdata/source.py, src/genesis/marketdata/build.py, src/genesis/marketdata/adapters/csv.py, src/genesis/marketdata/adapters/databento.py, src/genesis/marketdata/adapters/yfinance.py, src/genesis/marketdata/adapters/ibkr.py, src/genesis/marketdata/reconcile.py, src/genesis/marketdata/ibkr_live.py, ui/src/workspace/panels/account.tsx, src/genesis/server/broker_routes.py, ui/src/workspace/panels/broker.tsx, src/genesis/charting/source.py, src/genesis/charting/bars.py, tests/marketdata/, src/genesis/marketdata/__init__.py, src/genesis/marketdata/adapters/__init__.py, tests/charting/test_bars.py, tests/marketdata/__init__.py, tests/marketdata/test_adapters.py, tests/marketdata/test_budget.py, tests/marketdata/test_ibkr.py, tests/marketdata/test_ibkr_chain.py, tests/marketdata/test_ibkr_live.py, tests/marketdata/test_normalize.py, tests/marketdata/test_source.py, tests/marketdata/test_staleness.py, tests/marketdata/test_store.py, src/genesis/server/symbol_routes.py]
---

# Market Data Plane

How market data physically enters Genesis, where it lives, and how agents reach it.

[[Market Data Sources]] answers *how much do I trust this number*. This note
answers *who fetched it, when, and where is it stored* — and it exists because the
cheap answer and the expensive answer to that question differ by more than an
order of magnitude in running cost.

> [!important] Posture: batch-first, and that is not a compromise
> Genesis is an **analyst and advisor**, not an execution bot. The human is the
> trader. Its job is to arrive at insight — overnight, on a schedule, or on request
> — that leads to better decisions the next session. Its rare execution path
> ([[Execution Family]]) is a capability, not the workload.
>
> That framing settles the hardest question in this whole area: **v1 needs no live
> feed at all.** Closed bars, filings, macro series and calendars are enough to
> support every research agent in [[Research Family]], and closed data is the
> cheapest, most reliable, most backfillable, most storable data there is. Real-time
> is an *upgrade path* for [[Agent — Level Watcher]] and intraday
> [[Agent — Screener]] — not a prerequisite for anything.
>
> Concretely: the first working version of this plane is a cron job that fetches
> daily OHLC for a handful of symbols after the close and writes it to a file. Every
> section below is that idea taken seriously enough to run for years.

> [!note] Built 2026-09-04 — what exists, and what does not
> The plane is **built and running**: `normalize`, `interface`, `budget`,
> `store`, `staleness`, `source`, `build`, and the `csv` / `databento` /
> `yfinance` adapters, with 68 tests. `genesis chart <symbol> <timeframe>` draws
> a marked-up chart from stored bars, and a second run makes **zero network
> calls** — proven by a test that removes `socket` from the interpreter.
>
> **The IBKR adapter landed 2026-09-04** (Track C), alongside the headless
> gateway in `deploy/ib-gateway/` (Track B). It fits the Adapter Protocol with
> **no change above the interface** — which was the test of whether the
> Protocol was drawn in the right place, and it passed. Historical bars,
> contract qualification from the canonical symbol id, all three pacing rules,
> and a `keepUpToDate` streaming path that emits only *closed* bars.
>
> It is **tier 3**, not tier 1. See [[Market Data Sources]] — promotion needs
> `genesis ibkr reconcile` and a recorded tolerance.
>
> **Unproven against a live gateway.** No IBKR account credentials exist yet,
> so every IBKR test runs against a fake client. The code is real; the round
> trip is not yet evidence.
>
> Deliberately **not** built:
> - **No live ingest loop.** `stream_bars` exists and is tested; nothing
>   schedules it yet, and no supervised worker writes streamed bars.
> - **No `genesis-marketdata-mcp`.** The plane comes first; the tool façade is a
>   separate session, and the gateway's registered servers are untouched.
> - **No continuous contracts** until [[Open Questions]] §13 is answered.
>
> Two things the build learned that this note did not anticipate, both now in
> the code:
>
> 1. **Coverage must be recorded, not inferred.** "Do I hold this window?"
>    cannot be answered from the bars, because an empty answer is ambiguous — a
>    holiday and a never-fetched window look identical. Without a coverage
>    table, every ingest re-asks the vendor about every holiday forever, which
>    defeats *"never re-fetch"* precisely where a vendor is most likely to rate
>    limit for asking.
> 2. **Request windows must be quantised to the bar grid.** Every window ends at
>    `now`, so coverage recorded one second ago never covers the next call and
>    "never re-fetch" silently becomes "re-fetch every time". Snapping both ends
>    onto the timeframe's grid is correct rather than merely convenient: within
>    one bar period, no new bar can have closed.

## The mistake this note prevents

The natural reading of [[MCP Server Catalog]] is that market data is a **tool-plane**
concern: an agent wants a bar, an agent calls `market-data.ohlcv`, the gateway
routes it to a vendor's MCP server, the vendor answers. Seven research agents,
each with its own cadence, each calling out.

That design cannot be run for free, and the reason is arithmetic rather than
taste:

- **Free tiers are quotas, not rates.** Alpha Vantage's free tier is 25 requests
  per *day*. Seven agents asking questions during one overnight research pass
  exhaust it before the pass finishes.
- **N agents means N× the same fetch.** [[Agent — Screener]], [[Agent — Chart Markup]]
  and [[Agent — Regime And Correlation]] all want the same symbols' bars for the
  same session. On the tool plane that is three fetches of one fact.
- **Nothing accumulates.** A tool call answers a question and the answer is
  discarded. The private history that [[Market Data Sources]] promises — *"cache
  every closed bar; over months this becomes a private history that makes
  backtests free"* — never materialises, because no component owns doing it.
- **Rate-limit failures surface as agent failures.** A 429 from a vendor becomes a
  degraded [[Idea Schema|idea]] rather than a scheduling problem, which is the
  wrong place to fix it.

So: **market data is a data-plane concern with a tool-plane façade.**

## The shape

```
   ┌─────────── INGEST (daemon-scheduled, agent-free) ───────────┐
   │                                                              │
   │  adapters/           budget.py          normalize.py         │
   │  ├─ databento   ──┐   sliding windows    one bar schema,      │
   │  │   (history)    │   + cooldowns        one symbol id,       │
   │  ├─ yfinance    ──┼─► + daily quotas ──► UTC, Decimal,        │
   │  ├─ csv replay  ──┤   one gatekeeper     provenance stamped   │
   │  └─ ibkr (live) ──┘   per vendor                │             │
   │      ↑ Track C, built 2026-09-04                ▼             │
   └──────────────────────────────────────────  THE STORE  ───────┘
                                                     │
                          bars · reference · corp actions · calendar
                          fundamentals · macro · breadth · filings
                                                     │
   ┌─────────────────────────────────────────────────▼────────────┐
   │  genesis-marketdata-mcp   — the ONLY owner of market-data.*  │
   │  reads the store; derives levels/vol/breadth on the fly;     │
   │  falls back to a live adapter only when the store can't      │
   │  answer, and stores what it gets on the way back             │
   └──────────────────────────────────────────────────────────────┘
                                     │
              [[MCP Gateway]] allow-lists ──► research / charting agents
```

Three properties fall out of that picture, and they are the whole point:

1. **One place respects a rate limit.** `budget.py` is the only code that knows a
   vendor's quota. Agents never see a 429; they see a store that either has the
   answer or honestly does not.
2. **Every fetch is permanent.** Anything closed and immutable — a finished bar, a
   filed 8-K, a settled dividend — is written once and re-read forever. Cost per
   fact trends to zero.
3. **One canonical tool per capability.** [[MCP Server Catalog]] warns that
   `openbb-mcp`, `mcp-market-data-server` and `tradingview-mcp` all return quotes
   and bars, and that three competing `get_quote` variants make the router pick a
   defensible-but-wrong one. A data plane resolves that structurally: those servers
   stop being registered tools and become **adapters behind the store**. The
   registry contest disappears because there is only one candidate.

## The overnight pass is the product

Under the advisor framing, the daily loop below *is* Genesis working. Everything
else — voice, dashboard, on-demand questions — reads what this pass produced.

```
16:05 ET  corporate actions        splits/dividends first, always
16:15 ET  daily bars               one bulk pass, whole universe
16:30 ET  derive                   levels · vol · correlation · breadth · RS
17:00 ET  filings + news sweep     EDGAR RSS, publisher feeds, fenced
17:30 ET  research agents run      regime · screener · fundamental · sentiment
18:30 ET  Idea Synthesizer         ranked ideas, each citing its evidence
19:00 ET  vault write              50-Research/, charts marked up
06:45 ET  morning brief            overnight moves, today's calendar, spoken
```

Every step reads the store, not a vendor. The only network activity is the two
ingest rows, and both are bulk. A whole day of senior-analyst output costs a
handful of HTTP requests and some LLM tokens — and the LLM tokens, not the data,
are the larger bill. That inversion is the design working.

It also means the system's most demanding hour is 16:00–19:00 ET, when the market
is closed and latency is irrelevant. Nothing here needs to be fast. It needs to be
*finished by morning*, which is a far cheaper requirement to satisfy.

## Why the store is not the Memory Fabric

[[Memory Fabric]] holds what the system *believes* — ideas, lessons, episodes,
trades. The market data store holds what the world *did*. Different lifecycle,
different truth conditions, different size class.

| | Memory Fabric | Market data store |
|---|---|---|
| Content | beliefs, with confidence and half-life | facts, immutable once closed |
| Written by | agents | ingest jobs only |
| Corrected by | later evidence | vendor restatement (rare, logged) |
| Size | MB | GB and growing |
| Loss | expensive — it's the compounding | annoying — it's re-downloadable |

Concretely: **DuckDB over Parquet**, in `~/.genesis/market/`. Columnar, no server,
reads a year of minute bars in milliseconds, and the Parquet files are directly
readable by vectorbt and pandas — which matters because
[[Trading Corpus Index|the corpus]] is Python and
[[genesis-backtest-mcp]] should not need a translation layer. Bars partition by
`symbol / timeframe / year`. [[Trade Ledger]] stays in SQLite where it is; that is
a durability requirement, not an analytics one.

## Provenance is a column, not a convention

Every row carries `source`, `tier`, `as_of`, `ingested_at`, and `adjusted`.
[[Market Data Sources]] already requires that a tier-3 bar never silently satisfy a
tier-2 request; that requirement is enforceable only if the tier travels *with the
row* into storage. A cache keyed by tier is not enough once the data outlives the
cache.

This is also what makes [[Safety Invariants]] §10 checkable rather than aspirational:
an answer read aloud can always name its source and age, because the row it came
from carries both.

## Where it plugs into what exists

| New | Existing it attaches to |
|---|---|
| `src/genesis/marketdata/store.py` | — new |
| `src/genesis/marketdata/adapters/*.py` | — new, one per vendor |
| `src/genesis/marketdata/budget.py` | — new; quota state persisted, survives restart |
| `src/genesis/marketdata/normalize.py` | — new; the one bar/symbol schema |
| ingest jobs | `src/genesis/daemon/scheduler.py` cadences, `daemon/calendar.py` sessions |
| ingest supervision | `src/genesis/daemon/supervisor.py` — an ingest job is a supervised worker |
| `genesis-marketdata-mcp` | registered in `src/genesis/mcp/default_servers.yaml` |
| capability names | `src/genesis/mcp/allowlist.py` — `market-data.*` |
| failures | `src/genesis/errors.py` typed failures per [[Error Handling And Degradation]] |

Ingest jobs are **reflexes**, in the sense [[Biological Design]] uses: deterministic,
model-free, cheap, safe. No LLM is in the ingest path. That is not an optimisation —
a model in the ingest path would be a model that can invent a price.

## Capability surface

What agents actually get an allow-list entry for:

| Capability | Returns | Backed by |
|---|---|---|
| `market-data.ohlcv` | bars, any timeframe, adjusted or raw | store |
| `market-data.quote` | last / session H-L, with tier + age | tier-2 adapter, falling back per [[Market Data Sources]] |
| `market-data.levels` | VWAP, ORB, volume profile, FVG, prior-day H/L | **computed** from stored bars |
| `market-data.calendar` | sessions, holidays, earnings dates, econ prints | store |
| `market-data.reference` | symbol metadata, universe membership, splits, dividends | store |
| `market-data.breadth` | adv/dec, % above MA, new highs/lows | computed from stored bars |
| `market-data.vol` | realized vol, ATR, correlation matrix, regime stats | computed from stored bars |
| `market-data.fundamentals` | XBRL company facts, filing index | store (EDGAR) |
| `market-data.macro` | FRED series | store |

Note how many rows say *computed*. See [[Market Data Catalog]] §"Derive, don't buy" —
roughly half of what a vendor sells as a product is arithmetic over bars we already
hold. `news.*` and `web.*` are deliberately **not** in this table: they are untrusted
text, they belong to [[Agent — News And Catalyst]]'s allow-list, and they are fenced
by [[MCP Gateway]] rather than stored as fact.

## The fallback chain, restated for the plane

[[Market Data Sources]] gives each consumer an ordered chain. On the data plane
that chain resolves in one place — the MCP server — instead of inside each agent:

```
store hit (any tier ≥ minimum, fresh enough)
  └─ miss → tier-2 adapter (TradingView desktop, if a GUI session is up)
       └─ miss → tier-3 adapter (Alpaca delayed / Stooq / bulk EOD)
            └─ miss → typed failure. Never a guess.
  ↳ anything fetched here is written to the store on the way back
```

The [[Pre-Trade Risk Engine]] does not use this chain and does not call this server.
It reads the broker directly, tier 1 only, fail closed ([[Safety Invariants]] §3, §11).
Keeping the risk engine off the data plane entirely is what keeps the plane
*allowed* to be cheap and best-effort.

> [!note] SUPERSEDED 2026-09-04 by [[Open Questions]] §1 and §6 — the broker
> is IBKR, not Alpaca, and its feed is tier 1. Kept because the reasoning
> about sizing against a conservative price envelope still applies to any
> thin or delayed feed, and IBKR starts in delayed mode.
> The free-tier tier-1 question, and why it was already small
> Alpaca's free Basic plan is **IEX only** for real-time equities — about 2.5% of
> consolidated volume — with SIP available only at a 15-minute delay. Account state
> and positions are genuine tier 1; the *price* on the free plan is not a
> consolidated last.
>
> Under the advisor framing this stops being a blocking problem. Genesis proposes;
> the human executes in their own platform against their own live screen, which is
> the real tier-1 price. The free feed only has to be good enough for the risk
> engine to sanity-check the rare automated order — so: size against a conservative
> price envelope (a band around the thin last, widened by the feed's age) and reject
> rather than guess when the band exceeds the trade's stop distance.
>
> This resolves [[Open Questions]] §6's still-open tier-1 half at zero cost, and
> defers the buy-a-feed decision until automated execution is actually the workload.

## Failure modes worth designing for now

| Failure | Handling |
|---|---|
| Vendor quota exhausted | Budget refuses *before* the call; job reschedules to the next window; store still answers from history. Not an agent-visible error. |
| Vendor returns a restated bar | Detected on write (same key, different values). Old row kept, new row supersedes, both logged. Never silently overwritten — a changed history invalidates backtests. |
| Split not applied | The subtle killer. Corporate actions ingest runs **before** the daily bar job, and a bar job refuses to write across an unapplied split. See [[Market Data Catalog]] §4. |
| TradingView GUI absent (3am) | Tier 2 simply unavailable; chain falls to tier 3. Already anticipated by [[Market Data Sources]]. |
| Store corrupt / disk full | Ingest degrades to read-only; [[Agent — Watchdog]] alerts; live adapters still answer. |

## Build sequence

Fits inside [[Build Order]] Phase 3–4, after the [[MCP Gateway]] fence lands.

1. **The cron job, done properly.** Daily OHLCV for 5–30 symbols from Stooq or
   Alpaca, after the close, written to the store with provenance columns. No MCP
   server, no agents, no budget layer — a CLI command, a scheduler entry, and a test
   that reads the bars back. This is deliberately the small thing that already
   works; the value is that the schema and the provenance stamps are right on day
   one, because retrofitting them across a year of accumulated history is painful.
2. **Backfill + corporate actions.** Pull ten years of daily history for the
   universe in one pass, and make the split/dividend job run *before* the bar job.
   Exit criterion: a known historical split is correctly applied, verified against
   a chart. Now the store is worth something on its own.
3. **Budget + supervision.** Ingest becomes a supervised daemon job on the session
   calendar with persisted quota state. Exit criterion: a week unattended, no vendor
   limit tripped, store grows every session day and skips holidays.
4. **`genesis-marketdata-mcp` + derived capabilities.** Levels, vol, breadth and
   correlation computed from the store. Register as the sole owner of
   `market-data.*`; a test asserts no other registered tool claims those
   capabilities.
5. **Widen adapters** per [[Market Data Catalog]] priority order — EDGAR, FRED,
   calendar, news, then the optional lanes.
6. **Live data, only if wanted.** Quotes and intraday bars for a small hot ring.
   Nothing above changes shape; a tier-2 adapter is added to the fallback chain.

Only after step 4 does any research agent get a `market-data.*` grant. Building the
agents first would mean building them against a tool surface that is about to
change shape — and steps 1–3 are worth running for months before that, because the
history they accumulate is what makes the agents good when they arrive.

## Live session

`genesis serve` holds one read-only IBKR connection open while it runs
(`marketdata/ibkr_live.py`), for the series listed under `marketdata.live`.
The batch-first posture above still holds: this is a feed for the chart and
the account panel, not an input to any decision.

- **Backfill on every (re)connect**, from the last stored bar to now. Closing
  Genesis loses nothing inside IBKR's history window — the gap is pulled on the
  next start.
- **Closed bars are written; the forming bar is not.** It is pushed to the UI
  as `market.bar` with `closed: false` and drawn with `update()`, never stored.
- **Account balances and positions** ride the same connection and are pushed
  as `broker.account`; `ACC` renders them. Paper vs live is read from the
  account id IBKR returns (`DU…` is paper), not from the port.
- **In-process, not a recorder daemon**, because DuckDB allows one writer per
  file. A separate process would lock the UI out of the store.
- **Wedge defence** is the loop itself: no update for 180 s rebuilds the
  session (and re-backfills). Client id is the adapter's plus one.

Still tier 3. Promotion is unchanged: `genesis ibkr reconcile`.

The account is published the moment the login completes — before the
backfill, which can take minutes on a first run — with the session in state
`syncing` until the streams are up. `ACC`'s **refresh** reconnects the session
(filling any gap, resyncing the account) and runs the layered check.

**Connecting it from the UI** (`CON`, also the *setup* tab of `ACC`) is four
steps, each a door a person can also open by hand: save the login to
`~/.genesis/.env` (0600; the password is write-only), start the gateway
container (`docker compose up -d`), choose the live contracts and delayed or
realtime (`marketdata` in `~/.genesis/config.yaml`, applied to the running
session in place), and a layered test — login saved → container → socket →
logged in → bars. A bare root like `NQ` is refused with the reason (Open
Questions §13); the contract month is typed, e.g. `NQZ6`.

Series streamed by the session carry `live` on `/v1/market/symbols` —
`streaming` only while the session is actually live, `configured` otherwise —
and `SR` shows it as a badge. `LD` Live data lists *only* the configured
contracts (`feed.live` from `/v1/broker/settings`), with the delayed/realtime
mode on its header — shown before the first bar lands, and clicking one drives
`CH` like a Series row. `LD` also searches IBKR's contract directory
(`/v1/market/search` — `CL`, `GC`, `ES` list their dated months); clicking a
result saves the contract into `feed.live` through `/v1/broker/feed` and charts
it at the chart's timeframe; its `+` saves without charting (✓ once saved — a
contract is held once). A saved contract has **no timeframe of its own** — the chart is the only
timeframe control. Rows are one per symbol, like a watchlist; when `CH` sits on a
saved symbol at a timeframe that is not streaming, `LD` re-points that symbol's
stream to the chart's timeframe (debounced ~800ms, since each save reconnects the
session and backfills). ✕ removes the contract. Enter never adds the top
match — `CL` is also a stock. Kept apart from `SR`: the feed is not the store. Seeded
beside `CH` on Charting and into Trade under `ACC`; `SR` is seeded on Backtest. Once stored, a contract is found in ⌘K by its
root (`NQ`), because that list is the store's own series.

## Related

[[Market Data Sources]] · [[Market Data Catalog]] · [[MCP Gateway]] ·
[[MCP Server Catalog]] · [[genesis-tradingview-mcp]] · [[genesis-backtest-mcp]] ·
[[Daemon And Cadence]] · [[Memory Fabric]] · [[Pre-Trade Risk Engine]] ·
[[Biological Design]] · [[Open Questions]]
