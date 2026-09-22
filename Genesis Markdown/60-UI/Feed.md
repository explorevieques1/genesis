---
title: Feed
tags: [ui, module, automation]
status: built
implemented_by: [src/genesis/automation/feed.py, src/genesis/server/automation_routes.py, ui/src/workspace/panels/feed.tsx, tests/automation/test_feed.py]
---

# Feed — `FD`

What the automations have produced, newest first. One row per run that left
something durable — a note, a news brief, a journal observation, an alert —
and every row is a way into the thing itself.

Home category: [[Workspaces|automation]]. Sits beside [[Automation|`CD`]], which
answers the other question: not *what was produced* but *what is scheduled and
did it run*.

## Why it stores nothing

**The feed is a view over the run log.** Every run already records each step's
output ([[Automation]] §Q1), and a step that wrote something says so in its own
output: `output.note` returns the note path, `news.brief` returns the brief id,
`journal.observe` returns the observation id. So "what has Genesis produced" is
a query over records that already exist.

A second table would be a second truth — a feed row that says a note was written
and a vault with no such note is exactly the [[Biological Design|proprioceptive
drift]] the body-map rule forbids, in miniature. There is nothing to drift from
if the feed reads the log itself.

The consequence worth knowing: **an artifact deleted by hand still has a feed
row**, because the run really did produce it. The row opens the module, the
module says it is gone. That is honest, and it is the right failure — a feed
that silently dropped the row would hide that something was deleted.

## What counts as produced

| Step output key | Artifact | Opens in |
|---|---|---|
| `path` | note | [[Notebook\|`NOT`]] |
| `brief` | brief | [[News\|`NW`]] |
| `observation` | journalled | `JE` |
| `alert` | — titles the row | — |

A run with none of these is **not** a feed item. A gate that stopped a chain
because it was not pre-market did its job correctly; it belongs in `CD`'s run
history, not in front of a person. The distinction is the whole design: `CD`
answers *did it run*, `FD` answers *did it find anything*.

An action grows a destination by returning its id, not by teaching the feed
about itself — the key table above is the only coupling.

## New, without a seen-marker

An item from the last 24 hours is **new**, by its timestamp alone. There is no
stored read-state, so there is nothing that can disagree with what was actually
read — a marker cleared by opening the panel claims a person read what they
merely scrolled past.

## It does not open itself

**`FD` never appears unasked.** [[Operating Model]] §3 — the canvas opens empty,
and the vault permits Genesis to open a panel only while *answering a request*.
A cron job firing at 16:10 is not a request. The job leaves its artifact and the
trader comes looking, the same way an inbox works.

Push, when it is warranted, is what `output.alert` is already for.

## Daily movers

The first workflow built to feed this, shipped as a template ([[Automation]]
§Templates). Weekdays 16:10 ET:

1. **`market.index-movers`** — the S&P 500's five biggest gainers and losers, in
   one call, from the fund's own holdings file ([[Index Movers]]). Deterministic,
   `tier: none`. One node rather than two screens because steps take one input
   and there is no merge node.
2. **`data.symbols`** → **`news.brief`** over exactly those tickers, 12 hours
   back. The only judgement in the chain, and its text is third-party reporting:
   marked `untrusted`, never handed to another agent as data.
3. **`output.note`** → `Daily Movers/YYYY-MM-DD.md` in the notebook vault, in
   `replace` mode so a re-run does not stack copies of the same day.
4. **`journal.observe`** → one `movers.daily` observation carrying the note path,
   so the [[Agent — Insight Miner|Insight Miner]] can later rest a lesson on it.
5. **`output.alert`** — the movers line, for the push half.

Steps 3 and 4 are deliberate duplication of *pointer*, not of text: the note is
for a person to read and edit, the observation is for the miner to aggregate.
The note is the only copy of the words.

## Parity

`feed` opens it, typed or spoken ([[Terminal]]). The workflow behind it is a
template in `WB` and runs by hand from there — nothing in this module is
reachable only by asking Genesis nicely.

The alias `feed` moved here from `LD` (Live data), which keeps `live`. Codes and
aliases share one namespace, so one word resolves to one module.

## Related

[[Automation]] · [[Notebook]] · [[News]] · [[Journal Family]] · [[Index Movers]] ·
[[Operating Model]] · [[Workspaces]]
