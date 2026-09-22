---
title: genesis-tradingview-mcp
tags: [mcp, charting, data]
status: built
implemented_by: [src/genesis/tradingview/cdp.py, src/genesis/tradingview/surface.py, src/genesis/tradingview/markup.py, src/genesis/tradingview/server.py, src/genesis/tradingview/selectors.yaml, src/genesis/tradingview/__init__.py, tests/tradingview/test_cdp.py, tests/tradingview/test_surface.py]
---

# genesis-tradingview-mcp

**Control of the TradingView Desktop app, and a read path into the live data
subscription already running inside it.**

TradingView is the primary charting surface — the app open on the desk all day,
with a paid live feed. Genesis runs alongside it rather than replacing it: it
drives the app the way a person would, and reads what the app already knows.

> [!note] Not the `TV` panel
> The UI's `TV` module ([[Charting Engine]]) embeds TradingView's *public*
> Advanced Chart widget in a panel — tier 3, no read path, no markup. This
> server drives the **Desktop app** over CDP to read your paid tier-2
> subscription and to put Genesis's [[Markup Spec]] on your real chart. Same
> vendor, nothing else in common.

> [!important] TradingView is a hand, not a brain
> Genesis computes its own levels ([[genesis-charting-mcp]]) and holds its own
> [[Markup Spec]]. This server *actuates* — it puts Genesis's conclusions on your
> screen and fetches quotes from a feed you already pay for. When TradingView is
> closed, agents keep working, degraded ([[Error Handling And Degradation]]).
> Nothing in the autonomous loop may hard-depend on a GUI being open.

## Why it exists

Two jobs that no headless server can do:

1. **Act on the app you actually use.** *"Open TradingView and mark key support and
   resistance on gold"* has to move your chart, not render a PNG in a folder.
2. **Read the feed you already have.** Real-time data is the project's most likely
   cost bottleneck ([[Open Questions]] §6). A live subscription is already running;
   *"what's the current high of day on NQ"* should read it rather than buy the same
   tick twice.

The second is about **data access and cost, not compute.** Computing levels from
an OHLCV frame is milliseconds — that is never the bottleneck. Getting the bars in
the first place is what costs money. See [[Market Data Sources]].

## Transport

TradingView Desktop is an Electron app. Launch it with a remote debugging port and
attach over the Chrome DevTools Protocol.

> [!success] Spike result: **YES** — verified 2026-08-30. Transport: **raw CDP**.
> The remote debugging port opens and a full CDP attach works against the live,
> signed-in app. This server is viable and [[Open Questions]] §11 stands.
>
> **Evidence** — TradingView Desktop 3.3.0, Electron 38.2.2, Chromium 140.0.7339.133:
> - `127.0.0.1:9222` reaches LISTEN ~4 s after launch.
> - `GET /json/version` returns `Protocol-Version: 1.3` and a
>   `webSocketDebuggerUrl`; UA is `... TradingView/3.3.0 ... TVDesktop/3.3.0`.
> - `GET /json/list` enumerates 11 targets, including the live chart page.
> - `Runtime.evaluate` on that page returned the active symbol (`NQ1!`) and 34
>   chart `<canvas>` elements; `Page.getLayoutMetrics` OK.
> - Browser-level `Target.getTargets` and `Target.setDiscoverTargets` OK.
>
> The app was signed in to the real account, so this is a read of the **live
> subscription session** — the tier-2 data path in [[Market Data Sources]], as
> intended.

### How to attach

Retrieve the websocket URL over HTTP, then open the socket directly. No browser
automation framework — see *What doesn't work* below.

```python
# browser-level endpoint
ver = requests.get("http://localhost:9222/json/version").json()
ws_url = ver["webSocketDebuggerUrl"]

# or a specific page (what the markup and read tools actually want)
targets = requests.get("http://localhost:9222/json/list").json()
chart = next(t for t in targets if "tradingview.com/chart" in t["url"])
ws_url = chart["webSocketDebuggerUrl"]

# then speak CDP over the socket: {"id": n, "method": ..., "params": {...}}
```

### Launching the app

