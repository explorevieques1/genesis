---
title: MCP Gateway Build Plan
tags: [mcp, plan, phase-3]
status: built
implemented_by: [src/genesis/mcp/]
---

# MCP Gateway Build Plan

The Phase 3 construction plan for [[MCP Gateway]]. The gateway note says *what the
thing is*; this one says *what gets built, in what order, and what proves each
step*. Read [[MCP Gateway]] first — this is not a substitute for it.

## What it is, plainly

**One chokepoint between every agent and every tool.** Nothing in Genesis calls an
MCP server directly. An agent asks the gateway, and the gateway decides whether the
call is allowed, which session it goes down, whether the answer is already cached,
and how the result is wrapped before a model is permitted to look at it.

In [[Biological Design]] terms it is the **peripheral nervous system plus the
blood-brain barrier** — every sense and every hand plugs into it, and it is the
membrane deciding what is allowed through in each direction. It is almost entirely
reflex: allow-list checks, fencing, cache lookups and session dispatch are
deterministic code, and none of them may be talked out of firing.

Two things make it more than plumbing.

### 1. It solves context rot

MCP makes adding servers trivial. [[MCP Server Catalog]] lists ~25 of them —
easily 200+ tools. Put 200 tool schemas in an agent's context and the agent gets
*worse*: reasoning quality drops and it starts picking defensible-but-wrong tools.
Adding a useful server actively harms the system.

The router fixes this by showing each agent ~8 relevant tools for the task at hand
instead of all 200. [[MCP Gateway]] calls this the single most important design
decision in the gateway, and it is right — it is what makes "unlimited MCP servers"
a real capability rather than a slogan.

### 2. It is where the security boundary physically lives

- **Per-agent allow-lists.** Each agent declares its tools in its [[Agent Contract]]
  YAML. The gateway *enforces* it — a call outside the list is rejected before it
  reaches any server. The agent that ingests the most untrusted text in the system
  is structurally the furthest from the money, and no prompt injection can change
  that because the restriction lives outside the model.
- **The fence.** Everything from web, news, social or any third-party server comes
  back wrapped in `<untrusted source="..." retrieved="...">`, and every agent prompt
  states that text inside those tags is data, never instruction. Same reflex-arc
  logic as the voice kill phrase in [[10-Architecture/Voice Stack]]: safety a
  persuasive prompt cannot argue with.

Everything else in Phase 3 — the servers, Alpaca, TradingView — is downstream of
getting that pipe right.

## Constraints found in the existing code

Three things that shape the build, recorded here so they are not rediscovered late.

1. **The codebase is threaded; the MCP Python SDK is asyncio-only.** There is no
   `asyncio` anywhere in `src/genesis` — [[Task Bus]], [[Daemon And Cadence]],
   [[Orchestrator]] and the voice loop are all threads. The runtime therefore needs
   a single event loop confined to one owned background thread behind a
   **synchronous façade** (`gateway.call(...)` blocks). This is a step-1 decision;
   discovering it at step 3 is a painful refactor.
2. **Alpaca is integrated by half.** `alpaca-mcp-server` exposes order placement in
   the same server as market data. Registering it whole puts a `place_order` tool in
   the catalogue three phases before [[Pre-Trade Risk Engine]] exists — exactly what
   [[Safety Invariants]] §1 forbids. The registry allow-lists **tool names, not
   servers**, and a test enumerates the registered surface and fails if any mutating
   Alpaca tool appears.
3. **The fence and the allow-lists ship before any web-facing server.** This is why
   [[Build Order]] Phase 3 reads *gateway, then servers*. Wiring general web access
   before enforcement exists puts untrusted text one hop from an agent that has no
   business reading it.

## Component steps

Each ends with something testable. Dependency order.

