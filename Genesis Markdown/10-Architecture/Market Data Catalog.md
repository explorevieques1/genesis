---
title: Market Data Catalog
tags: [architecture, data, moc]
status: building
implemented_by: [src/genesis/marketdata/universe.py]
---

# Market Data Catalog

What data Genesis actually needs, who consumes it, and the cheapest honest way to
get it. [[Market Data Plane]] is the machinery; this is the shopping list — and the
argument that almost nothing on it has to be bought.

> [!important] Read this list as an analyst's, not a bot's
> Genesis advises; the human trades. The question every row answers is therefore
> *what would a senior analyst need to have read by morning* — not *what does an
> execution engine need in the next 200 ms*. Those two lists barely overlap, and
> the analyst's list is the cheap one: **depth of history, breadth of coverage, and
> primary documents**, all of which are closed, free, and permanently storable.
> Latency, the expensive axis, is worth almost nothing here.
>
> Priorities below reflect that. Tick data and real-time options analytics — the
> only genuinely costly lanes — fall to the bottom, where they belong.

## The acquisition doctrine

Six rules, in priority order. Applied together they cover most of what the fleet
in [[Agent Index]] needs at close to zero recurring cost.

### 1. Prefer primary sources — they are free by mandate

The most valuable data in this system is published by governments and exchanges
because publishing it is the point. SEC EDGAR, FRED, Treasury, BLS, Cboe's daily
statistics, Nasdaq Trader's daily files. These are not free tiers that will be
withdrawn next quarter; they are public goods with stable formats and generous
limits. A vendor selling an "insider transactions API" is reselling Form 4.

This is the single biggest under-used lane, and it is the one that most suits an
advisor: primary documents are exactly what a senior analyst reads. [[MCP Server Catalog]]
names EDGAR and FRED; the exchange and Treasury files below are not in it yet.

### 2. Own the history

Bars are immutable once closed. Backfill once, store forever
([[Market Data Plane]]). After a few months of unattended ingest,
[[Agent — Regime And Correlation]], [[Agent — Backtest Runner]] and every strategy
evaluation run on a private dataset with no marginal cost and no vendor dependency.
The cost curve is front-loaded and then flat at zero — which is exactly the shape
you want for a system that is supposed to run for years.

The corollary is a scheduling rule with real consequences: **start collecting
before you need it.** Anything published as a daily snapshot and not archived by
its publisher — implied volatility, open interest, short interest, index
membership, analyst estimates — is backfillable only by buying it. A row you start
storing today is free; the same row a year from now costs money and may not exist.
Cheap daily snapshots of things not yet used are the highest-return line in this
whole design.

### 3. Bulk beats per-symbol

One end-of-day file for the whole market is one request. Iterating 500 symbols is
500 requests and burns a daily quota in minutes. Whenever a source offers a full
snapshot — Stooq's bulk archives, Nasdaq Trader's daily directory, Cboe's daily
statistics CSV — take the file, not the endpoint. This is what makes a
universe-wide [[Agent — Screener]] affordable at all.

### 4. Push beats poll

RSS/Atom is free, arrives when something happens, and needs no key. EDGAR publishes
filings as RSS; so does every financial publisher worth reading. A 5-minute poll of
a news endpoint is 288 requests a day to learn nothing 280 times.

### 5. Derive, don't buy

A large fraction of what "market data APIs" sell is arithmetic over OHLCV: VWAP,
ATR, RSI, Bollinger bands, opening range, volume profile, fair value gaps, realized
volatility, correlation matrices, relative strength, breadth. All of it is
milliseconds of local compute over bars already in the store. As
[[Market Data Sources]] puts it: computing levels is not the bottleneck, getting the
bars is.

This rule deletes most of the reason to run `mcp-market-data-server` and
`tradingview-mcp` as live tool dependencies — they become optional cross-checks
rather than sources of truth, and the routing-overlap problem [[MCP Server Catalog]]
warns about goes away.

### 6. Use the feed already paid for

TradingView Desktop is open all day on a live subscription. Reading it via
[[genesis-tradingview-mcp]] is tier 2 and costs nothing extra. Decided in
[[Open Questions]] §6; unchanged here — though under the advisor framing it matters
much less than it did, since the human is already looking at that screen.

