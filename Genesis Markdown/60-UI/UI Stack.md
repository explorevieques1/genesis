---
title: UI Stack
tags: [ui, architecture]
status: building
implemented_by: [ui/package.json, ui/vite.config.ts, ui/src/styles/tokens.css, ui/src/transport/transport.ts, ui/src/transport/live.ts, ui/src/lib/format.ts, ui/src/components/SurfaceBoundary.tsx, ui/src/components/TapToSpeak.tsx, src/genesis/server/app.py, src/genesis/commands.py, tests/test_server.py, tests/test_commands.py, ui/src/main.tsx, ui/src/App.tsx]
---

# 🧱 UI Stack

The technology decisions behind [[Dashboard]], [[Fleet View]] and [[Genesis Core]],
and the reasoning for each. Written before any UI code exists so the first commit
does not become the decision.

This note is about *how*. [[Dashboard]] is about *what*.

> [!note] Wired to a real backend — 2026-09-04
> The transport note said *"not wired yet — the daemon has no socket surface"*.
> It has one now: `src/genesis/server/app.py`, Starlette + uvicorn (already
> present via the MCP SDK), started with **`genesis serve`**. Loopback only.
>
> Three things changed and each was a correctness fix, not a feature:
>
> 1. **The transport defaults to live, not mock.** Mock-by-default is what made
>    the surface a demo: it opened onto a busy simulated fleet whether or not
>    anything was running. Live-by-default means an unstarted server shows as
>    honestly disconnected, which is more useful than a convincing fake.
>    `VITE_GENESIS_MOCK=1` still gets the mock for UI work.
> 2. **The clock stops when nothing is moving.** The surface ran a
>    requestAnimationFrame loop at ~20 fps unconditionally — 25 React Flow
>    nodes and 54 store subscriptions re-rendering twenty times a second to
>    show an idle fleet. Now gated on `selectBusy`: 1 Hz at rest, 10 fps while
>    a task is in flight. An organism at rest should cost nothing.
> 3. **The envelope shape is pinned by a test.** The server's first version
>    emitted `trace`/`at`/`severity`; the store reads `trace_id`/`ts`/`priority`
>    and ignores everything else. That failure is silent from both ends — a UI
>    that looks connected and does nothing — so
>    `tests/test_server.py::test_the_envelope_matches_the_uis_contract_exactly`
>    holds it in place.
>
> **Push-to-talk** is `ui/src/components/TapToSpeak.tsx`: hold the button or the
> space bar, release to send. Audio is transcribed locally by faster-whisper
> (`tiny.en`) and never leaves the machine. No hot mic and no wake-word model —
> the tap is the addressing, so nothing listens until asked.

> [!important] What the surface is *for* — [[Operating Model]]
> This note is the *how*. [[Operating Model]] is the *who*: the trader commands,
> Genesis advises, and three of its rules bind the stack directly —
> **the canvas opens empty** (§3), **typed and spoken are one path** (§4), and
> **Genesis drives the same dock the human does** (§5). Read it before adding
> surface.

## The governing constraint

> [!important] The UI is a client, and a client may fail alone
> [[Desktop Shell]] already states the separation: closing the UI must never stop
> trading. This note adds the inverse, which matters more once there is a GPU in
> the picture — **the UI failing must never hide risk.** A lost WebGL context, a
> dropped socket, or a wedged renderer must degrade to something that still shows
> position, heat, approval mode and the [[Kill Switch]]. See §6.

## 1. Shell — Tauri v2

Native wrapper, Rust host, system WebView. Chosen over Electron:

- ~10 MB binary against ~200 MB, and one WebView process rather than a bundled Chromium
- Real tray, real global hotkeys, real OS notifications — all four things
  [[Desktop Shell]] asks for
- The **kill-switch hotkey lives in the Rust host, not the web layer.** It fires when
  the WebView is white-screened, which is exactly the case [[Desktop Shell]] requires
  and the case Electron's renderer-side accelerators do not survive

