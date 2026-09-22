---
title: UI-0 Build Order
tags: [meta, plan, ui]
status: building
implemented_by:
  - src/genesis/orchestrator/answer.py
  - src/genesis/orchestrator/loop.py
  - src/genesis/orchestrator/build.py
  - src/genesis/server/analyst.py
  - src/genesis/server/app.py
  - src/genesis/server/tool_routes.py
  - tests/test_parity.py
---

# UI-0 Build Order

**Making the surface commandable.** Six steps that close [[Operating Model]] §8
— the gap between what the trader was promised and what the code does.

This is stage zero of [[Build Order]] Phase 6, and it comes before the panels,
the core at `hero` tier, and the Tauri shell. The reason is not sequencing
taste: **every panel added before this inherits the shape of the problem.** A
new panel today is reachable from one page, opened only by a person, carrying no
statement of where its numbers came from, and invisible to the orchestrator that
is supposed to reason about it. Building ten more of those makes the surface
larger and no more commandable.

> [!important] Most of this is deletion and re-wiring
> There is a lot of code here already. The complaint that produced this plan —
> *"thousands of lines and two or three real use cases"* — is not a shortage of
> implementation. It is 131 tools behind one router, an answer ladder locked
> inside an audio loop, and a landing page nobody asked for. Four of the six
> steps below **remove or re-point** existing code rather than adding to it.

---

## Step 0 — One answer path, reachable without a microphone — **BUILT**

> [!done] Built 2026-09-06
> `orchestrator/answer.py` holds the ladder; `VoiceLoop._handle` and
> `POST /v1/command` are its two callers. `server/analyst.py` builds the HTTP
> side lazily and **shares `tool_routes.GATEWAY`** rather than starting a
> second copy of every MCP server. `tests/test_parity.py` pins both halves.
>
> Three things worth keeping:
>
> 1. **The rungs are read at call time, not held.** `VoiceLoop.ladder()`
>    rebuilds a `Ladder` per utterance from its own attributes. A dataclass
>    allocation is free next to a model round trip, and it means there is one
>    source of truth — swapping `loop.reasoner` swaps what answers, with no
>    second copy to keep in step.
> 2. **`path` is now on both routes.** The rung that answered comes back as
>    `analyst.reasoned` / `analyst.trivial` in the command envelope, not a flat
>    label. The parity test asserts on it, because "both produced an answer" is
>    a weaker property than "both took the same rung" — a typed question that
>    quietly skipped the calendar and paid for a model call would pass the first
>    and be the bug this step exists to prevent.
> 3. **The HTTP ladder has no bus**, so its planning rung is absent rather than
>    declining. `build_ladder` already takes a bus; the rung reappears the day
>    `serve` is given the daemon's, with no change in `analyst.py`.

**The parity rule made structural.** [[Operating Model]] §2, §4.

### The problem, precisely

`VoiceLoop._handle` (`orchestrator/loop.py`) contains the answer ladder the
[[Orchestrator]] note specifies — verbosity command, deterministic answer, plan,
fail-open to the large tier with tools. It is thirty lines in the middle of a
method whose input is **audio frames**.

`POST /v1/command` (`server/app.py` `_run`) calls `commands.dispatch` and stops.
A sentence the table does not match returns *"I didn't catch a command in
that"* — with a fully-built reasoner sitting behind an import the route never
makes.

So the ladder has one caller, and it needs a microphone. Everything the trader
can only get by speaking, they can only get because of this.

### The change

Extract the ladder into `orchestrator/answer.py`:

```
Ladder(verbosity, answerer, planner, runner, reasoner)
    .answer(text, *, context="", on_dispatch=None) -> Rung
    verbosity → answers → planner/runner → reasoner → honest failure
```

`on_dispatch` fires once, before a validated plan runs — the acknowledgement
hook. The voice path plays an earcon there; the screen will show work in flight.
The ladder does not know which one it is calling.

Two callers, both thin:

- `VoiceLoop._handle` — keeps the audio, the STT, the earcons, the follow-up
  window, the speaker. Loses the ladder.
- `server/app.py` `_run` — after `match_command` misses, hands the sentence to
  `server/analyst.py` instead of returning `unmatched`.

The deterministic table stays in front on both paths, and the safety reflexes
(`voice/reflex.py`) stay in front of *that*. Neither moves. This step changes
who can reach the slow path, not what the fast path does.

### Not in this step

- No new tools, no new agents, no new prompts.
- The route stays read-only. `answer_text` reaches the `orchestrator`
  allow-list, which grants no execution ([[Safety Invariants]] §1 is untouched
  because there is nothing here to route around).
- Streaming. The route answers when it has an answer; step 5 makes long work
  visible.

### Exit

- The same sentence, typed and spoken, produces the same reply text, the same
  `path`, and the same trace shape. **One test asserts it on both routes** —
  this is the property that decays silently otherwise.