> [!danger] `ELECTRON_RUN_AS_NODE` must be unset in the child environment
> **Symptom:** the launch fails with
> `/usr/bin/tradingview: bad option: --remote-debugging-port=9222`, and no port
> opens. This is indistinguishable at a glance from *"Electron disabled remote
> debugging"* — i.e. it looks exactly like the NO answer that kills this whole
> server.
>
> **Cause:** it is not TradingView. `ELECTRON_RUN_AS_NODE=1` is set in the VS Code
> extension-host shell (and any process inheriting it). With that set, the Electron
> binary runs as plain Node and parses `--remote-debugging-port` as a Node CLI
> option, which it rejects. You get a Node REPL where a chart should be.
>
> **Rule:** any Genesis process that spawns TradingView **must explicitly remove
> `ELECTRON_RUN_AS_NODE` from the child environment** — do not merely rely on it
> being absent from the parent. See [[Error Handling And Degradation]].
>
> ```python
> env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
> subprocess.Popen(["tradingview", "--remote-debugging-port=9222"], env=env)
> ```

### What doesn't work

**Playwright `connect_over_cdp` — tried and rejected.** The obvious client is not
the right one:

```python
playwright.chromium.connect_over_cdp("http://localhost:9222")   # hangs, do not use
```

It retrieves the websocket URL, connects the socket, and then hangs until the
180 s launch timeout. Playwright's browser-attach handshake disagrees with
Electron's target model. Raw CDP against the *same* browser endpoint succeeds in
milliseconds, so this is a client-library incompatibility, not a closed door.

Recorded here so Phase 3 does not spend an afternoon re-attempting it.

## Drawing: compile to Pine, don't simulate clicks

The obvious implementation — select the trendline tool, click two points — depends
on price→pixel math, pan position, and zoom state. It breaks constantly.

**Instead: compile the [[Markup Spec]] into a Pine indicator and load it through
the editor.** Every operation becomes text and keystrokes, which is the robust
surface. `compile_pine` already exists in [[genesis-charting-mcp]].

Three things fall out of this for free:

| | |
|---|---|
| **Your drawings are untouched** | Genesis owns exactly one indicator. You own your chart. Clearing its markup is removing one indicator, not hunting objects. |
| **Deterministic and re-renderable** | The same spec produces the same script — which is what level-outcome tracking in [[Knowledge Graph]] requires. |
| **One mechanism, both requests** | *"Mark S/R on gold"* and *"write me a Pine script for daily highs and lows on ES"* differ only in whether Genesis wrote the script from a spec or from your words. |

Lineage: [[Repo — gensis-agents]] `agents/alert-agent` for the condition
vocabulary, and `pine-forge` for the builder UI.

## Tools exposed

### Navigation
| Tool | Notes |
|---|---|
| `open_symbol` | Switch the active chart |
| `set_timeframe` | 1m … 1M |
| ~~`set_layout`~~ | **Not built, deliberately.** A saved layout is your personal, cloud-stored arrangement, and there is no read-back that says which one loaded — so it is an actuator with no matching sense, which is the configuration [[Biological Design]] calls dangerous. Nothing asks for it. Build it when something does, with a read first. |

### Markup
| Tool | Notes |
|---|---|
| `apply_markup` | [[Markup Spec]] → Pine → replaces Genesis's indicator |
| `clear_markup` | Removes **only** Genesis's own indicator |
| `write_pine` | A named script → editor → apply → save. Refuses a `strategy()` script (see hard rule 1) |
| `add_to_chart` | Apply a saved script by name, confirmed by the legend |
| `read_pine` | Read what is actually in the editor, so Genesis can fix a script that failed to compile |

### Read
| Tool | Returns |
|---|---|
| `quote` | Last, bid/ask, change, session high/low — the live-subscription read path |
| `ohlcv` | Bars for a symbol/timeframe, for local computation |
| `watchlist` | Your watchlist symbols |
| `screenshot` | Chart image — read-back verification, and vision input |

### Explicitly absent
**No tool touches the Trade panel.** See the hard rules below.