The Rust host talks to the Python daemon over a local socket. It holds no trading
logic — it is transport, tray, hotkey, and window management only.

[[Repo — Gensis Terminal Official]] is Electron. Its **widgets are HTML and portable**;
the shell is not. Port the widgets, not the shell ([[Widget Catalog]]).

## 2. Frame — React + TypeScript + Vite

Not a framework choice so much as the price of the ecosystem below (React Flow, R3F,
Dockview all assume it). TypeScript is non-negotiable: [[Event Schema]] should be
generated into TS types from the same source that generates the Python side, so a
renamed event breaks the build rather than blanking a panel at runtime.

## 3. Panels — Dockview

Dockable, splittable, floating, serialisable panel layout. This is the "summon a
screen and put it next to the other one" mechanic, and hand-rolling it is a
multi-week detour.

Layouts serialise to JSON, which gives [[Voice UX]] something to target: *"Genesis,
put the chart next to the risk gate"* resolves to a **module short code plus a
category** — `open CH in charting` — not to freehand window arithmetic. The
constraint is the one that matters: the voice path *selects a named thing*, and
never computes pixel geometry. Selecting from a named set is classification,
which a model is good at; pixel arithmetic is not.

> Named layout **presets** were the first form of this target and have been
> removed — see [[Workspaces]] §Seeds. Fourteen arrangements behind a switcher
> is a menu of layouts somebody else designed, where a terminal wants a space
> you fill yourself. Modules carry the names now.

## 4. Chrome — Tailwind v4 + Base UI

Unstyled behavioural primitives (Base UI, or Radix) plus a hand-authored token
layer. Explicitly **not** a pre-styled component kit.

The reason is [[Dashboard]]'s own acceptance criteria: *live mode must be visually
unmistakable* and *stale data must look stale*. Both are whole-surface visual states,
not badges. A kit whose components carry their own colour opinions fights that, and
the fight is lost in a hundred small overrides. Own the tokens, and `live` can
restyle every panel border, number colour and chrome tint from one place.

Tokens carry the semantics, not the palette: `--state-live`, `--state-stale`,
`--verdict-blocked` — never `--red-500` at a call site.

> [!important] Contrast is a token-layer property, and it was failing — fixed 2026-09-06
> Owning the tokens is what made this a one-file fix, and it is also what let it
> go wrong everywhere at once. Measured against `--bg-void`, the bottom of the
> ink ramp was **`--ink-faint` at ~2.8:1 and `--ink-ghost` at ~1.55:1**. WCAG's
> floor is 4.5:1 for body text and 3:1 for large text, and `.label` — every
> field caption on the surface — uses `--ink-faint`. The captions were below the
> legibility floor in every panel simultaneously.
>
> Two things compounded it, and neither was visible in the token file:
>
> 1. **Opacity multiplied the ramp.** [[Fleet View]]'s agent nodes drew
>    `--ink-dim` at `opacity: 0.34` for an unbuilt agent — and most of the fleet
>    *is* unbuilt today, so the organism view read as empty when it was full.
>    Recession is now `--dim-out` / `--dim-unbuilt` / `--dim-unseen` in the
>    token layer, because a value that multiplies the ink ramp belongs beside
>    it, not as a literal in a node component.
> 2. **Panels were separated from the ground by a hairline alone** — six units
>    of luminance between `--bg-panel` and `--bg-void`. The hairline is the
>    *seam*; it cannot be the only thing that makes a panel a distinct surface.
>
> The ramp now bottoms out near 4:1, `--ink-faint` clears 6:1, and two state
> colours that failed the 3:1 floor were lifted: `--state-idle` (2.24 → 4.60)
> and `--state-stale` (2.71 → 6.36). The second mattered most — stale must look
> degraded *and* stay readable, because it labels a number the operator has to
> make a decision about, and the warning was harder to read than the thing it
> warned about.

