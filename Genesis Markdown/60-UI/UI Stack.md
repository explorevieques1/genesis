---
title: UI Stack
tags: [ui, architecture]
status: building
implemented_by: [ui/package.json, ui/vite.config.ts, ui/src/styles/tokens.css, ui/src/transport/transport.ts, ui/src/transport/live.ts, ui/src/lib/format.ts, ui/src/components/SurfaceBoundary.tsx, ui/src/components/TapToSpeak.tsx, src/genesis/server/app.py, src/genesis/commands.py, tests/test_server.py, tests/test_commands.py]
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
put the chart next to the risk gate"* resolves to a named layout preset, not to
freehand window arithmetic. Presets live in config; the voice path selects among
them and may create one, never computes pixel geometry.

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

## 5. Data surfaces

| Surface | Library | Why |
|---|---|---|
| Price charts | **TradingView Lightweight Charts** | The actual financial chart. Price lines, markers and custom series map onto [[Markup Spec]] annotations directly ([[Charting Engine]]) |
| Dense time series | **uPlot** | Sparklines, equity curves, gauges-over-time. Handles tens of thousands of points; a wall of these is the [[Dashboard]] steady state |
| Categorical / structural | **ECharts** | Allocation, correlation clusters, exposure. Themeable to the token layer |
| Agent graph | **React Flow + elkjs** | See [[Fleet View]] |
| The core | **three.js / R3F**, **Rive** | See [[Genesis Core]] |

Recharts and Chart.js are ruled out here — fine for one marketing chart, not for
twelve live panels sharing a frame budget.

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

The app lives at `ui/`. `npm run dev` runs it; it is a browser app today, not yet
a [[Desktop Shell|Tauri]] one.

| §  | Specified | Built | Gap |
|---|---|---|---|
| 1 | Tauri v2 shell | — | Browser only. **The kill-switch hotkey therefore does not exist yet** — the in-app button posts directly to the kill-switch process, and the note's guarantee that the hotkey survives a white-screened WebView is *not* met until the Rust host is written. The UI says so rather than implying otherwise. |
| 2 | React + TS + Vite | ✅ | `ui/src/types/events.ts` is hand-written against [[Event Schema]]. Generating it and the Python side from one source is still to do; until then the two can drift, and only review catches it. |
| 3 | Dockview panels | ✅ | Built, across eight pages — see [[Workspaces]]. Presets are named and declarative (`workspace/presets.ts`); a person's own arrangement serialises to `localStorage` per preset and `reset` restores the declared one. [[Voice UX]] now has named targets. Dockview v8 moved its React bindings to `dockview-react`; the core is framework-agnostic. |
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

[[Dashboard]] · [[Fleet View]] · [[Genesis Core]] · [[Desktop Shell]] ·
[[Widget Catalog]] · [[Event Schema]] · [[Error Handling And Degradation]] ·
[[Observability]] · [[Conventions]]