> [!caution] Where scraping fits — narrowly, and last
> A headless browser is the *most* expensive acquisition method, not the cheapest.
> It costs a GUI session, breaks silently on every site redesign, carries
> terms-of-service risk, and is the widest possible prompt-injection surface.
>
> Use it for exactly two things: (a) driving TradingView Desktop, which is
> actuation of software we license, not scraping; and (b) one-shot retrieval of a
> specific known page that has no API and real value — a research note, a filing
> exhibit, an IR page — fetched on demand, fenced as `<untrusted>`, summarised
> before it touches the [[Vector Store]], and never a scheduled job. Prefer a
> search MCP with content extraction (exa/tavily, per [[MCP Server Catalog]]) over
> a browser: it returns structured results with source URLs, which makes the fence
> mechanical instead of an HTML-parsing exercise.
>
> A general scraping fleet is a maintenance liability disguised as free data. Do
> not build one.

---

## The catalog

Seventeen data types. **Priority** is build order within [[Market Data Plane]] step 5:
P1 = the advisor is crippled without it, P2 = a named agent is blocked, P3 = a real
edge but deferrable, P4 = only if automated intraday execution becomes the workload.

### 1. Daily OHLCV bars — P1

The substrate everything else derives from, and the whole of what v1 needs.

- **Consumers:** effectively all of [[Research Family]], [[Charting Family]],
  [[Strategy Family]], [[genesis-backtest-mcp]]
- **Free sources:** Stooq (decades of daily history, no API key, bulk downloadable —
  the best backfill source here); Alpaca daily bars (200 rpm, same account the
  broker adapter uses); yfinance as a gap-filler only — it scrapes unofficial
  endpoints and is rate-limited or broken without notice, so it may fill history but
  must never be a scheduled dependency.
  **Scoped 2026-09-04:** this warning is about **bars**, where a broker feed exists
  and the number moves money. For company reference data there is no better free
  source and the data is not time-critical, so [[Company Data Model]] makes
  yfinance primary for breadth with EDGAR authoritative for as-filed figures.
  The mitigation there is caching plus explicit guards, not abstinence
- **Cadence:** one bulk pass after the close
- **Tier:** 3 — entirely sufficient, because a closed daily bar is the same number
  from every source
- **Depth:** 10+ years. Depth is free here, and it is what lets
  [[Agent — Regime And Correlation]] say *this looks like 2018*.

### 2. Intraday bars — P3

5- and 15-minute; 1-minute only if a strategy genuinely trades on it.

- **Consumers:** [[Agent — Chart Markup]] for lower-timeframe context,
  [[Agent — Screener]] intraday scans
- **Free sources:** Stooq (delayed 5/60-minute); Alpaca (SIP at 15-min delay, which
  is free and *entirely fine* when the consumer is an evening research pass)
- **Cadence:** end-of-day pull of the whole session, not a live stream. A delayed
  feed and a closed session are the same data by 4:30pm.
- **Note:** this is where storage grows — a year of 1-minute bars for 500 symbols is
  ~50M rows. Trivial for DuckDB, but pull it for the watchlist, not the universe.

### 3. Quotes and session state — P4

Last, bid/ask, session high/low, VWAP-to-date, volume-so-far.

- **Consumers:** voice quote lookups, [[Agent — Level Watcher]]
- **Free sources:** TradingView desktop (tier 2, already paid for); Alpaca IEX
  websocket (free, real-time, thin)
- **Cadence:** on demand only — never stored as history, only a short-TTL cache
- **Tier:** 2, with the age stamp [[Market Data Sources]] requires
- **Why P4:** the human has a live chart open. Genesis answering "what's the price"
  is a convenience, not an insight — the one thing the trader can already see faster
  than they can ask.

### 4. Corporate actions — P1

Splits, dividends, symbol changes, mergers, spin-offs.

- **Consumers:** everything that touches history — silently corrupts every
  backtest, every level, and every 52-week high if missing
- **Free sources:** Alpaca corporate-actions endpoint; SEC filings; Nasdaq Trader
  daily list
- **Cadence:** daily, **before** the bar ingest job
- **Why P1 despite being unglamorous:** an unapplied 4:1 split looks exactly like a
  75% crash to [[Agent — Screener]] and exactly like a broken strategy to
  [[Agent — Backtest Vs Live Drift]]. Highest ratio of damage to effort in the
  catalog, and the most likely way an advisor confidently tells you something false.

### 5. Symbol reference and universe — P1