| # | Component | What lands | Exit |
|---|---|---|---|
| **1** ✅ | Tool descriptor + registry | `ToolSpec` (id, server, capability, schema, trust, mutating, cache policy), an `mcp_servers.yaml`, capability dedup | 100+ tools register from config; dedup test proves one owner per capability |
| **2** ✅ | Allow-list enforcement | Deny-by-default resolution from agent YAML, rejection *before* dispatch | Per-agent test: [[Agent — News And Catalyst]]→broker rejected, [[Agent — Order Manager]]→web rejected. Mutating-Alpaca test fails loudly |
| **3** ✅ | Persistent runtime | Async loop on an owned thread + sync façade, per-server queue, one silent reconnect, typed errors, idle timeout, health probe | Kill a server mid-call → silent reconnect; kill twice → typed `MCPServerSessionError`; [[Agent — Watchdog]] sees health |
| **4** ✅ | The fence | `<untrusted>` wrapper, injection detector + trust scoring, SSRF guard | Prompt-injection eval set: zero injected instructions executed |
| **5** ✅ | Router + `toolSearch` | Selection by task type and description, per-reply cap on the escape hatch | Selection-accuracy eval; adding 50 tools changes latency <10% and does not degrade tool choice |
| **6** ✅ | Cache + call path assembly | Bar-boundary keying, `degraded` labelling, [[Episodic Log]] entry per call with latency and cost | Cache hit rate on market data above 60% in an active session |
| **7** ✅ | Wire the first servers | time, filesystem, Obsidian, git, fetch, exa, tradingview, sec-edgar, fred, markitdown, arxiv, github — each through the [[MCP Server Catalog]] integration checklist | Real calls return real data, fenced and logged |
| **8** ◐ | [[genesis-tradingview-mcp]] | CDP transport — the [[Build Order]] Phase 0 spike came back **yes**, verified 2026-08-30, raw CDP, TV Desktop 3.3.0 | Read and navigation built; markup waits on [[genesis-charting-mcp]] |

### Status — 2026-09-02: steps 1–3 built

`src/genesis/mcp/`, 59 tests. The registry catalogues by capability with tier
dedup and refuses mutating tools; allow-lists are enforced before dispatch and
deny by default; sessions are long-lived, serialized per server, reconnect once
silently and then fail typed.

**The asyncio decision, made and settled.** One event loop on one daemon thread
owned by `runtime.py`, with sessions held open in per-server *keeper* tasks and
a synchronous façade (`GatewayRuntime.call` blocks). Async never leaks past that
file. The alternative — making the fleet async — was a rewrite of Phase 1 to
accommodate a Phase 3 dependency.

**Three decisions the spec did not settle**, each now recorded in the note it
belongs to:

1. **Allow-list entries are capability patterns**, never server or tool names.
   See [[MCP Gateway]] §entries. The mixed reading was ambiguous in the
   dangerous direction.
2. **A read-only claim does not cover a dangerous verb.** A test that injected
   `place_order` into every shipped server found that `read_only: true` bulk
   registration would catalogue it. Now a name-level tripwire refuses it. See
   [[MCP Server Catalog]] §how the danger is enforced.
3. **Untrusted tools cannot be granted at all until step 4 lands.**
   `Gateway.grant()` refuses at boot, which makes *gateway, then servers*
   mechanical rather than remembered.

**A bug this fixed:** `AgentDeclaration.may_use_tool` matched exactly, so an
agent declared `genesis-execution.*` — the form [[MCP Gateway]] uses for a whole
grant — would have been refused every real tool. It now shares the gateway's
matcher.

**Not built:** rate limiting, the cache, the fence, the router. The call path in
`gateway.py` names each seam in order rather than leaving a reader to guess
whether a stage is missing or merely elsewhere.

### Status — 2026-09-02: step 4 built, step 7 mostly wired

**The fence** (`src/genesis/mcp/fence.py`) — wrapping that cannot be escaped by
its own input, eight injection patterns, a trust ledger that does not recover by
waiting, and an SSRF guard that runs on every URL-shaped argument at any depth
in the argument tree. 42 tests. Design decisions are recorded in
[[MCP Gateway]] §the fence.

**Seven servers live**, verified through genesis's own runtime: obsidian,
filesystem, git, time, fetch, tradingview and exa. 30 tools registered. See
[[MCP Server Catalog]] §wired.

Proven end to end against live servers: a real Exa web search, summarised and
saved into the vault as a note; Exa's `agent_run` research agent returning in
39s, fenced; an SSRF attempt refused before dispatch even with the URL nested
inside an array argument; and an out-of-allow-list call refused before a
session opened — including `research.agent`, which was correctly denied until
it was deliberately granted.