- A test asserts the `operator` allow-list covers every tool the `orchestrator`
  allow-list grants for reading. Parity as a check, not a promise.
- `curl` with the daemon running and no audio hardware present answers a
  question that needs the large tier.

---

## Step 1 — Nobody knows the ticker

**Name resolution as a reflex.** [[Operating Model]] §7, [[Company Data Model]].

### The problem

`company/symbols.py` `normalise()` takes `nvidia`, finds it does not match
`^[A-Z0-9^][A-Z0-9.\-^=]{0,19}$`… actually it *does* match, and that is worse:
`NVIDIA` is a syntactically valid ticker that no exchange lists, so the request
travels one more hop and dies as `UnknownSymbol` on a vendor round trip. The
trader hears *"I don't know that symbol"* about the most-traded stock on earth.

Every command in `commands.py` that captures `(?P<symbol>…)` has this hole.

### The change

`company/names.py`, new and small:

- **Source:** EDGAR `company_tickers.json` — already a provider in this module,
  free, no key, carries the CIK the filings path needs anyway. Cached to disk;
  refreshed daily. See [[Open Questions]] §17 — decide before building.
- **Shape:** `resolve(text) -> Resolved(ticker, name, source) | Ambiguous(list)
  | None`. Three outcomes, and `None` — *"this is not a symbol"* — is a normal
  answer, not a failure. *"Gann"* returns `None`, and the caller treats it as a
  research subject.
- **No model.** A lookup against a real list. Asking a model for a ticker is the
  wrong tier and answers `NVDIA` with total confidence one day in a hundred.
- **Aliases** the SEC list will not have (`spoos`, `the semis`, `my usual`) live
  in a short hand-kept table beside it, not in a prompt.

Wired in front of `normalise` at the `commands.py` capture sites, and exposed as
a resolution step in front of the ladder so the model path benefits identically.

### Exit

- `what is nvidia` → NVDA. Typed and spoken.
- An ambiguous name **asks**, listing the matches. It never picks — a silently
  wrong ticker is a chart of a different company that looks entirely normal.
- The resolution is returned in the result payload and rendered, so a
  mis-resolution costs one glance rather than one trade.
- `research gann` does not attempt a ticker lookup.

---

## Step 2 — The canvas opens empty — **BUILT**

> [!done] Built 2026-09-06
> `home` is the first category and `DEFAULT_PAGE`. It has no seed and no dock:
> `App.tsx` branches on the page before it looks for one, so the landing screen
> is the command line and nothing else.
>
> **The command line is one component in two placements** — `CommandBar` grew a
> `variant` prop rather than a second search field. The alternative drifts
> within a week, and then the canvas and `⌘K` reach different catalogues, which
> is the parity failure again in miniature.
>
> Under the input, gone on the first keystroke: four literal example commands
> and this viewer's recents from `localStorage`. Neither holds data and neither
> is a panel, so §3 is intact — the starter content occupies the *input's* own
> space, which is where discoverability was always supposed to live.
>
> Also done here, and not in the original plan: **the safety strip collapsed to
> one line** and the top bar's search went from a 60px ghost button to a real
> field. Both are the same complaint — the chrome was spending its weight on
> things nobody asked for and starving the control that reaches everything.

**Mostly deletion.** [[Operating Model]] §3, [[Workspaces]].

### The change

- A `home` category in `shell/pages.ts`: `requires: null`, **no dock**.
- `DEFAULT_PAGE = 'canvas'`. Overview stays, reachable at `⌘2`, and stops being
  the front door. Nine pages now, so the shortcuts run `⌘1…⌘9`.
- The command line moves from a `⌘K` overlay to the **focal element of the
  empty canvas** — same component, same code path, rendered inline when the dock
  is empty and as an overlay when it is not. One implementation, two placements.
- Under the input: a row of literal example commands that vanishes on the first
  keystroke, and the resolution chip from step 1. See [[Open Questions]] §16 —
  decide before building.

### Not in this step

No new panel types. No landing-page widgets — the whole point is their absence.
The Overview page is not deleted; it is demoted.

### Exit

- Launch shows: command line, safety strip, core sigil. **No data panel.**
- One keystroke reveals pages, panels, series, agents and tools by name.
- The safety floor and kill switch are unaffected by all of it ([[UI Stack]] §6).

---

## Step 3 — Genesis opens panels, through the same door

**The efferent path to the surface.** [[Operating Model]] §5.

### The problem

`workspace/dock.ts` `openPanel` has exactly one caller: the command bar. The
orchestrator has **no path to the UI at all**. It can answer about a chart it
cannot show you.

### The change

The socket is one-directional by design ([[UI Stack]] §7 — commands go over
HTTP, events come back), so the path is an **event**, not a reverse call:

- New [[Event Schema]] kind `surface.panel_opened` — `panel`, `params`,
  `because` (`{request, trace_id}`), `by` (`orchestrator` \| `operator`).
  Priority `normal`; **never spoken** ([[Voice UX]] — an unknown kind is silent,
  and this one stays that way deliberately).
- The store folds it and calls the same `openPanel` the command line calls.
  One function, two callers, no private channel — which is what makes the
  parity rule checkable rather than aspirational.
- The panel chassis grows a provenance line: **what produced it**, **as of
  when**, **which request opened it**. Panels a person opened carry the same
  line saying `you`. There is no separate "agent output" surface.

Genesis **opens and sets**. It does not close a panel a person opened, and it
computes no geometry ([[Workspaces]]).

### Exit

- On an empty canvas, `chart NVDA` — typed **and** spoken — opens a chart panel
  labelled with the request that opened it.
- A panel opened by Genesis and the same panel opened by hand are
  indistinguishable except in that line.
- Closing a panel Genesis opened does not reopen it.

---

## Step 4 — Panels publish what they are showing

**The thing existing terminals cannot do.** [[Operating Model]] §5,
[[Terminal]] §still to build.

Bloomberg's panels do not publish; that is a design gap, not a model problem.
When a news panel and a chart are open on MSFT, *"why is MSFT down today"* must
read the open workspace rather than re-fetching the world.

### The change

- Panels register `{panel, subject, as_of, summary}` into a small surface
  registry on mount and on subject change.
- `GET /v1/surface` returns it — afferent, cheap, no session.
- `answer_text` includes it in `context`, the same slot the ambient buffer uses.
- **Symbol link groups**, which is the same mechanism from the other side:
  setting a ticker in one panel sets it in the group. Genesis joins a group as a
  **participant, not an owner**.

### Exit

- Ask a question about a symbol already on screen; the answer cites the open
  panel and the trace shows no duplicate fetch.
- Setting the symbol in one linked panel sets it in the others, whether a person
  or Genesis set it.

---

## Step 5 — Work that outlives the turn

**The Gann case.** [[Operating Model]] §6.

> *"Research W. D. Gann's findings and save them in my research journal."*

Three properties, none of which the current request/response shape has:

1. **Acknowledgement precedes work.** Speak step 1 before dispatching step 4. A
   multi-minute pass that answers with silence is indistinguishable from a hang.
2. **Progress is visible.** The task appears in [[Fleet View]] and as a
   work-in-flight panel: the steps named, who is on which, what has landed.
   `task.dispatched` / `started` / `completed` already carry this — nothing
   renders it as *one job* yet.
3. **The result is an artifact.** A vault note via `vault.*`, addressable
   tomorrow. Findings that exist only in a transcript have not been delivered.

### Dependency, stated plainly

This is the one step that is not self-contained. Doing it *well* needs at least
one registered research agent, which is [[Build Order]] Phase 4 — the planner
declines every utterance today because `registry.py` holds nothing.

Until then it runs on the reasoner's `research.*` tools, which is a real answer
and a slower one. **Build 1 and 3 now** — the acknowledgement and the vault
write are worth having on the tool path, and they are what makes the difference
between a system that feels employed and one that feels asked. Build 2's
single-job view with the agents.

### Exit

- A research request is acknowledged in under two seconds, describing what it is
  about to do.
- It is visible while it runs, as one job rather than as loose events.
- It lands as a vault note the trader can open the next morning.

---

## Not in UI-0

Stated so they are deferred rather than forgotten:

- **Writes from the command line.** Still refused twice, independently
  ([[Terminal]]). The approval gate is Phase 7.
- **Approval-mode control in the UI.** [[Safety Invariants]] §9.
- **The Tauri shell and the kill-switch hotkey.** UI-1 — and until then the note
  says plainly that the hotkey does not exist.
- **[[Genesis Core]] at `hero` tier.** UI-3. The only part the system can run
  without.
- **[[Research Canvas]].** Needs the Knowledge Graph, not a front end.
- **Multi-user anything.** One operator, one machine.

## Order, and why it is this one

| Step | Depends on | Why here |
|---|---|---|
| 0 · one answer path | — | Everything below assumes typed reaches the analyst |
| 1 · name resolution | 0 | Pure backend; the difference between three use cases and a system that understands you |
| 2 · empty canvas | — | Independent, mostly deletion; do it early so nothing new is built into the old shape |
| 3 · Genesis opens panels | 0, 2 | Needs a canvas to open into and a path to reach it from |
| 4 · panels publish | 3 | Needs the chassis change step 3 makes |
| 5 · work outlives the turn | 0, 3 | Needs the answer path and the surface; agents needed for its best form |

## Related

[[Operating Model]] · [[Build Order]] · [[Orchestrator]] · [[Terminal]] ·
[[Workspaces]] · [[UI Stack]] · [[Company Data Model]] · [[Event Schema]] ·
[[Open Questions]] · [[Safety Invariants]]
