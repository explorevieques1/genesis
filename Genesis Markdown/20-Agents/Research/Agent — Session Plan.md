---
title: Agent — Session Plan
tags: [agent, research]
family: research
cadence: on-demand
tier: none
status: building
implemented_by: [src/genesis/agents/research/session_plan.py, src/genesis/research/plan.py, src/genesis/server/plan_routes.py, tests/research/test_session_plan.py]
---

# 🗺️ Agent — Session Plan

## Purpose

**Your ideas in; a plan of action out.** The head trader shares what they're
thinking — typed, spoken, or `genesis idea add` — and asks *"so what do I do?"*.
The desk answers with the four things a trader asks for before the open:

1. **Ranked ideas with permitted size** — how much the gate would let you do
2. **Levels and triggers** — where to act, where it's wrong, where to take it
3. **What's in the way** — the envelope, the book, the calendar, your own lessons
4. **A written brief you can re-read** — saved to the vault, one file per plan

Placed on the map ([[Biological Design]]): this is the **senior analyst's
briefing** ([[Operating Model]]) assembled over spinal cord. It is `tier: none`
because every number in a plan is someone else's and every word of reasoning is
the trader's own. The judgement layer is the conversation *about* the plan — the
orchestrator can read the saved note and argue with it — not a paragraph generated
into it.

> [!important] No sizing lives here
> Every size is the [[Pre-Trade Risk Engine]]'s own answer to a **dry run** of the
> exact ticket (`OrderManager.dry_run`), which mints no approval and records
> nothing. There is one sizing implementation in the system, and it is the one that
> guards orders — a second copy in the plan would agree with it until the day it
> did not ([[Safety Invariants]] #3).

## Cadence

`on-demand` — dispatched by the [[Orchestrator]] (`idea.record`, `plan.build`), or
run by hand. Nothing on a cron: a plan nobody asked for is the canvas filling itself
([[Operating Model]] §2).

## Inputs

| Input | From | Absent means |
|---|---|---|
| Live ideas — yours and the synthesizer's | research store, `kind: idea`, past-horizon excluded | "No setup today" is a valid plan |
| Sizes | the gate's dry run, via the running order manager | a desk line naming *why* (order path off, server not running) — never sizes of 0 |
| Heat, positions, problems | [[Agent — Position And PnL Accountant]] | no book-level conflicts, stated |
| Lessons | [[Agent — Insight Miner]] — matched on `applies_when` naming the symbol or setup | none listed |
| Scheduled prints | [[Economic Calendar]] — high impact, inside the idea's horizon | none listed |
| Envelope, allow-list, configured contracts | config, **re-read per plan** so a tightened limit applies to the next one | — |

Each input is fetched when the plan runs; any one failing is a line under
**Degraded**, never a crash and never a silent gap.

## Output

A `SessionPlan`: ranked items, desk-level blockers, degraded inputs, and the sources
it was built from. Saved as a research note `kind: plan` at
`10-Ideas/plans/YYYY-MM-DD-HHMM.md` ([[Obsidian Vault Schema]]) — one file per
plan, because a plan is a record of what was advised *when*.

Per item: size, the check that bound it, worst case, R:R, levels with distance
from the mark, conflicts, and **the exact ticket the trade panel would propose**.
Acting on a plan is still `propose → approve → place`; nothing here is an order.

Three decisions worth stating:

- **Sized as if the market were open.** A plan is usually made before the open, and a
  gate that stops at "not trading now" says nothing about *how much*. The session,
  halt and mode are lifted for the sizing and reported on the desk as they are now —
  never presented as the current answer.
- **Priced at the far edge of the entry zone** — top for a long, bottom for a short.
  The fill furthest from the stop, so the size survives the worst entry in the zone,
  and a price the trader wrote down (a midpoint need not be on the tick grid).
- **Heat is "no room", not "blocked".** An idea the gate refuses for heat, contract
  cap or daily loss becomes takeable as risk comes off; one refused for its shape
  (not on the allow-list, no stop, off the tick grid) does not. Ranking keeps them
  apart: actionable first, then confidence × min(R:R, 3)/3.

## Recording an idea

`idea.record` writes through the same `Idea` type as [[Agent — Idea Synthesizer]], so
**no invalidation, no idea** holds for yours exactly as for its. Two additions to
[[Idea Schema]]:

- `stop_price` — the invalidation as a number. An idea may be stated as a condition
  and still be recorded, but **without a price nothing can be sized**: the gate
  measures risk from entry to stop, and a condition is not a distance.
- A long's stop must be below its entry zone and a short's above — a reflex at
  intake, because "I meant 19,950 not 20,950" is cheapest to catch while the person
  who said it is still there.

Spoken ideas: a model turns the sentence into arguments, and the capability tells it
to use **only numbers the trader said**. The readback states every number recorded,
so a misheard price is caught by the person who said it. Your ideas get their own
subject (`nq-long`), so restating one updates it and never supersedes the
synthesizer's.

Nobody knows the contract month: `NQ` resolves to the one configured `FUT:…:NQ:…`
contract, two configured is surfaced as ambiguous, none configured says so — the
plan never guesses the front month ([[Open Questions]] §13).

## Doors

| Door | Afferent | Efferent |
|---|---|---|
| Orchestrator | — | `idea.record`, `plan.build` |
| HTTP | `GET /v1/ideas`, `GET /v1/plan` (builds, saves nothing) | `POST /v1/ideas`, `POST /v1/plan` |
| CLI | `genesis idea list` | `genesis idea add`, `genesis plan [--no-save]` |

`genesis plan` goes through the running server when there is one — only that process
holds the order manager, and the order manager is what sizes. Offline it builds
locally and says the gate could not size anything.

## Memory namespace

Read: `shared`, `idea-synthesizer`, `session-plan`, `ledger`, `lessons`
Write: `session-plan` (plans, and your ideas)

## Acceptance criteria

- Every size in a plan equals the gate's `approved_qty` for the same ticket — no
  second implementation.
- An idea with no stop price is listed, never sized, and never sent to the gate.
- A dry run mints no approval token.
- A closed market or an engaged kill switch appears on the desk, never folded into a size.
- An unavailable input is a degraded line, not a crash.
- `GET /v1/plan` writes nothing; `POST /v1/plan` writes one vault file.
- Loaded with any model tier, the declaration is refused (`SPINAL_AGENTS`).

## Related

[[Idea Schema]] · [[Agent — Idea Synthesizer]] · [[Pre-Trade Risk Engine]] ·
[[Agent — Position And PnL Accountant]] · [[Risk Envelope]] · [[Economic Calendar]] ·
[[Agent — Insight Miner]] · [[Operating Model]] · [[Research Family]]