> [!important] The scales, audited — 2026-09-06
> Three of the four systems this note claims to own were not systems.
>
> **Type had no hierarchy where the text is.** Four steps inside three pixels
> — 10.5 / 11.5 / 12.5 / 13.5, each ~1.08× the one below — is four *names* for
> one size. Measured across the surface: `--fs-micro` had **83** call sites and
> `--fs-base` had **7**. Almost every word was rendered at the smallest
> available size, which is the entire content of *"everything looks the same"*.
> The scale is now ~1.15× widening to 1.4×, and every step is perceptibly
> larger than the one beneath it.
>
> **Spacing had no scale.** 3, 5, 7, 9, 11 and 13 px were all in use across
> inline styles. A 2px base step is legitimate here — the canonical 4/8/16 is
> too coarse for 20px rows — but a *dense* scale is still a scale. `--s-1` …
> `--s-8` now exist and the shell uses them; charts and graph nodes are exempt,
> because those are drawings rather than layout.
>
> **There was no elevation system at all.** The consequence was visible on the
> element that needed it most: the ⌘K palette floats above the entire surface
> with a 1px hairline and no shadow, so it read as painted on rather than
> above. `--shadow-sm` … `--shadow-xl` are two-part (tight dark edge + diffuse
> ambient) and carry real opacity, because a 0.05 alpha shadow is invisible on
> a near-black ground. Applied only to things that genuinely float — the
> palette and Dockview's floating groups. Tiled panels get none: if everything
> floats, nothing has depth.
>
> **What still fails:** 78 inline `--fs-micro` uses are on *content*, not
> captions. `.label` at the smallest size is correct and stays; body text
> borrowing the caption size is the remaining hierarchy debt, concentrated in
> `AgentInspector`, `TraceView` and `ExecutionPath`.

## 5. Data surfaces

| Surface | Library | Why |
|---|---|---|
| Price charts | **TradingView Lightweight Charts** | The actual financial chart. Price lines, markers and custom series map onto [[Markup Spec]] annotations directly ([[Charting Engine]]) |
| Dense time series | **uPlot** | Sparklines, equity curves, gauges-over-time. Handles tens of thousands of points; a wall of these is the [[Dashboard]] steady state |
| Categorical / structural | **ECharts** | Allocation, correlation clusters, exposure. Themeable to the token layer |
| Agent graph | **React Flow + elkjs** | See [[Fleet View]] |
| Research canvas | **React Flow** | See [[Research Canvas]]. The second legitimate use of it: addressable nodes with React content, panned and zoomed. Named here rather than left implicit, so the canvas could not quietly adopt a third graph library |
| The core | **three.js / R3F**, **Rive** | See [[Genesis Core]] |

Recharts and Chart.js are ruled out here — fine for one marketing chart, not for
twelve live panels sharing a frame budget.

The journal's force-directed view is **not** a third React Flow surface. It is a
canvas-drawn d3-force graph for a thousand undifferentiated dots, which is a
different problem with a different answer: React Flow renders a DOM node per
node, and a thousand of those is a frozen tab.

## 6. Frame budget and the degradation ladder

The [[Genesis Core]] particle system and a full [[Dashboard]] cannot both run at
full quality. This is a design constraint, not a tuning problem, so it is specified
rather than discovered:

| Tier | When | Core | Panels |
|---|---|---|---|
| `hero` | core is the focused surface, no dense panels | full particle count, bloom | — |
| `ambient` | panels are up, core is the corner sigil | Rive sigil, **no WebGL context** | full |
| `reduced` | GPU lost, thermal throttle, `prefers-reduced-motion` | static SVG sigil | full |
| `degraded` | socket down, or the renderer failed | static sigil | last-known values, **all marked stale** |

The ladder is one-way under fault and automatic: nothing about it waits for a user
choice. Dropping a tier is logged as `ui.tier_changed` — a UI that quietly went
blind is the failure [[Error Handling And Degradation]] is written against.

**The safety floor sits below all four tiers.** Position, portfolio heat, daily-loss
headroom, approval mode and the [[Kill Switch]] render in plain DOM, from the last
value received, with no dependency on WebGL, canvas, or the socket being alive.
They are the first thing painted and the last thing to fail.