**The write policy changed, and split in two.** A single `allow_mutating`
boolean conflated a write to a markdown file with a write to a broker. Phase 4
needs the first — its exit criterion is a daily brief *in the vault* — and must
never have the second. So `allow_writes` is the ordinary gate, and
`EXECUTION_NAMESPACES` (`order.`, `broker.`, `position.`, `execution.`) is
absolute, reachable only by `allow_execution_writes`, which is a Phase 7 act.
The flag somebody has a daily motive to turn on is no longer the flag that
opens the broker.

**Four bugs found by contact with real servers**, all fixed:

1. **Every tool had an empty input schema.** The SDK renamed `inputSchema` to
   `input_schema` and `readOnlyHint` to `read_only_hint` in v2, keeping the old
   names as wire aliases only — so `getattr` returned the default and *nothing
   failed*. The router would have had to plan with no schemas.
   `tests/mcp/test_sdk_shapes.py` now pins this against the real SDK type.
2. **`~` in a server argument was passed through literally**, including inside
   `--vault name=~/path`. A server handed a literal tilde creates a directory
   called `~` and looks like it worked.
3. **A failed connect said "unhandled errors in a TaskGroup (1 sub-exception)"**
   and nothing else. The cause is one level down in an ExceptionGroup; it is now
   flattened into the message.
4. **Every tool call used a hardcoded 30s timeout.** `call_timeout_sec` was
   configurable and then ignored — worse than not offering the setting.
   Timeouts are now per-tool, which is what a five-minute research agent
   sharing a server with a one-second search needs.
5. **A protocol error tore down a healthy session.** Every exception from
   `call_tool` was read as session loss, so "invalid params" spent two
   reconnects and abandoned the server's queue to fix a bad argument. Errors
   are now classified by shape: an error carrying a JSON-RPC code is the
   server *answering*, and is degraded rather than transient.
6. **`read_only` conflated two questions** — *can it write* and *must you name
   its tools*. brave-search cannot write and still wants curating: eight tools,
   of which three belong on a trading desk. `explicit_tools` separates them.

**Not built:** the router and `toolSearch` (step 5), rate limiting and the cache
(step 6), and [[genesis-tradingview-mcp]] (step 8) — the CDP server that drives
the desktop app. The headless `tradingview` server wired here does analysis; it
does not draw on your screen.

Steps 1–3 are the spine and are best built as one stretch. Step 4 gates step 7
absolutely. Step 8 is a different animal from the rest and should not be allowed to
stretch Phase 3 by itself.

### Registry deduplication is not a nice-to-have

`openbb-mcp`, `mcp-market-data-server` and `tradingview-mcp` all return quotes.
Three competing `get_quote` variants is a *distinct* failure from having too many
tools: the router picks a plausible wrong one and nothing notices, because the shape
is right. One canonical tool per capability, losers **unregistered** rather than
deprioritised, with [[Market Data Sources]] deciding the winner by trust tier.

### Status — 2026-09-03: steps 5, 6 and 7 built; step 8 half built

**The router** (`router.py`) and **`toolSearch`** — deterministic, per the open
decision below, which is now closed. **The cache** (`cache.py`) and **rate
limiting** (`limits.py`) — the two seams `gateway.py` had been naming in
comments are now stages. Design decisions for all three are recorded in
[[MCP Gateway]] under §smart tool selection, §caching and §rate limiting.

**Five more servers wired**, each started through genesis's own runtime with its
tool list read back: `sec-edgar` (13 tools), `fred` (5), `arxiv` (7),
`markitdown` (1), and `github` (hosted read-only endpoint, reached and
authenticating — a token is all it wants). **56 tools from 11 servers**, 738
tests.

**`capability_prefix` was the missing mechanism**, and its absence had been
hiding in plain sight. Allow-list entries are exact or `prefix.*`, so a
bulk-registered tool whose capability defaulted to its own bare name was a tool
**no allow-list could ever grant** — which is why `time` and `filesystem` name
every tool by hand for no reason other than to give it a capability. A prefix
says that once. It also keeps two servers apart: `sec-edgar` and `openbb` both
offer `get_company_facts`, and undecorated they would claim one capability and
refuse to boot.

