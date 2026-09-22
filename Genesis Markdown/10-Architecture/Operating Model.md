---
title: Operating Model
tags: [architecture, ui, product]
status: building
implemented_by:
  - src/genesis/company/resolve.py
  - src/genesis/orchestrator/answer.py
  - src/genesis/server/analyst.py
  - tests/test_parity.py
---

# 🏛️ Operating Model

**Who commands, who advises, who does the work.**

[[Biological Design]] says what kind of *thing* Genesis is. This note says what
it is *for*, and who is in charge of it. Read both before designing anything
with a person on the other end of it.

The rules here are product rules, not safety rules — where they meet
[[Safety Invariants]], the invariants win. But they bind code just as directly,
because every one of them has already been violated by something that shipped.

---

## 1. The firm

Genesis is a research and analysis firm with one client, and the client owns it.

| Role | Who | What they do |
|---|---|---|
| **Head trader** | the human | Decides. Commands. Places the trade. Owns the P&L. |
| **Senior analyst** | the [[Orchestrator]] | Takes a question, works out what would answer it, puts the staff on it, comes back with a briefing. |
| **The staff** | the ~30 agents | The hours of work — screening, filings, news, backtests, chart markup, journal mining. |

The feeling to build for is *"I have thirty analysts, quants and researchers on
my desk"*, not *"I have a chatbot with a terminal attached"*. That distinction
is the whole product, and it shows up in code as: **an answer arrives with the
work behind it attached** — who ran, on what data, as of when — never as a
paragraph of prose whose sources you have to take on trust.

A Bloomberg terminal *presents* data. Genesis **collects, computes and
orchestrates** it. If a panel could have been a Bloomberg panel, it is not yet
finished — it is missing the agent, the provenance, or the conclusion.

> [!important] Genesis is an advisor, not the owner
> The orchestrator has full motor control of the software — it can open tools,
> arrange the workspace, and dispatch the fleet without being asked twice. It
> does **not** have authority over the trader. It proposes; the human disposes.
> That is the same asymmetry [[Approval Modes]] enforces for orders, applied to
> the surface as a whole.

---

## 2. The parity rule

> **Anything Genesis can do, a person can do by hand — through the same door,
> with the same audit line.**

[[Terminal]] states this for the tool catalogue. It is a system-wide rule and
belongs here, because it constrains every component that grows a capability.

Two reasons, and only the first is about convenience:

1. **Speed.** Asking a model to pick a tool costs a second and a token budget to
   do something the operator already knows the name of.
2. **Verification.** A system where the model can reach further than its
   operator is one where the operator cannot check the model's work. If Genesis
   says a filing shows something, the human must be able to open that filing
   themselves, from the same catalogue, and see the same bytes.

Corollaries that are easy to get wrong:

- **A capability behind voice only is a bug**, not a phase. If the only route to
  a working tool is to say a sentence and hope the router picks it, that tool is
  not shipped.
- **The caller is recorded, not inferred.** `operator` and `orchestrator` are
  separate identities with separate allow-lists ([[MCP Gateway]]). A log that
  cannot tell a person from a model cannot answer *"who did this?"* on the day
  it matters.
- **Parity is on capability, not on grants.** The human may do things Genesis
  may not (approve an order). Genesis may do things that cost money and time on
  a lane rather than behind Enter (`research.*`). Neither breaks the rule; a
  capability reachable *only* by the model does.

---

## 3. The canvas opens empty

The surface starts as an **open canvas**: the command line, the safety floor,
the core sigil, and nothing else.

This is a reversal. The shell currently opens on an Overview page that reports
what the system is; before that it opened onto a simulated fleet. Both answer a
question nobody asked, and the cost is the same either way — **the first screen
teaches the operator what the software is about, and a wall of unrequested
telemetry teaches them that things appear on their own.**

Three rules follow:

- **Nothing is on screen that was not asked for**, by the human or by Genesis
  acting on the human's request. The exceptions are the safety floor
  ([[UI Stack]] §6) and anything [[Voice UX]] §*when it speaks unprompted*
  already licenses to interrupt.
- **The blank canvas must be self-describing.** An empty screen with a cursor is
  a dead end unless typing into it reveals the surface. The command line is the
  map: typing shows pages, panels, series, agents and every MCP tool by name,
  with what each one needs. Discoverability lives in the input, not in a
  pre-populated screen.
- **Pages are entry points, not the organising principle.** A page is a named
  starting arrangement ([[Workspaces]]). The workspace is the product; the eight
  pages are eight bookmarks into it.

---

## 4. The command surface is the human's

**The human is the primary input. Voice is a peer, not the door.**

| Input | Reaches | Model involved |
|---|---|---|
| Command line (`⌘K`) | pages, panels, series, agents, every tool by name | none |
| Typed sentence (`⌘↵`) | the deterministic command table, then the orchestrator | only past the table |
| Voice | the same table, then the orchestrator | only past the table |

All three reach the same gateway and produce the same audit line. The typed
sentence and the spoken one are the *same* path — a microphone failure must
never be indistinguishable from a broken command, and a person on a call still
needs to drive the system.

It should feel like an **agentic terminal**: you type, and either the system
does the deterministic thing immediately, or an analyst picks it up. Not a chat
window bolted to a dashboard.

---

## 5. Genesis drives the same workspace you do

The orchestrator's motor surface on the UI is the **same** dock API the human
uses — it opens modules by short code into the current workspace and sets
symbols in link groups. It is a *participant* in the workspace, not an owner of
it, and it has no private channel:

- It **opens** panels and **sets** their subject. It does not close a panel a
  person opened, and it never computes pixel geometry ([[Workspaces]]).
- Everything it opens is labelled with **why** — the request that caused it, and
  the trace it belongs to. A panel that appeared unexplained is
  indistinguishable from a bug.
- The human can do all of it by hand, per §2. `openPanel` is one function with
  two callers.

**Panels publish what they are showing.** This is the capability existing
terminals do not have, and it is not a model problem — their panels simply do
not publish. When a news panel and a chart are open on MSFT, *"why is MSFT down
today"* must be able to read them rather than re-fetching the world.

---

## 6. The loop

The shape of every non-trivial request, from the trader's own example:

> *"Hey Genesis, I'm interested in W. D. Gann's research. Do some deep research
> on his findings, then save them in my research journal."*
>
> *"Starting the research agents on the web now — I'll write the findings to
> your journal when they're in."*

| # | Step | Where it lives |
|---|---|---|
| 1 | **Understand** the task, and say it back before doing it | [[Orchestrator]] §intent |
| 2 | **Resolve** the entities — names to tickers, a person to a research subject | §7 below |
| 3 | **Decide** which tools and which agents can answer it | [[Orchestrator Tools]], [[Agent Index]] |
| 4 | **Dispatch** them, in parallel where the dependencies allow | [[Task Bus]] |
| 5 | **Track** the state of the work, and report it while it runs | [[Fleet View]] |
| 6 | **Persist** the result as an artifact, not as a chat message | [[Memory Fabric]], [[Obsidian Vault Schema]] |
| 7 | **Present** the briefing back, with the work attached | [[Voice UX]], the canvas |

Two properties this shape demands that a request/response chat does not:

- **Acknowledgement precedes work.** A multi-minute research pass that answers
  with silence is indistinguishable from a hang. Step 1 speaks; step 5 is
  visible; step 7 is the answer.
- **A deliverable outlives the conversation.** *"Save it in my journal"* is the
  common case, not a special one. Long-running work produces a vault note, a
  markup spec, a backtest report — something addressable tomorrow. A findings
  paragraph that exists only in a transcript has not been delivered.

---

## 7. Nobody knows the ticker

**Traders speak in names. The system must speak both.**