Listings, delistings, sector/industry, share count, index membership, tick size,
tradability and shortability flags.

- **Consumers:** [[Agent — Screener]] universe definition, [[Agent — Portfolio And Allocation]]
- **Free sources:** Nasdaq Trader daily symbol directory (bulk file, includes
  delistings); Alpaca `/v2/assets` (carries tradable/shortable, which is broker
  truth and therefore the right source for it)
- **Cadence:** daily
- **Why it matters:** delistings are how survivorship bias enters research. A
  universe built only from currently-listed symbols will always look profitable, and
  an advisor built on it will always sound smarter than it is.

### 6. Session calendar — P1

Market holidays, half days, early closes, the session clock.

- **Consumers:** [[Daemon And Cadence]] — infrastructure, not research
- **Free sources:** Alpaca `/v2/calendar`; `pandas_market_calendars` locally
- **Cadence:** yearly, refreshed monthly
- **Note:** already half-built at `src/genesis/daemon/calendar.py`; this is the data
  behind it. The overnight pass must not run at 16:05 on Thanksgiving.

### 7. Event calendar — P1

Earnings dates with before/after-market flags, economic prints with impact ratings,
Fed speakers, expiries.

- **Consumers:** [[Agent — News And Catalyst]], which owns the forward calendar
- **Free sources:** *economic prints* — **ForexFactory's weekly JSON**, no key,
  and the only free source that carries the **impact rating** rather than making
  us hand-maintain the list of which prints are red; *earnings* — Alpha Vantage
  free tier (25 requests/day, so budget it as a single daily bulk pull); FRED
  release calendar; the Federal Reserve's published schedule; EDGAR 8-K filings
  for confirmed dates
- **Cadence:** economic prints ride the [[Agent — News Collector]] run, capped at
  once every 6h; earnings a daily 06:45 ET sweep, matching that agent's cron
- **Why P1 for an advisor:** *"you're holding NVDA and they report tonight"* is
  the single most useful sentence Genesis can say, it requires no live data, and it
  costs one request a day. This is the cheapest high-value row in the catalog.
- **Built (economic prints only):** [[Economic Calendar]] — `EC`, the
  `econ_events` table in `news.db`, and the countdown in the status row. One
  rolling week of horizon, which is all the vendor publishes. Earnings dates,
  Fed speakers and expiries are **not** built.

### 8. Structural levels — P2, derived

Prior-day H/L/C, opening range, VWAP and bands, volume profile (POC/VAH/VAL),
fair value gaps, swing points, round numbers.

- **Consumers:** [[Agent — Chart Markup]], [[Agent — Level Watcher]], [[Agent — Screener]]
- **Source:** **computed** from §1 and §2. No vendor. Rule 5.
- **Cadence:** on demand, cached per symbol per bar close
- **Note:** for an advisor these are the *content* of the advice — "the level is
  122.10" is what you actually want to hear — and they cost nothing but arithmetic.

### 9. Volatility and regime — P2, derived

Realized vol at 10/20/60/120d, ATR, rolling correlation matrices, trend/range
classification, beta to benchmark.

- **Consumers:** [[Agent — Regime And Correlation]], [[Agent — Risk Metrics]],
  [[Risk Envelope]] sizing
- **Source:** computed from §1
- **Cadence:** daily after close; deep Sunday pass

### 10. Market breadth — P2, derived

Advance/decline, % of universe above the 50/200-day MA, new highs vs new lows,
up/down volume, sector relative strength.

- **Consumers:** [[Agent — Market Analyst]] ("what kind of market is it today?"),
  [[Agent — Regime And Correlation]]
- **Source:** computed from bulk daily bars across the whole universe — which is
  precisely why rule 3 matters. Breadth is unaffordable per-symbol and free in bulk.
- **Cadence:** daily
- **Note:** not currently an input to any agent, and it should be. Breadth is the
  cheapest available answer to the regime question and is derived from data being
  downloaded anyway.

### 11. Macro and rates — P1

Fed funds, the yield curve and its spreads, CPI, unemployment, credit spreads,
VIX and its term structure, DXY, oil, gold.

- **Consumers:** [[Agent — Market Analyst]], [[Agent — Regime And Correlation]],
  [[Agent — News And Catalyst]]
- **Free sources:** **FRED** (free key, effectively unmetered, hundreds of
  thousands of series, and the primary release itself); US Treasury daily yield
  curve; Cboe for VIX
