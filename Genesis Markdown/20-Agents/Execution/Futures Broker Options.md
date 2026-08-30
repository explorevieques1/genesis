---
title: Futures Broker Options
tags: [execution, risk, research]
family: execution
status: spec
implemented_by: []
---

# 🔌 Futures Broker Options

Research note answering the futures half of [[Open Questions]] §1: what does
[[Agent — Broker Adapter]]'s `place()` actually speak to, given the account sits
at a **futures prop firm**, not a retail equities broker.

## Why this is its own note

[[Agent — Broker Adapter]] and [[genesis-execution-mcp]] both cite
`alpaca-mcp-server` as the reference implementation — that's an equities/options/
crypto shape. Futures-at-a-prop-firm is a different world: no broker exposes a
clean REST API to a funded account, and the platform choice is dictated by which
firm you're evaluating with. This note is the survey; §1/§2 in
[[Open Questions]] hold the decision once it's made.

## The blocker that rules out the obvious answer

**Tradovate direct API access does not work for prop accounts.** It requires a
$1,000 **live**-account balance plus a $25/month API subscription, and prop-firm
or evaluation accounts are rejected outright at the subscription screen — no
distinction shown between "underfunded" and "ineligible account type." This holds
across every firm that routes through Tradovate (Apex, Topstep's older stack,
etc.). Confirmed repeatedly on the Tradovate community forum as of 2026. Existing
open-source Tradovate MCP servers (`alexanimal/tradovate-mcp-server`,
`0xjmp/mcp-tradovate`) are real and reasonably complete, but they're built against
the live-account API this gate excludes — not usable here.

## The four paths that do work

| Path | Access model | Latency | Fit |
|---|---|---|---|
| **TopstepX / ProjectX Gateway API** | Official REST + SignalR, Topstep-exclusive since ProjectX ended third-party prop-firm licensing 28 Feb 2026 | Low | Only reachable if [[Open Questions]] §2 resolves to **Topstep**. Best effort-to-result ratio of the four — official, documented, a reference MCP already exists ([`brandononchain/topstepx-mcp`](https://github.com/brandononchain/topstepx-mcp)) to study or fork for the adapter's shape. |
| **Sierra Chart DTC protocol** | Documented binary/JSON protocol; Sierra Chart runs a local DTC server, the adapter is a normal socket client | Low, purpose-built for third-party automation | Best long-term reference implementation to prototype [[Agent — Broker Adapter]]'s interface against — it isn't a UI-automation hack, it's a real protocol meant for exactly this. Needs a Sierra Chart subscription with the firm's data feed enabled inside it. |
| **Rithmic R\|API+** | Official API; the data/order feed most futures prop firms (Apex, Bulenox, and others) actually route through underneath their supported front ends | Lowest of the four | Best long-term target, worst short-term effort. Protobuf + cert/login handshake, no mature Python MCP exists yet — `async_rithmic` on PyPI is the closest starting point, but `genesis-broker-rithmic` would be written close to scratch. |
| **NinjaTrader ATI** | Local DLL/pipe automation interface into an already-logged-in NT8 instance | Low | Fallback for firms that only support NT8 as a front end. Adapter shells out to a small C#/NT8 addon or the ATI COM/pipe bridge. |

None of these four route through [[genesis-tradingview-mcp]] — that server
structurally cannot reach an order path (see its "Explicitly absent" section and
[[Safety Invariants]] §1). TradingView-as-front-end automation (clicking its Trade
panel) was considered and rejected for the same reason: it's a UI-automation path
around the risk gate, not a real API.

## Recommendation

1. **Resolve [[Open Questions]] §2 (which firm) first.** It isn't just a config
   value here — per [[Prop Firm Rules]], it also promotes
   [[Agent — Prop Firm Guard]] from Phase 10 to Phase 7: a hard gate in
   [[Pre-Trade Risk Engine]] before any execution work starts, not an add-on
   after.
2. **If the firm is Topstep** → build against **TopstepX**. Shortest path to a
   working `place_approved` end to end; fork `topstepx-mcp`'s tool shape rather
   than starting from `alpaca-mcp-server`'s.
3. **If it's Apex or most other firms** → target **Sierra Chart's DTC protocol**
   first for the adapter interface (real automation protocol, well documented),
   with **NinjaTrader ATI** as the fallback for NT8-only firms. Treat **Rithmic
   R\|API+** as the follow-on once the adapter shape is proven, since it's the
   lowest-latency but highest-effort of the set.
4. **TradingView stays eyes-only.** [[genesis-tradingview-mcp]]'s scope is
   unchanged by this decision — data and markup, never the hands.

## Reference implementations to study before writing the futures adapter

Add these alongside `alpaca-mcp-server` in [[genesis-execution-mcp]]'s and
[[Agent — Broker Adapter]]'s "study before writing" pointers, once §1/§2 land on
futures:

- Sierra Chart DTC protocol docs (`sierrachart.com/index.php?page=doc/DTCProtocol.php`)
- `async_rithmic` (PyPI) — if the Rithmic path is taken
- `brandononchain/topstepx-mcp` — if the firm is Topstep

## Acceptance criteria

Same bar as [[Agent — Broker Adapter]] already sets, applied to whichever target
is chosen: refuses to start live without live credentials present, reconciles
open orders/positions on reconnect before placing anything new, declares
capabilities (native brackets, OCO, trailing stop) rather than assuming them —
this varies materially between Rithmic, Sierra Chart, and NT8.

## Related

[[Agent — Broker Adapter]] · [[genesis-execution-mcp]] · [[genesis-tradingview-mcp]] ·
[[Prop Firm Rules]] · [[Agent — Prop Firm Guard]] · [[Open Questions]] ·
[[Safety Invariants]] · [[MCP Server Catalog]] · [[Execution Family]]