> [!warning] Collapsed to one line — 2026-09-06, and it must expand again by Phase 7
> The floor was five cells and ~60px of permanent chrome, and in this phase four
> of them render an em dash: there is no broker, no position, no reconciliation.
> [[Operating Model]] §3 says nothing is on screen that was not asked for, and a
> row of placeholders is the purest case — it trains the operator to ignore the
> strip, which is the wrong habit for the one component that must be believed
> when the numbers become real.
>
> So the default is a **single line** carrying approval mode, halted state and
> feed status, expanding to the full grid on click; the full readout also lives
> in `Settings → Approval`, rendered by the same component so the summary and
> the detail cannot disagree.
>
> **Every property above is unchanged** — plain DOM, first painted, no WebGL or
> socket dependency, its own error boundary, and `halted` is never collapsed
> away. What changed is how much room it takes when it has nothing to report.
>
> **This is a concession to an empty system, not a design for a loaded one.**
> Heat and daily-loss headroom become live the moment there is a position, and
> a number that matters behind a click is a number nobody reads. Restore the
> expanded grid to the chrome in [[Build Order]] Phase 7.

## 7. Transport

One WebSocket, per [[Dashboard]] §Transport, carrying [[Event Schema]] envelopes off
the [[Task Bus]]. Additions the UI needs are specified in [[Fleet View]] §Events.

Rules:

- The socket is **read-mostly**. Commands go over HTTP to the daemon so they carry
  a response, an idempotency key, and an audit line. A fire-and-forget socket frame
  is the wrong shape for anything that acts.
- The [[Kill Switch]] does not use either. Direct HTTP to the kill-switch process,
  from the Rust host, as [[Desktop Shell]] already specifies.
- On reconnect the UI requests a state snapshot by `trace_id` watermark and replays
  forward. It never assumes continuity across a gap; a gap it cannot close puts the
  surface in `degraded`.

## 8. Type discipline

Prices and sizes arrive as **strings** and stay strings until formatted.
[[Conventions]] §Money says `Decimal`, never `float`, on the Python side; JSON
numbers are IEEE 754 doubles, so parsing a price into a JS `number` silently
discards that guarantee at the boundary. Format from the string; never arithmetic
in the UI. Any number the UI needs to *compute* is computed by an agent and sent.

## 9. What is deliberately not here

- **No client-side state store of record.** No Redux slice that owns positions. The
  UI renders pushed state ([[Widget Catalog]] §Widget contract); a refresh loses nothing
  because there is nothing to lose.
