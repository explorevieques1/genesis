---
title: Daemon And Cadence
tags: [architecture, core]
status: building
implemented_by: [src/genesis/daemon/daemon.py, src/genesis/daemon/calendar.py, src/genesis/daemon/scheduler.py, src/genesis/daemon/supervisor.py, tests/daemon/]
---

# Daemon And Cadence

The forever loop. Genesis is not "on during the day" — it has **two different jobs**
depending on whether the market is open.

## The loop

```python
while True:
    tick = now()
    session = calendar.state(tick)      # premarket | open | afterhours | closed | holiday

    if session in (OPEN, PREMARKET, AFTERHOURS):
        run_due(cadence="market-open")
    else:
        run_due(cadence="market-closed")

    run_due(cadence="cron", at=tick)
    drain_task_bus()                    # user + event + agent-generated work
    handle_events()                     # fills, level touches, breaches

    if working_memory.too_large():
        summarise_into_episodic()

    watchdog.heartbeat_all()
    sleep(TICK)                         # ~1s
```

## Session states

| State | Hours (US equities, ET) | Behaviour |
|---|---|---|
| `premarket` | 04:00–09:30 | brief, gap scan, catalyst digest; no auto orders by default |
| `open` | 09:30–16:00 | full market-open cadence |
| `afterhours` | 16:00–20:00 | earnings reactions, EOD journal starts |
| `closed` | 20:00–04:00 | deep work — backtests, optimization, mining |
| `holiday` / `half-day` | calendar-driven | closed cadence; announce the exception in the brief |

The calendar must be real (market holidays, half-days, DST). Getting this wrong
means the system backtests during the open and scans on Christmas.

Futures and crypto have different sessions — if [[Open Questions]] §1 lands on
futures or crypto, this table is per-venue, not global.

## Cadence types

| Cadence | Meaning |
|---|---|
| `on-demand` | Only when the [[Orchestrator]] dispatches |
| `market-open` | Runs on an interval while the market is open |
| `market-closed` | Runs on an interval while closed |
| `cron` | Runs at a wall-clock time |
| `event` | Runs when a subscribed [[Event Schema|event]] fires |

Agents declare their cadence in [[Agent Contract]]. One agent may have several
(e.g. [[Agent — Idea Synthesizer]] is `market-open:15m` + `cron:premarket` + `event:news.spike`).

## Market-open roster

| Agent | Interval |
|---|---|
| [[Agent — News And Catalyst]] | 5–15 min + event |
| [[Agent — Screener]] | 1–5 min |
| [[Agent — Level Watcher]] | streaming / 1 min poll |
| [[Agent — Sentiment]] | hourly |
| [[Agent — Idea Synthesizer]] | 15 min |
| [[Agent — Position And PnL Accountant]] | on every fill + 30 s |
| [[Agent — Execution Quality]] | on every fill |
| [[Agent — Watchdog]] | 30 s |

## Market-closed roster

| Agent | Interval |
|---|---|
| [[Agent — Fundamental]] | daily |
| [[Agent — Regime And Correlation]] | daily |
| [[Agent — Backtest Runner]] | queue-driven |
| [[Agent — Optimizer]] | queue-driven, long jobs |
| [[Agent — Insight Miner]] | nightly |
| [[Agent — Performance Analyst]] | nightly + weekly deep |
| [[Agent — Backtest Vs Live Drift]] | nightly |
| [[Agent — ML Signal]] | weekly retrain |
| [[Agent — Digest]] | nightly |

Closed-market work is where the compute budget goes. Long backtests and parameter
sweeps should be **scheduled to finish before pre-market**, not started at 08:00.

## Cron schedule

| Time (ET) | Job |
|---|---|
| 07:00 | Pre-market brief — [[Agent — Market Analyst]] + [[Agent — News And Catalyst]] → daily research note, spoken on request |
| 09:15 | Final gap/catalyst check, watchlist freeze |
| 16:15 | EOD sweep — close journal entries, reconcile [[Trade Ledger]] against broker |
| 18:00 | [[Agent — Performance Analyst]] daily tearsheet |
| 21:00 | [[Agent — Insight Miner]] + [[Memory Consolidation]] |
| 23:00 | [[Agent — Digest]] — tomorrow's prep note |
| Sun 10:00 | Weekly review (spoken), strategy leaderboard, [[Agent — Backtest Vs Live Drift]] deep pass |
| Sun 03:00 | Corpus re-index (`build_index.sh`), [[Vector Store]] refresh |

## Supervision

Each agent runs as a supervised worker.

- Crash → restart with exponential backoff (1s, 2s, 4s… cap 60s)
- 5 crashes in 10 minutes → mark `degraded`, stop restarting, emit `agent.down`,
  tell the user via [[Voice UX]]
- A `degraded` execution-path agent forces [[Approval Modes|`confirm`]] mode
  (never `auto`) until it recovers
- [[Kill Switch]] runs **outside** supervision — it must work when the supervisor is broken

Reference: [[Repo — gensis-agents]] `scripts/dev.js` process manager;
[[Repo — jarvis]] `daemon.py`.

## Restart behaviour

On boot: reload config, restore [[Task Bus]] state, reconnect MCP sessions, reconcile
the ledger against the broker **before** enabling any order path, expire all pending
order confirmations, then resume cadence.

Boot announces itself: "Genesis online. Market closed. Ledger reconciled. Four agents idle."

## Acceptance criteria

- Runs 7 days unattended without a manual restart.
- Correctly identifies a half-day and a holiday.
- A killed agent restarts and rejoins its cadence within 60 s.
- Restart never resurrects a stale order confirmation.
- Closed-market jobs finish before the 07:00 brief, or are killed and reported.

## Related

[[Task Bus]] · [[Agent Contract]] · [[Agent — Watchdog]] · [[Observability]] · [[Kill Switch]]
