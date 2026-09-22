---
title: MCP List
tags: [mcp, intake]
status: reference
implemented_by: []
---

# MCP List

**The intake queue.** Servers found in the wild, and what happened to each one.

[[MCP Server Catalog]] is the decided catalogue — what Genesis uses and why.
This note is the step before it: a place to drop a repository URL without having
to decide anything yet, and a record of the decision once it is made. The two
are different jobs, and collapsing them means either the catalogue fills with
maybes or the maybes are lost.

**A row leaves this note when it is dispositioned.** Not when it is wired —
*"not usable, archived"* is a finished row too, and arguably the more valuable
kind, because it is the one that stops the same repository being rediscovered in
six months and researched again.

---

## Batch — 2026-09-03

Eight repositories, all market-data or broker adjacent. Every one is now
dispositioned in [[MCP Server Catalog]] and configured in
`src/genesis/mcp/default_servers.yaml`.

| Repository | Disposition | Where it went |
|---|---|---|
| [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) `mcp_server` | configured, off | `openbb`. `uvx --from openbb-mcp-server`. Gates its own surface by category — that flag is the real enforcement. |
| [financial-datasets/mcp-server](https://github.com/financial-datasets/mcp-server) | configured, off — 6 of 10 | `financial-datasets`. No PyPI package; launched from a clone. Four crypto tools out by [[Open Questions]] §1. |
| [sverze/stock-market-mcp-server](https://github.com/sverze/stock-market-mcp-server) | configured, off | `stock-market`. Finnhub, free tier, clone-launched. Value is as a **cross-check**, not a primary. |
| [barvhaim/yfinance-mcp-server](https://github.com/barvhaim/yfinance-mcp-server) | configured, off | `yfinance`. No auth at all, and no service agreement either. Tier 3, `untrusted` — a scraped consumer endpoint is not a data contract. Clone-launched. |
| [atilaahmettaner/tradingview-mcp](https://github.com/atilaahmettaner/tradingview-mcp) | **already wired** | `tradingview`, live since 2026-09-02. 5 of 73 tools — see the `execute_order` / `kelly_position_size` danger box in the catalogue. |
| [wshobson/maverick-mcp](https://github.com/wshobson/maverick-mcp) | configured, off — **11 of 52** | `maverick`. Screening and TA. **Sizes positions, keeps a portfolio, and backtests** — three separate invariant collisions, see below. |
| [wshobson/mcp-trader](https://github.com/wshobson/mcp-trader) | **not usable** | Archived 2025-08-24 by its author and superseded by maverick-mcp. Row kept so it is not rediscovered from an old bookmark. |
| [alpacahq/alpaca-mcp-server](https://github.com/alpacahq/alpaca-mcp-server) | configured, off | `alpaca`. Read half only, with **three independent locks** on the order path. Tool names were verified and four of the previously configured ones did not exist. |

### What the batch actually changed

**Three findings worth more than the servers themselves.**

1. **`mcp-trader` is archived.** The obvious-looking repository is the dead one;
   its successor is elsewhere in the same list. Two rows in one batch pointing
   at the same author, one of them a ghost.

2. **`alpaca-mcp-server` has `ALPACA_TOOLSETS`.** The server will decline to
   expose its own trading tools if told to. That is a stronger lock than
   refusing to catalogue them, because `place_stock_order` then does not exist
   on the wire and nothing downstream has to be careful. It also forced a real
   distinction into the config schema: `env:` for behaviour set from the file
   and committed to git, `env_keys:` for credentials read from the environment,
   and a hard error if one name appears in both. A safety decision living in a
   shell profile is a safety decision nobody reviews.

3. **The previously configured Alpaca tool names were wrong.** `get_stock_quote`,
   `get_stock_snapshot`, `get_account` and `get_positions` — four names that do
   not exist. It would have connected, registered one tool, and looked exactly
   like a server nobody uses. This is the failure `genesis mcp check`'s
   zero-tool warning exists for, and it had been sitting in the file since the
   server was first described from documentation rather than from a tool list.

### And one thing the batch nearly did

**maverick-mcp would have put position sizing on a third-party server.**
`portfolio_get_regime_adjusted_sizing`, `portfolio_risk_adjusted_analysis`
(ATR-based stops and targets), `portfolio_check_position_risk` —
[[Safety Invariants]] §3, which says a language model never sizes a position and
a number that decides how much to buy may not arrive over a socket from somebody
else's code.

Worth stating plainly: **none of those names contains a verb the discovery
tripwire catches.** "Sizing" and "risk" are not "order", "delete" or
"liquidate". Registered in bulk on a `read_only: true` claim — which is *true*,
none of them writes anything — all three would have entered the catalogue and
nothing would have fired. The explicit `tools:` block is what stopped it, which
is the whole argument for why a read-only claim does not buy bulk registration
on a server this large.

It would also have brought a second [[Trade Ledger]] (its portfolio store and
trade journal) and a second [[genesis-backtest-mcp]] (twelve backtesting tools).
Both are proprioceptive drift: two records of the same truth, and no way to say
which is authoritative.

---

## How a row gets dispositioned

The [[MCP Server Catalog]] integration checklist is the full version. In
practice, four questions decide almost every row:

1. **Does it write?** If yes, name every tool by hand. No exceptions.
2. **Does it compute anything that decides money?** Sizing, stops, risk
   arithmetic, position limits. If yes, that tool never registers, whatever the
   server claims about being read-only. [[Safety Invariants]] §3.
3. **Does it duplicate something Genesis owns?** A portfolio store, a trade
   journal, a backtester, a memory. Two records of one truth is worse than one
   record and a gap.
4. **How many tools does it ship, and how many are questions anyone asks?**
   Everything else is context rot, and the router cannot rank its way out of a
   catalogue where thirty tools are equally irrelevant.

Anything serving prices or fundamentals also lands on the **vendor bench** —
configured, disabled, and registered under `vendor-<id>.*`, a namespace no
allow-list grants — until [[Market Data Plane]] decides who owns
`market-data.*`. See [[MCP Server Catalog]] §the vendor bench.

## To add

*(Empty. Drop repository URLs here.)*

## Related

[[MCP Server Catalog]] · [[MCP Gateway]] · [[MCP Gateway Build Plan]] ·
[[Market Data Plane]] · [[Market Data Sources]] · [[Safety Invariants]] ·
[[Open Questions]]
