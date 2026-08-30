---
title: Error Handling And Degradation
tags: [architecture, risk]
status: spec
implemented_by: []
---

# Error Handling And Degradation

The system must **fail honestly and degrade gracefully**. A trading assistant that
confabulates a price is worse than one that says nothing.

## Three failure classes

| Class | Meaning | Response |
|---|---|---|
| `transient` | Will probably work on retry — network blip, MCP session loss, rate limit | Retry with exponential backoff, cap attempts, then escalate to `degraded` |
| `degraded` | Can proceed with less — stale quotes, one feed down, small model instead of large | Proceed, **label the output**, tell the user once, keep going |
| `fatal` | Cannot proceed safely — broker unreachable during an open position, reconciliation mismatch, corrupt ledger | Stop that path, escalate, speak immediately, consider [[Kill Switch]] |

## The labelling rule

Any output built on degraded input carries the degradation forward.

- In a result: `"degraded": true` with a reason ([[Agent Contract]])
- In a spoken reply: "…on delayed data" / "…the sentiment feed is down, so this is
  price-only"
- In a vault note: a `degraded:` frontmatter field and a visible callout
- In an [[Idea Schema|idea]]: confidence is capped when inputs were degraded

Degradation that isn't visible is just bad data with good manners.

## Never confabulate

Forbidden, in all circumstances:

- Inventing a price, a level, or a P&L figure
- Reporting a fill that didn't happen
- Presenting a backtest result computed on incomplete data without saying so
- Answering "what's my position?" from memory when the ledger is unreachable

Correct behaviour: *"I can't reach the broker, so I can't confirm your position.
Last known as of 14:32 was 40 NVDA long — treat that as stale."*

## Degradation ladder by subsystem

| Subsystem | Degraded | Fatal |
|---|---|---|
| [[Voice Stack]] STT/TTS | local model, worse voice | mic gone → text-only via [[Dashboard]] |
| Market data | delayed quotes, label everything | no data during an open position → warn, tighten to `confirm` |
| [[LLM Model Tiers]] large tier | small tier + caveat | none — deterministic paths keep working |
| [[MCP Gateway]] one server | that agent's tools shrink | execution MCP down with orders working → `halt` |
| Broker | read-only (positions visible, no new orders) | unreachable with open risk → `halt` + alert loudly |
| [[Memory Fabric]] vector store | graph + recency recall only | none |
| [[Trade Ledger]] | — | any corruption or mismatch → `halt`, no exceptions |
| Obsidian vault | queue writes to disk, flush later | none |
| Internet | research-only mode | none — never corrupt state |

## Retry policy

- Backoff: 1s, 2s, 4s, 8s… capped at 60s, with jitter.
- Max 3 attempts for a task, then `degraded` or `fatal` by class.
- **Order placement is never blind-retried.** Retry only after querying broker state
  by idempotency key ([[Order And Fill Schema]]). A duplicate fill is worse than a
  missed one.
- MCP session loss gets one silent reconnect before it counts as an attempt
  (pattern: [[Repo — jarvis]] `mcp_runtime.spec.md`).

## Spawning external processes

A child process inherits the parent's environment, and an inherited variable can
silently change what the child *is*. Build the child env explicitly; never assume
the parent's is clean.

- **`ELECTRON_RUN_AS_NODE` must be removed when spawning any Electron app.** If it
  is set (it is, in the VS Code extension-host shell), the binary runs as plain
  Node, rejects the app's own CLI flags, and gives you a REPL instead of a window.
  The failure — `bad option: --remote-debugging-port=9222` — reads exactly like the
  app having disabled remote debugging, so it is misdiagnosed as a dead end rather
  than a dirty environment. See [[genesis-tradingview-mcp]].

Classify a spawn that fails on flag parsing as `fatal` for that component, not
`transient` — retrying with the same environment cannot succeed, and the honest
report is "I could not launch it", never a guess about why.

## Circuit breakers

A component failing repeatedly is taken out of rotation rather than retried forever:

- MCP server: 10 failures in 5 min → open circuit for 5 min, agents relying on it go `degraded`
- Agent: 5 crashes in 10 min → `degraded`, no more restarts, user notified ([[Daemon And Cadence]])
- LLM endpoint: sustained errors → route that tier elsewhere, log it
- Data feed: staleness beyond threshold → mark stale, don't just keep serving old bars

## Execution-path special rules

1. A `degraded` execution-path component forces [[Approval Modes|`confirm`]] mode.
   Autonomy requires health.
2. Any [[Trade Ledger]] inconsistency is `fatal` and triggers [[Kill Switch]].
3. Reconciliation failure at 16:15 blocks the next session's order path until resolved.
4. If [[Pre-Trade Risk Engine]] cannot evaluate a rule (missing data), it **rejects**.
   Fail closed, never open.

That last one is the single most important line in this note.

## Acceptance criteria

- Pull the network cable mid-session: voice degrades, agents return typed failures,
  no crash, no invented data, spoken notification within 30 s.
- Kill the market-data MCP: dependent agents go degraded and say so; unrelated
  agents unaffected.
- Corrupt a ledger row in a test: system halts and refuses to trade.
- Force a risk-rule evaluation error: the order is rejected, not allowed through.

## Related

[[Safety Invariants]] · [[Pre-Trade Risk Engine]] · [[Kill Switch]] ·
[[Agent Contract]] · [[Observability]] · [[Agent — Watchdog]]