- **Cadence:** daily; most series update far less often
- **Why P1:** it is the context every other read is interpreted in, it is ~30 series
  rather than 5,000 symbols, and it is completely free. An advisor with no macro
  context gives confident, narrow, wrong advice.

### 12. Fundamentals — P1

Revenue, margins, EPS, balance sheet, cash flow, share count, guidance history.

- **Consumers:** [[Agent — Fundamental]]
- **Free source:** **SEC EDGAR XBRL `companyfacts`** — every reported figure for
  every US issuer, as filed, free, no key, ~10 req/s with a declared User-Agent.
  This is the complete primary dataset that commercial fundamentals APIs resell.
- **Cadence:** on filing (driven by §13), plus a quarterly sweep
- **Tier:** 3, but uniquely so — it is the filing itself, not somebody's summary
- **Why P1 here and P2 for a bot:** an advisor is expected to know what a company
  *is*. This is the row that separates "the chart broke out" from "the chart broke
  out and the margin story supports it."
- **Built 2026-09-04:** [[Company Data Model]]. EDGAR remains the authoritative
  source for as-filed statements and is the **only** source of the filed date,
  without which every as-of query looks ahead. yfinance supplies the ~190 fields
  that are not in any filing — sector, market cap, float, ownership, analyst
  views. Neither replaces the other

### 13. Filings and insider activity — P1

8-K, 10-K/Q, S-1, 13-D/G, 13F, Form 4.

- **Consumers:** [[Agent — News And Catalyst]], [[Agent — Fundamental]], [[Agent — Sentiment]]
- **Free source:** EDGAR RSS (push — rule 4), the submissions JSON API, and
  full-text search
- **Cadence:** RSS poll a few times an hour; nothing here needs to be instant for an
  advisor
- **Note:** the filing text is a document; the *fact that it was filed* is structured
  data. Store the metadata as fact; fence the text as `<untrusted>`.

### 14. News and tone — P2, untrusted

Headlines, wires, source, timestamp, entity tags, tone.

- **Consumers:** [[Agent — News And Catalyst]], [[Agent — Sentiment]]
- **Free sources:** publisher RSS feeds (free, push, no key — the workhorse);
  Alpaca's news endpoint (free with an account); Alpha Vantage news-with-sentiment
  within its daily budget
- **Cadence:** an evening sweep and a morning sweep is enough for an advisor; tighten
  only around held positions and scheduled events
- **Tier:** 4. Never stored as fact. Never a numeric claim. Fenced at
  [[MCP Gateway]], summarised before the [[Vector Store]].

### 15. Positioning and sentiment — P3

Short interest, days-to-cover, put/call ratios, IV rank, skew, unusual options
activity, social volume.

- **Consumers:** [[Agent — Sentiment]]
- **Free sources:** Nasdaq Trader short-interest files (semi-monthly, bulk, free);
  Cboe daily market statistics (put/call ratios, free CSV); Alpaca's indicative
  options feed on the free plan
- **Derived:** IV rank and percentile need *history*, which vendors charge for and
  which rule 2 gives away — store the daily IV snapshot from day one and the rank
  becomes computable in a year. This is the clearest case of "start collecting
  before you need it."
- **Cadence:** daily
- **Note:** real-time options analytics (OPRA, live greeks, sweeps) is the one
  category with no honest free path. Deferred, not scraped around.

### 16. My own trade history — P1, and free

Every trade the human actually took: entry, exit, size, stop, the thesis at the
time, the outcome — and, crucially, **whether Genesis suggested it**.

- **Consumers:** [[Agent — Performance Analyst]], [[Agent — Trade Journal]],
  [[Agent — Insight Miner]], [[Agent — Backtest Vs Live Drift]]
- **Source:** broker statements, [[Trade Ledger]], and the human's own words at the
  time — captured by voice, which is what the voice loop is *for*
- **Cadence:** on every trade

This is the highest-value dataset Genesis will ever have, it costs nothing, and
**nobody else has it**. Every other row is available to every market participant;
this one is proprietary by construction. It is also the only data that can answer
the question the project actually exists to answer: *which of my decisions are
good, and which are habits?* An advisor that has read your last 300 trades is worth
more than one that has read the tape.

### 17. The advice ledger — P1, and unique to this design

