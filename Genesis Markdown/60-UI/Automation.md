---
title: Automation
tags: [ui, orchestration]
status: spec
implemented_by: []
---

# ⚙️ Automation

## Purpose

A surface where a person composes **workflows** — steps wired together that
Genesis can run on a cadence or an event — without writing code.

**Not built.** `automation.workflows` probes false; there is no
`genesis.automation` module. The page reports that, names this note, and shows
what exists instead.

## What exists instead, and why it matters

Genesis already automates. Eleven agents declare real cadences in
`AgentDeclaration.cadence`, and the daemon runs them:

- `market-open: 30s` — the watchdog, while the market is open
- `market-closed: 86400s` — the insight miner, overnight
- `cron: 07:00, 16:30, 21:00, 23:00` — the digest's four daily passes
- `event: agent.down, agent.degraded` — the watchdog again, reactively

The Automation page renders these, grouped by trigger. They are not a mock of
what a workflow engine would do — they are a running schedule.

That framing is the design constraint. **A workflow engine is not greenfield.**
It is a way to author what `cadence` already expresses, and it must extend that
declaration rather than sit beside it as a second, parallel scheduler. Two
schedulers is two answers to "what is going to happen at 16:30", and the daemon
can only obey one.

## Open questions

1. **Where does a workflow live?** A `cadence` entry is code, in the agent's
   module, reviewed in a diff. A UI-authored workflow is data, in a store,
   changed by a click. Those have different audit properties and the difference
   is the whole risk of this feature.
2. **What may a step do?** If a step can call any MCP tool, the workflow builder
   becomes a way to compose tool calls that no agent declaration authorised —
   which routes around [[MCP Gateway]]'s allow-lists. Steps must be drawn from
   the same capability set the invoking agent already holds.
3. **Can a workflow reach an order path?** No, and this must be structural
   rather than a rule — [[Safety Invariants]] #1. A workflow that could compose
   `propose_order` with an auto-approve step would be an autonomy escalation
   authored in a canvas.
4. **What happens to a running workflow when it is edited?** Versioning, or
   refusal.

Until 1–3 have answers, the honest surface is the one that shows the schedule
that exists and says the builder does not.

## Related

[[Orchestrator]] · [[Daemon And Cadence]] · [[Agent Contract]] ·
[[MCP Gateway]] · [[Safety Invariants]] · [[Workspaces]]