**Curation is not optional for a large read-only server.** FRED offers 33 tools
and 28 of them walk its own taxonomy — categories, tags, sources, release
tables, GeoJSON region shapes. That is how you *browse* FRED in a browser, and
nothing in Genesis browses. arxiv offers 19 and 12 manage a local paper library,
which is a second retrieval system that [[Open Questions]] §9 decided against.
Registering them was tried, measured, and reverted: with 33 undifferentiated
FRED tools the router found the right *server* every time and the right *tool*
never, because a server's keywords are equally true of all of it and the tie fell
alphabetically. `read_only: true` + `explicit_tools: true` is now a documented
pair — the first says it cannot write, the second says we are naming its tools
anyway.

**This is why the catalogue is 56 tools and not 104.** Both numbers are real:
uncurated bulk registration hit 104 and cleared the letter of the Phase 3 exit
criterion while failing its spirit, since the extra 48 were plumbing that made
selection *worse*. See [[Build Order]] Phase 3 for the resulting decision about
that number.

**Four bugs, all found by tests or by contact with live servers:**

1. **The plural folder turned `news` into `new`** — and the namespace signal
   compared a raw namespace against folded query tokens, so the one namespace
   most likely to be asked for by name could never be matched.
2. **The token bucket used `0.0` as its "never refilled" sentinel.** A
   monotonic clock legitimately reads 0.0. It would have refused correctly,
   forever — the shape of bug that looks like a working rate limiter.
3. **`genesis mcp check` crashed on a failure with an empty message.** The
   report that exists to explain failures was the thing that broke on one.
4. **`on` in a keyword list is YAML boolean `true`.** Caught by the config
   loader rather than by a silently mistyped keyword.

### Status — 2026-09-03: step 8, the half that can exist

[[genesis-tradingview-mcp]] is built as far as it can honestly go:
`src/genesis/tradingview/` — raw CDP over a hand-written WebSocket client, the
chart surface with read-back verification on every mutation, and the MCP server
itself (`genesis-tradingview-mcp`, stdio). Navigation, read, screenshot,
`self_test` and `status`. 33 tests, none of which need Electron.

**The markup tools are not built, and not for lack of time.** `apply_markup`
compiles a [[Markup Spec]] into Pine, and `compile_pine` lives in
[[genesis-charting-mcp]], which does not exist. Writing one here would mean a
second Pine compiler — precisely the duplication the note's *one mechanism, both
requests* design avoids. The ordering is also the right one: *proprioception
before ambition*. A chart Genesis can read and screenshot is exactly the sense
that will later verify a chart Genesis draws on.

Registered as `genesis-tradingview` and **disabled by default** — it needs the
app running with a debugging port, which is a desk-hours condition, and
[[Biological Design]] forbids anything in the autonomous loop hard-depending on
a window being open.

## Phase 3 exit criterion

From [[Build Order]]: 100+ tools registered, the router selects a relevant handful
per task, and adding a server does not slow or degrade replies.

## Decisions, closed

1. **Router: deterministic.** ~~Open.~~ Lexical and capability-tag ranking, no
   LLM, per [[Biological Design]] §reflex arc — selection runs on every call and
   must never invent a tool. A model tier would go *in front* of it if the eval
   demanded one; it would not replace it. See [[MCP Gateway]] §smart tool
   selection for the four ranking rules and [[LLM Model Tiers]].
2. **[[genesis-tradingview-mcp]] straddles the boundary, deliberately.** Its
   read and navigation half is built inside Phase 3, because that half is the
   *sense* and costs nothing to have early. Its markup half is blocked on
   [[genesis-charting-mcp]] and belongs wherever that lands.

## Open decisions

1. **Does the Phase 3 exit criterion still say "100+ tools"?** It is reachable
   only by registering plumbing that degrades selection — the opposite of what
   the number was a proxy for. See [[Build Order]] Phase 3.

## Related

[[MCP Gateway]] · [[MCP Server Catalog]] · [[Agent Contract]] · [[Build Order]] ·
[[Biological Design]] · [[Safety Invariants]] · [[Market Data Sources]] ·
[[genesis-tradingview-mcp]] · [[Observability]] · [[Repo — jarvis]]