> [!success] Markup built — `src/genesis/tradingview/markup.py`, 2026-09-03
> `apply_markup` and `clear_markup` now work, and they work the way this note
> insists on: **compile, don't click.** The [[Markup Spec]] is compiled to Pine
> by `genesis.charting.pine` — the one compiler, shared with
> [[genesis-charting-mcp]] — then loaded through the editor and applied.
>
> **No price becomes a pixel anywhere in the path.** That is the property that
> makes this safe to run unattended-ish: a drag-based automation must convert a
> price to a screen coordinate using the chart's current scale, and every such
> conversion is a chance to draw a level at the wrong price, silently and
> authoritatively. Pine takes prices.
>
> **The write is verified, not assumed.** After applying, `markup.py` polls the
> chart's own legend for a source titled `Genesis Markup`. If it does not appear
> within 8 seconds the result is `degraded`, never `ok` — hard rule 2, and the
> reason the read half was built first. "I sent the command" is not perception.
>
> **`apply_markup` aligns the chart first.** Symbol and timeframe are set from
> the spec before the script loads. A markup applied to the wrong chart draws
> every level correctly against a completely different instrument, and looks
> entirely plausible — the worst available failure.
>
> **`clear_markup` compiles an empty indicator** rather than hunting for a
> remove button. One code path that can fail instead of two, and it cannot
> delete anything except the one script Genesis owns.
>
> The general-purpose script tools followed on 2026-09-19 — see below.

> [!success] Built — `src/genesis/tradingview/`, 2026-09-03
> Three modules, layered so only the top one needs a GUI: `cdp.py` (raw CDP
> over a hand-written WebSocket client), `surface.py` (the chart as a handful
> of operations, each write verified by a read-back), `server.py` (the MCP
> server, run as `genesis-tradingview-mcp`). 33 tests, none needing Electron.
>
> **Built:** `open_symbol`, `set_timeframe`, `quote`, `watchlist`,
> `screenshot`, `self_test`, `status`.
>
> **The markup tools were deferred here and are now built** — see the note
> below. The deferral was correct and the ordering paid off exactly as
> predicted: the read half became the read-back that verifies the write half.
>
> **The WebSocket client is hand-written**, ~100 lines that would otherwise be
> a dependency. The trade is worth making *here* and would not be in most
> places: the peer is Chromium on `127.0.0.1`, so there is no TLS, no proxy and
> no compression negotiation — the three hard parts of a general client are all
> absent. What is bought is a frame codec that is a pure function, testable
> exhaustively with no TradingView and no network, which matters more than
> usual because everything else in this server can only be tested against a
> running GUI.
>
> **Hard rule 1 is enforced three ways**, none of them a prompt: no tool takes
> a side, a size or an order as an argument; every expression is checked
> against a denied-surface list *before* it reaches the socket, matched on a
> normalised form so `trade panel`, `trade-panel` and `tradePanel` are one
> pattern; and `userGesture` is never set, so nothing can synthesise the click
> a broker widget requires. A test enumerates the tool surface and fails if an
> order-shaped tool or argument appears.
>
> **A bug this found:** the first version of the denied list spelled out
> `trade panel` and `trading-panel` and missed `trade-panel` — the spelling
> TradingView actually uses. A list of literal spellings is how a reflex
> develops a hole; normalising the input is how it stops.