Every insight, idea, level and warning Genesis produced — timestamped, with its
evidence, its confidence, and the forward outcome attached later.

- **Consumers:** [[Agent — Performance Analyst]], [[Agent — Insight Miner]], and the
  human deciding how much to trust the thing
- **Source:** generated by Genesis itself. [[Idea Schema]] already carries most of
  the shape; what is missing is the **outcome join** — a scheduled job that, N days
  later, marks what actually happened to each idea.
- **Cadence:** written on every idea; scored on a T+1 / T+5 / T+20 schedule

An advisor that cannot be graded is an advisor that cannot improve, and one you
have no principled reason to believe. This row turns Genesis from a thing that
generates opinions into a thing with a track record — and since ideas and outcomes
are both already in the store, the entire cost is one scheduled join. It is
probably the highest-leverage item in this document that nothing else in the vault
currently owns.

---

## Cadence and universe budget

Cost is decided here, not in the source list — and under an EOD posture it barely
decides anything, which is the point.

| Ring | Size | What it gets | Cadence |
|---|---|---|---|
| **Focus** | 5–30 — held positions and active watchlist | daily + intraday bars, full derived set, fundamentals, filings, news | nightly, deep |
| **Watch** | ~100–500 — screener universe | daily bars, derived levels and vol, corporate actions | nightly, bulk |
| **Universe** | full listed set | daily bars in bulk, reference, corporate actions, breadth inputs | nightly, one file |
| **Macro** | ~30 series | FRED, Treasury, VIX, rates | daily |

Promotion is a scheduling decision, not an agent decision: [[Agent — Screener]] runs
against stored watch-ring data overnight, and a hit promotes a symbol into the focus
ring for tomorrow's deep pass. That single rule resolves [[Open Questions]] §8
(universe size) as a *ring sizing* question rather than one number — and note the
whole thing runs at night, so ring size trades against wall-clock hours before
morning rather than against a rate limit.

## Estimated recurring cost

| Lane | Cost |
|---|---|
| Daily bars, reference, corporate actions, calendar (Stooq + Alpaca + Nasdaq Trader) | $0 |
| Fundamentals, filings, insider (EDGAR) | $0 |
| Macro, rates, VIX (FRED, Treasury, Cboe) | $0 |
| Breadth, levels, volatility, correlation, IV rank (derived) | $0 |
| News (publisher RSS + Alpaca news) | $0 |
| Event calendar (Alpha Vantage free tier, 25/day) | $0 |
| Positioning (Cboe daily stats, Nasdaq short interest) | $0 |
| Own trade history, advice ledger (self-generated) | $0 |
| Delayed intraday bars, pulled after the close | $0 |
| Quotes and session state (TradingView subscription) | already paid |
| Real-time consolidated SIP / OPRA options analytics | **not needed for v1** |

The last row is the whole argument. The only genuinely expensive data serves
intraday execution timing — which is the decision the human makes, on their own
screen, in their own platform. **Genesis's recurring data cost for v1 is zero**, and
the largest bill in the system is LLM tokens for the overnight pass, not data.

Revisit only if automated intraday execution becomes the workload rather than a
capability. At that point price Polygon or Databento against a *measured* cost of
delay — a measurement §16 and §17 will by then be able to produce.

## Open decisions

Candidates for [[Open Questions]]:

- **§6 tier-1 half — now answerable:** no feed purchase for v1. Advisor posture, EOD
  data, human executes. Record the decision so Phase 4 does not re-propose it.
- **§8 restated:** ring sizes above — are 30 / 500 / full right for a 7 GB machine
  running a nightly pass?
- **Retention:** keep 1-minute bars forever, or roll to 5-minute after two years?
- **Snapshot-now list:** which daily snapshots start immediately even though nothing
  reads them yet? Recommended: IV/open interest, short interest, index membership,
  and the full daily universe close. All cheap, none backfillable.
- **Advice-ledger scoring windows:** T+1/T+5/T+20, and what counts as "right" for an
  idea the human never took.

## Related

[[Market Data Plane]] · [[Market Data Sources]] · [[MCP Server Catalog]] ·
[[Research Family]] · [[Agent — Screener]] · [[Agent — Regime And Correlation]] ·
[[Agent — News And Catalyst]] · [[Agent — Sentiment]] · [[Idea Schema]] ·
[[Daemon And Cadence]] · [[Open Questions]]
