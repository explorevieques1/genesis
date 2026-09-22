❯ i want to build a system in genesis that allows me to query infromation about stocks includin the proce infotmation on a daily chart. information aout the comapny upcoming earnign etc. this is a bit different than than the futures data that i prefer to see live. since i rarely trade stocks below a daily time frame the chart only needs to show daily closes. this is i will yfinance or other libraries. i want there to be a search bar genesis that allows me to save specific symbols to mt watchlist. the stock proce data collection can be more simple and less granular than futures beacsue i rarely trade stocks or nouted to go below a 1 day chart. its more about news about the company, upcoming earnings, etc rather than futures data doest have that. so we need to plan to plan out the system to query information about a specific company so that genesis has it and i can also view it.

  Listed 1 directory, ran 13 shell commands

Read the vault and the repo. Memory was stale — you're well past Phase 1: Phase 3 complete (103 tools, 14 servers), Phase 4 in progress (Charting Family + Journal Family built; Research Family not started). Updating that note at the end.

Here's the good news first: most of what you're asking for is already wired. The 2026-09-03 correction in Build Order.md — "market data was doing too much work as a phrase" — already un-gated exactly this. You have, free, keyless, live today:

┌─────────────────────────────────────────┬────────────────────────────────────────────────────────┐
│              What you want              │                     Already there                      │
├─────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ 20y of daily bars                       │ yfinance → market-data.ohlcv, into the DuckDB BarStore │
├─────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ Upcoming earnings + confirmed/estimated │ openbb → calendar.earnings                             │
├─────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ Consensus / forward EPS / price targets │ openbb → analyst.*                                     │
├─────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ Company news                            │ yfinance → news.company; Finnhub for market-wide       │
├─────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ 8-K, 10-Q, Form 4                       │ sec-edgar                                              │
├─────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ Dividends, splits, statements           │ yfinance / openbb                                      │
└─────────────────────────────────────────┴────────────────────────────────────────────────────────┘

The YFinanceAdapter also already refuses FUT outright, on purpose — so the equity path and the futures path can never contest a symbol. Your "stocks are different from futures" instinct is already structural in the code.

So this isn't a data problem. Four things genuinely don't exist.

1. The watchlist is referenced everywhere and specified nowhere

Grep finds it in 15 places — config.universe: watchlist, 70-Watchlists/ in the vault schema, Screener, News & Catalyst, Fundamental all read "the watchlist" — and no note owns it and no code implements it. That's the first thing to build, and it's the thing your search bar writes to.

It's a belief/preference, not market data → SQLite in the Memory Fabric, not the DuckDB store. tier: none, pure reflex, no model anywhere near it.

watchlist(symbol_id, added_at, source: manual|screener|agent, tags[], note, active)

Two sub-pieces:
- Symbol resolution — "apple" → AAPL. Deterministic, a cached local symbol table, never an LLM. This is what makes the search bar feel instant.
- Bootstrap import — genesis-tradingview-mcp already has a working watchlist read tool. Your existing TradingView watchlist imports in one call on day one.

Mirrors to Obsidian 70-Watchlists/ per Obsidian Vault Schema.md.

2. The Company Dossier — one symbol, one assembled record

The piece that turns nine scattered tools into "Genesis knows about NVDA." A new 70-Schemas/Dossier Schema.md + src/genesis/research/dossier.py.

Crucially: this is an afferent nerve, not a judgement organ. Per Biological Design §reflex arc, the assembler is tier: none — it fetches, normalises, fences untrusted text, stamps freshness, and stops. It forms no opinion. That keeps it out of the "do not add agents in Phase 4 beyond the five listed" rule, and it means Agent — Fundamental (Phase 10) later reads the dossier rather than re-plumbing it.

Per-field staleness, because these age at wildly different rates:

┌───────────────────────────┬─────────────────────────────────────────────────────┐
│           Field           │                         TTL                         │
├───────────────────────────┼─────────────────────────────────────────────────────┤
│ Daily bars                │ until next close                                    │
├───────────────────────────┼─────────────────────────────────────────────────────┤
│ Profile / sector / mktcap │ 30d                                                 │
├───────────────────────────┼─────────────────────────────────────────────────────┤
│ Next earnings date        │ 6h (it moves, and confirmed→estimated flips matter) │
├───────────────────────────┼─────────────────────────────────────────────────────┤
│ Consensus / targets       │ 24h                                                 │
├───────────────────────────┼─────────────────────────────────────────────────────┤
│ News, filings             │ 15m                                                 │
└───────────────────────────┴─────────────────────────────────────────────────────┘

3. Cadence — your "daily only" constraint is a real saving, so make it explicit

Market Data Catalog.md already defines a Focus tier: 5–30 symbols, held positions and active watchlist, nightly and deep. Your watchlist is that tier. Write it down as: EQ symbols fetch 1D only, no intraday backfill, ever. One nightly market-closed pass over the watchlist. That also answers Open Question §8 (universe size), which is still blank — the answer is "the watchlist, ~30."

4. The UI — and this is the honest tension

The UI today is Phase 6 UI-1: fleet graph, event stream, safety floor, kill switch. No Dockview, no lightweight-charts, no read API for bars. UI Stack.md already picked TradingView Lightweight Charts for price and Dockview for panels, and Widget Catalog.md already lists "Ticker manager → Watchlist" as portable from Gensis Terminal Official.

So a search bar + daily chart is a deliberate UI-2 pull-forward, and it needs one thing that doesn't exist: a read path from the daemon to the UI. The WebSocket bridge in transport/live.ts is push-only telemetry; asking "give me 500 daily bars for NVDA" is a request/response.

Scope it to one panel, not the Dashboard: search bar → watchlist rail → daily-close chart → company card (next earnings, consensus, last 5 headlines, recent filings).

---

Build order I'd propose

1. Watchlist store + symbol resolution (reflex, SQLite, TradingView import) — nothing else can start
2. Dossier assembler over the already-wired tools, with per-field TTLs and fencing
3. genesis-research-mcp — ~6 curated tools (watchlist_add/remove/list, resolve_symbol, dossier, earnings_next). This is what makes "Genesis, when does NVDA report?" work by voice, with no UI at all. Watch the curation rule — 6 tools, not 30.
4. Nightly focus-tier refresh on the existing daemon
5. Agent — News And Catalyst — it's already spec'd, it's on the Phase 4 list, and it's exactly your "news about the company, upcoming earnings" ask. It owns the forward calendar.
6. UI: read API + the one Symbol panel

Steps 1–4 are one Claude Code session. Step 5 is its own. Step 6 is its own.

---

Four decisions that are yours, not Claude Code's

These go in Open Questions.md rather than getting guessed at:

- §8 universe size — confirm "watchlist, ~30, focus tier only"?
- Is the Genesis watchlist authoritative, or a mirror of TradingView's? One-way import at bootstrap is easy; continuous two-way sync is a whole reconciliation problem. I'd say: import once, then Genesis owns it.
- Pull Agent — Fundamental forward from Phase 10? I'd say no — take the deterministic dossier now, add judgement later. But "is NVDA expensive?" won't be answerable until you do.
- UI now or headless first? Steps 1–5 give you the whole thing by voice and in Obsidian with no UI work at all. The panel is real work (read API + Dockview + charts).

Want me to write the three new vault notes (Equity Watchlist, Dossier Schema, plus the Market Data Catalog focus-tier amendment), or go straight to the paste-in Claude Code prompt for steps 1–4?

  Ran 1 shell command

❯ essetially what i want to do is give genesis the full power of yfinance python library how will i do this

  Ran 5 shell commands

Verified against your venv: yfinance 1.7.0 is installed in .venv, and the library exposes roughly 50 distinct data surfaces. Genesis currently reaches 9 of them.

The bottleneck isn't yfinance — it's the third-party server in front of it

- id: yfinance
  command: uv
  args: ["--directory", "~/.genesis/mcp-servers/yfinance-mcp-server", "run", "main.py"]
  trust: untrusted

That's somebody else's MCP server wrapping the library. It offers 10 tools, you registered 9, and you can't add an eleventh without forking it. Everything below is in the library and unreachable through it today:

┌──────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────┐
│       Missing surface        │                                        yfinance API                                         │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ Next earnings date + history │ calendar, earnings_dates ← your core ask, and the 10-tool server has no clean version of it │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ Forward estimates            │ earnings_estimate, revenue_estimate, eps_trend, eps_revisions, growth_estimates             │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ Analyst detail               │ analyst_price_targets, upgrades_downgrades, recommendations_summary                         │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ Insiders                     │ insider_transactions, insider_purchases, insider_roster_holders                             │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ Ownership                    │ institutional_holders, mutualfund_holders, major_holders                                    │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ Filings                      │ sec_filings                                                                                 │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ Statements, properly         │ quarterly / TTM / as-reported variants, valuation_measures                                  │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ Options                      │ options, option_chain                                                                       │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ Discovery                    │ Search, Lookup, Sector, Industry, Market, screen + EquityQuery                              │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ Fast path                    │ fast_info (no full info payload)                                                            │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
│ Live                         │ WebSocket, live                                                                             │
└──────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────┘

Note eps_revisions and growth_estimates — those are forward numbers, and MCP Server Catalog.md currently says "yfinance has analyst recommendations; it has no forward numbers" and hands analyst.* to openbb on that basis. That claim is now false in yfinance 1.x. Worth correcting in the note either way.

But "full power" as 40 MCP tools is the one move the vault has already measured as wrong

MCP Gateway §2, demonstrated on your own config: curating FRED from 33 tools to 5 turned selection from wrong to right, because a server's keywords are equally true of all of it and 33 tied tools fell to alphabetical order. Registering 40 yfinance tools would be the largest server in your catalogue and would degrade every other lookup in it.

So: two surfaces, and only one of them is MCP.

Surface 1 — in-process Python. This is where "full power" actually lives.

A first-party src/genesis/research/yahoo.py that imports yfinance directly and has 100% of the library, forever, with no curation tax — because a Python function call costs zero context. This is the Dossier assembler from the plan above. tier: none, pure reflex, no model in the path.

insider_transactions, eps_revisions, institutional_holders, upgrades_downgrades, option_chain — all of it goes into the dossier record via deterministic code. Nothing is gated on whether a tool description would rank well in a router.

This is also where the library's real ugliness gets absorbed once, in one place: yfinance returns pandas DataFrames with inconsistent orientation and shifting column names, raises differently per endpoint, silently returns empty on a bad ticker, and rate-limits by IP with no warning. Your YFinanceAdapter already handles that for bars — same treatment, wider.

Surface 2 — MCP, and stay small

Replace the third-party server with a first-party genesis-research-mcp, ~8 tools over the dossier, plus the watchlist tools from the plan:

dossier(symbol, sections=[...])   one call, model asks for the slice it wants
earnings_next(symbol)             calendar + confirmed/estimated + BMO/AMC + consensus
estimates(symbol)                 the five forward-estimate surfaces, merged
ownership(symbol)                 insiders + institutions, merged
resolve_symbol(query)             Search/Lookup, deterministic
watchlist_list / add / remove

sections= is the trick: one tool with a parameter beats eight tools with keyword contests, and the router only has to get one ranking right.

Three things to decide before it's built

1. The capability handover. Registry dedup refuses two tools claiming one capability at one tier — it raises at start-up, so the system won't boot. Moving analyst.* from openbb to first-party yfinance, or claiming screen.* with EquityQuery against maverick's, has to be settled by hand in MCP Server Catalog.md's ownership table first.
2. Options. option_chain is a genuinely large surface and you said you rarely go below daily. Fetch it into the dossier or leave it out of v1? I'd leave it out.
3. WebSocket / live. yfinance now streams. Market Data Plane.md says "v1 needs no live feed at all", and your futures live path is a separate concern — I'd hold the line and not wire it.

And the one thing that does not change: the FUT refusal in YFinanceAdapter stays. Yahoo's ES=F is a continuous front-month with an undocumented roll, and the docstring in that file is right that it's the most dangerous kind of wrong answer. Full power over equities, still zero futures.

---

That reshapes the earlier build order slightly — step 2 (dossier) gets bigger and step 3 (genesis-research-mcp) now replaces a server rather than adding one. Want the paste-in Claude Code prompt for steps 1–3 on that basis?