*"Why is Nvidia down today?"* must resolve to `NVDA` before anything else
happens. Today it does not: `company/symbols.py` `normalise()` validates a
symbol and rejects a company name, so the name path fails at the first hop.

The rule:

- **Resolution is a lookup, not a guess.** A name → ticker map from a real
  source (EDGAR company tickers, the exchange listing) is a reflex —
  deterministic, cheap, auditable. Asking a model *"what is Nvidia's ticker"* is
  the wrong tier and will one day answer `NVDIA` with total confidence.
- **Ambiguity is surfaced, never resolved silently.** Two matches ask; zero
  matches say so. A silently wrong ticker is a chart of the wrong company that
  looks completely normal.
- **What was resolved is shown.** The panel says `NVDA — NVIDIA Corp`, so a
  mis-resolution is visible in one glance instead of one trade.
- **Not everything is a ticker.** *"Gann"* is a research subject; *"semis"* is a
  sector; *"my worst week"* is a journal query. Entity resolution classifies
  before it looks up, and "this is not a symbol" is a valid, common answer.

Lives beside the rest of identity in [[Company Data Model]].

---

## 8. What this changes about what is built

Written so the gap is legible rather than implied — a note describing a system
that does not exist is [[Biological Design|proprioceptive drift]].

| § | Rule | Today | Gap |
|---|---|---|---|
| 2 | Parity | partial | The tool panel and `⌘K` give the operator the read catalogue, and the allow-list symmetry is now pinned by a test. **`convert.*` is granted to the model and not the person** — that looks like an oversight rather than a decision, and widening a grant is not something a test should do quietly. Decide it. |
| 3 | Opens empty | ✅ | `DEFAULT_PAGE = 'home'` — command line, safety floor, core sigil, no dock. Every other category is a workspace the operator fills themselves. |
| 3 | Self-describing input | partial | `⌘K` lists pages, panels, series, tools, agents. It is not discoverable from an empty screen and has no "what can I ask?" affordance. |
| 4 | Typed sentence reaches the analyst | ✅ | Built 2026-09-06. The ladder moved out of `VoiceLoop._handle` into `orchestrator/answer.py`; `POST /v1/command` calls it when the deterministic table declines. The table still goes first on both paths, and `tests/test_parity.py` asserts the two take the same rung. |
| 5 | Genesis drives the workspace | ✗ | There is **no efferent path from the orchestrator to the UI at all**. `openPanel` has one caller: the command bar. |
| 5 | Panels publish context | ✗ | Not built. Symbol link groups are not built either. |
| 6 | Deliverables outlive the turn | partial | `vault.*` writes exist for the orchestrator; nothing routes a research pass into a journal note. |
| 7 | Name → ticker | ✗ | `normalise()` rejects a company name. No resolver, no ambiguity path. |

---

## Acceptance criteria

- The shell opens with no data panel on screen, and typing one character into
  the command line reveals what the system can do.
- Every tool Genesis uses in a session can be opened by hand from the same
  catalogue, and returns the same bytes.
- *"Why is Nvidia down today?"* — typed **and** spoken — resolves `NVDA`, opens
  the panels it used, and answers with each source named and timestamped.
- A panel opened by Genesis names the request that opened it.
- A multi-minute research request is acknowledged in under two seconds, visible
  while it runs, and lands as an addressable vault note.
- Unplugging the microphone removes no capability.
- An ambiguous name asks. It never picks.

## Related

[[UI-0 Build Order]] — how §8's gaps get closed, in order ·
[[Biological Design]] · [[Orchestrator]] · [[Orchestrator Tools]] · [[Terminal]] ·
[[Workspaces]] · [[UI Stack]] · [[Voice UX]] · [[Dashboard]] ·
[[Company Data Model]] · [[MCP Gateway]] · [[Agent Index]] ·
[[Approval Modes]] · [[Safety Invariants]]