- **No UI-side risk logic.** Not a preview, not a "likely to be rejected" hint. The
  verdict comes from [[Pre-Trade Risk Engine]] or it is not shown ([[Safety Invariants]] #1).
- **No offline mode.** Stale and labelled, or nothing.

## Build status — what exists, and what does not

*Updated 2026-09-05.*

Written when the first UI commit landed, because a note that describes a stack the
code does not have is **proprioceptive drift** ([[Biological Design]]), and this
one describes six technologies of which three are not yet in the tree.

The app lives at `ui/`. `./genesis up` (repo root) runs it; it is a browser app
today, not yet a [[Desktop Shell|Tauri]] one.

**Dev loop (2026-09-14).** `./genesis up` starts `genesis serve` detached (log:
`~/.genesis/logs/serve.log`) and then vite in the foreground, so a UI restart
never re-boots the ~15 MCP servers. The frontend hot-reloads; the backend does
**not** — `./genesis reload` restarts the daemon after Python edits. Auto-restart
on save was removed: a burst of edits meant a burst of full fleet boots. Plain
`npm run dev` still spawns a daemon if none is up, logged to the same file, dying
with vite.

| §  | Specified | Built | Gap |
|---|---|---|---|
| 1 | Tauri v2 shell | — | Browser only. **The kill-switch hotkey therefore does not exist yet** — the in-app button posts directly to the kill-switch process, and the note's guarantee that the hotkey survives a white-screened WebView is *not* met until the Rust host is written. The UI says so rather than implying otherwise. |
| 2 | React + TS + Vite | ✅ | `ui/src/types/events.ts` is hand-written against [[Event Schema]]. Generating it and the Python side from one source is still to do; until then the two can drift, and only review catches it. |
| 3 | Dockview panels | ✅ | Built. **One dock per main category** — nine workspaces, each seeded once from `SEEDS` and then the operator's own, serialised to `localStorage` per category. Every panel is a **module** with a short code (`workspace/modules.ts`), spawnable into any workspace, any number of times. Named presets are gone; [[Voice UX]]'s target is a module code plus a category. `clear space` empties a workspace. Dockview v8 moved its React bindings to `dockview-react`; the core is framework-agnostic. |
| 4 | Tailwind v4 + Base UI | partial | Tailwind v4 is wired for layout utilities; the token layer in `ui/src/styles/tokens.css` is hand-authored and semantic as the note requires. **Base UI is not used and probably will not be** — `@base-ui-components/react` does not resolve, and the handful of controls the shell needs (button, field, chip, table, section) are twenty lines each in `components/Primitives.tsx`. The note chose Base UI *because* it is unstyled; hand-rolled is unstyled by construction. Revisit if a real behavioural primitive is needed — a combobox, a focus-trapped dialog. |
| 5 | Lightweight Charts · uPlot · ECharts | partial | Lightweight Charts draws the price surface (`components/charts/PriceChart.tsx`); uPlot draws the backtest equity curve with its drawdown band. ECharts is installed and unused — nothing categorical is built yet. React Flow + `elkjs` **is** in, per [[Fleet View]]. `d3-force` was added for the journal graph: a thousand undifferentiated dots on one canvas is a different problem from React Flow's addressable nodes. **Gotcha worth keeping:** these libraries parse colour strings themselves and reject CSS `color-mix()` — Lightweight Charts throws and renders an empty chart with no visible error. `format.withAlpha()` exists for this. |
| 5 | three.js / R3F + Rive for the core | partial | [[Genesis Core]] is a 2D canvas particle field — the same Fibonacci sphere, curl-ish displacement, additive blend and five uniform sets, **with no WebGL context at all**. That satisfies the `ambient` tier as specified and defers `hero`. The static SVG sigil for `reduced` / `degraded` is built. |
| 6 | Degradation ladder | partial | The ladder, the automatic drop under fault, and the safety floor are built. `SurfaceBoundary` catches a render failure and still paints heat, headroom, approval mode and the kill switch. `hero` has no distinct behaviour because there is no WebGL tier to drop from. |
| 7 | One read-mostly socket | ✅ | `LiveTransport` implements the socket, the watermark reconnect and the gap semantics, and `src/genesis/server/app.py` is the endpoint. The mock transport is no longer wired. Reads are served by `server/reads.py` — all afferent, money as strings, and absence reported as `{available: false, reason}` rather than as an empty list. |
| 8 | Strings for money | ✅ | `ui/src/lib/format.ts` formats from strings and never parses a price. The one float is a gauge's pixel width, which is never shown as a number. **The formatters are total** — they accept `undefined` and render an em dash. That is not defensiveness: a snapshot field the server did not send reached `money()`, threw, and unmounted the entire tree including the safety floor and the kill switch. The snapshot's shape is now pinned by a test on both sides. |
| 9 | No state store of record | ✅ | The Zustand store is a pure fold of the event stream. It computes no position, no P&L and no risk verdict. |

Closing the `mock → live` gap needs one thing from the daemon: an endpoint that
streams [[Event Schema]] envelopes off the [[Task Bus]] and answers a snapshot
request by watermark. Nothing in `ui/` changes when it appears except two
environment variables.

## Related

[[Operating Model]] · [[Dashboard]] · [[Fleet View]] · [[Genesis Core]] · [[Desktop Shell]] ·
[[Widget Catalog]] · [[Event Schema]] · [[Error Handling And Degradation]] ·
[[Observability]] · [[Conventions]]