> [!success] Complete — the script tools, `ohlcv`, and the latency pass, 2026-09-19
> **`write_pine`, `add_to_chart`, `read_pine` are built.** They drive the same
> editor `apply_markup` does, through the same four methods on `ChartSurface`,
> and they are verified the same way: the chart's own legend has to report the
> script by name or the result is `degraded`. The only difference between the
> two paths is whether the Pine came from `compile_pine` or from words — which
> is what this note meant by *one mechanism, both requests*.
>
> **A second door to a broker, closed.** Hard rule 1 was written about the
> Trade panel because until these tools existed the panel was the only way in.
> It is not: a Pine **`strategy()`** script can be connected to a TradingView
> broker integration and traded, and the source now arrives as text a model
> composed. `surface.refuse_strategy` matches `strategy(`, `strategy.entry`,
> `.order`, `.exit`, `.close`, `.cancel` on the source **before** it reaches
> the socket, and raises the same fatal `ForbiddenSurface` the trade-panel
> reflex does. It sits in `write_pine_source` — the one function every script
> passes through — rather than in each caller, because a guard per caller is
> one new caller away from a hole. Genesis draws indicators.
>
> **`ohlcv` is built**, through the widget's own `exportData`. This is the
> second reason the note gives for the server existing: the compute is
> milliseconds, the *bars* are what cost money, and a subscription is already
> running in the app. Still tier 2 — hard rule 3 is unchanged.
>
> **Latency, on the path a person waits on.** `quote` was three socket round
> trips (symbol, timeframe, quote); it is now one page evaluation returning
> all three. And a held CDP session dies silently when you restart the app,
> which used to spend the next call: ask, get `unavailable`, ask again, get an
> answer. Every tool now drops and reconnects **once** before reporting
> unavailable, so a restart is invisible rather than flaky. Retried once only —
> if the app really is closed the second attempt fails on the HTTP probe in
> milliseconds.
>
> **A bug this found, and it was the important kind.** The `_guarded`
> decorator rebuilt each tool as `wrapper(*args, **kwargs)`, so *every tool in
> this server published an `args`/`kwargs` schema* — none of them was callable
> by a model, and the test that enumerates the tool surface passed anyway
> because a schema with no real arguments has no order-shaped argument in it.
> A safety test that is vacuous reports safety. `functools.wraps` fixes the
> schemas; the test now fails if a tool ever exposes `args`/`kwargs` again.

## Hard rules

### 1. Nothing here can reach a broker
TradingView Desktop has broker integration. An automation server that can click is
an automation server that can click **Buy** — a path around
[[Pre-Trade Risk Engine]], which [[Safety Invariants]] §1 forbids structurally.

Enforced at the tool surface, not by prompting: no order tool is defined, the
Trade panel is a denied selector, and any action resolving into it aborts and logs.
Orders go through [[genesis-execution-mcp]]. Only.

### 2. Verify every mutation by reading back
The app is a black box. Act → `screenshot` → confirm the expected state. A
mismatch reports `degraded`; it never reports success.

### 3. Never the risk engine's price source
A quote scraped from a GUI is fine for answering *"what's the high of day"*. It is
not fine for sizing a position or evaluating a stop. [[Pre-Trade Risk Engine]]
uses the broker's own feed, always. See [[Market Data Sources]].

### 4. Degrade, never block
TradingView closed, updated, or unresponsive → the tool returns `unavailable` and
the agent proceeds without it. The headless renderer in [[genesis-charting-mcp]]
covers vault notes, journal snapshots, and vision input at 3am when no GUI is
running.

## Fragility budget

This server automates someone else's UI. It **will** break on their updates. Design
for that:

- Every selector in one config file, not scattered through the code
- A `self_test` tool that exercises each interaction and reports what broke
- [[Agent — Watchdog]] runs it on a schedule and after any TradingView update
- Failures are `degraded`, never `fatal` — nothing in the execution path depends
  on this server

## Access

Allow-listed to [[Charting Family]], [[Agent — Market Analyst]],
[[Agent — Strategy Author]], and the [[Orchestrator]] for direct voice commands.
**Never** to [[Execution Family]].

## Acceptance criteria

- The CDP spike is recorded above with a definite yes/no.
- `apply_markup` renders a spec onto the live chart, and `clear_markup` removes it
  without disturbing any hand-drawn object.
- `quote` on a liquid symbol matches the app's displayed value.
- With TradingView closed, every allow-listed agent still completes its task and
  reports `degraded` — no exceptions, no hangs.
- No defined tool can reach an order path. Asserted by a test that enumerates the
  tool surface — including that each tool publishes its real arguments, without
  which the assertion is vacuous.
- No `strategy()` script can be written to the editor. Asserted on the source,
  before it is sent.
- `self_test` detects a deliberately renamed selector.
- A voice request — *"mark support and resistance on gold and tell me the long-term
  trend"* — moves the chart and returns a spoken synopsis.

## Related

[[Market Data Sources]] · [[genesis-charting-mcp]] · [[Charting Engine]] ·
[[Markup Spec]] · [[MCP Gateway]] · [[MCP Server Catalog]] ·
[[Safety Invariants]] · [[Agent — Chart Markup]] · [[Agent — Strategy Author]] ·
[[Repo — gensis-agents]]
