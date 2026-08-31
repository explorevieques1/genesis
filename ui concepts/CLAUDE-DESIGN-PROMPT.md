# Claude Design prompt — Genesis Trading Orchestrator

Design a multi-artboard concept canvas for **Genesis**, a voice-driven, always-on autonomous
trading orchestrator. Genesis is a JARVIS-style command layer: the user speaks to one
orchestrator, which commands a fleet of ~30 specialist agents (research, chart markup,
strategy/backtest, execution/risk, journal/insight) over a task bus, behind an unbypassable
pre-trade risk gate. The UI is the *visual* half of a voice-first system — the voice says the
one-line answer, the screen carries the detail.

Treat this as a **command center**, not a dashboard app. It should feel like a private
mission-control surface owned by one operator, not a SaaS product page.

---

## 1. The hero: the Genesis core

The landing/idle screen is dominated by a large **3D vector animation of "Genesis"** —
a living wireframe intelligence, centered, on near-black.

Reference the style directly: thin luminous vector linework, orbital shells and nested rings
drawn as continuous curves, a dense particle nucleus at the center, radial emission spikes,
faint orbiting nodes with small ring glyphs. Not a solid 3D model, not glassmorphism — pure
stroked geometry rendered in light, like a data-viz of a particle collision or an orrery.
Depth comes from overlapping ellipses at different rotations, line-weight falloff, and
opacity, not shading.

Show the core in **four states** as separate artboards or a state strip:

| State | Read |
|---|---|
| **Idle / listening** | Slow orbital drift, dim nucleus, one breathing ring. Waiting. |
| **Thinking / dispatching** | Rings accelerate and counter-rotate; particles stream inward; agent nodes light up around the shell as tasks fan out. |
| **Speaking** | Nucleus pulses in time with the voice; a waveform ring modulates on the outer shell. |
| **Risk / halt** | Palette flips to amber→red, the outer shell hardens into a closed containment ring, orbit freezes. |

Around the core, keep the screen mostly empty. Only a thin ring of ambient telemetry:
market session clock, P&L today, open positions count, agents active, approval mode,
and a single line of live transcript ("*Genesis, how's my book looking?*").

At the bottom: a **voice input bar** — waveform/level meter, wake-word indicator, push-to-talk
affordance, and a text fallback field. This is the primary input for everything.

---

## 2. Screens summon into the space

The key interaction: the user *asks*, and Genesis materializes the right screen. Show this
as a mechanic, not just a set of static pages.

- Panels **assemble out of the core** — vector lines extend from the orbital shell and
  resolve into a framed panel. Show 2–3 frames of that transition on its own artboard.
- Multiple panels can coexist: a **canvas/tiling model** where the user says "put the chart
  next to the risk gate" and panels dock, split, or float. Show single-panel, split-pane,
  and a dense 6-up "wall" layout.
- The core **shrinks to a persistent corner sigil** once panels are up, still animating,
  still listening — always visible, never gone.
- Every panel has: title, live/stale data indicator, the agent that produced it, timestamp,
  and dismiss/pin controls. Pinned panels survive the next question.

Include a **command palette / intent overlay**: what the user said, how Genesis parsed it
(intent → agents dispatched → tools called), and the resulting screen. This makes the
orchestration legible.

---

## 3. Screen types to design

Design each as its own artboard, at desktop scale, all sharing one panel chassis:

1. **Chart & markup** — full candlestick chart with agent-drawn annotations: levels, zones,
   trendlines, entry/stop/target brackets, each tagged with the agent that drew it and a
   confidence value. Timeframe switcher, indicator strip, volume.
2. **Portfolio / book** — equity curve, open positions table with live P&L, exposure by
   asset, allocation donut, win rate, drawdown.
3. **Agent fleet view** — the strongest secondary screen. A flow graph in the spirit of the
   command-center reference: data sources on the left → the orchestrator core in the middle →
   agent families fanning out right, with animated flow lines carrying task counts. Per-agent
   status: idle / running / blocked / failed, tokens spent, last output.
4. **Research brief** — pre-market or on-demand narrative: headline thesis, catalysts, news
   cards with sources, sentiment gauge, related tickers. Text-forward, readable.
5. **Backtest / strategy lab** — parameter panel, equity curve vs. benchmark, trade
   distribution, Sharpe/drawdown/expectancy stat tiles, run history.
6. **Risk gate & execution** — the most important screen to get right. A pending order card
   showing symbol, side, size, entry/stop/target, R multiple, and the risk envelope it's
   being checked against (max position, daily loss remaining, allowed symbols, session).
   Explicit **PASS / BLOCKED** verdict with the rule that fired. Approval mode selector
   (`advisory` / `confirm` / `auto-within-limits` / `halt`) and a large, unmistakable
   **HALT / flatten-all** control.
7. **Journal & memory** — timeline of trades, decisions, and lessons; linked-note graph view
   of the memory fabric; searchable episodic log.
8. **Alerts / notification rail** — a right-edge stack of agent-pushed cards: setup found,
   regime shift, risk breach, order filled. Each with severity, source agent, and a
   "show me" action that summons the relevant panel.

Also include: a **mobile/companion view** (core + voice bar + alert stack only), and an
**empty/first-run state**.

---

## 4. Visual system

- **Ground:** near-black (#05070A–#0B0F14), with a subtle radial vignette. No pure white
  anywhere. Panels are 3–6% lighter than ground with 1px hairline borders, not drop shadows.
- **Accent:** a single cyan-teal signal color for the intelligence (core, active state,
  primary data), used sparingly so it means something.
- **Semantics:** green = long/profit/pass, red = short/loss/blocked, amber = pending/warning.
  Semantic color is for data only — never for chrome.
- **Type:** a clean geometric or grotesk sans for UI; **tabular monospace for every number** —
  prices, P&L, sizes, times. Numbers must align in columns and never jitter as they tick.
- **Density:** information-dense in the panels (a trader's terminal — many small readouts,
  tight rows, sparklines inline), spacious around the core. The contrast between the calm
  hero and the dense panels is the point.
- **Motion:** everything eases; nothing bounces. Flow lines, orbital rotation, and value
  transitions are continuous, not stepped.
- **Persona:** calm, precise, British-butler register. Confident, never hyped. No gradients-
  as-decoration, no marketing copy, no emoji in the UI.

---

## 5. Deliverables

A canvas of artboards covering: the four core states, the panel-summoning transition,
each of the eight screen types, the split and 6-up layouts, the mobile companion, and a
final style-tile artboard (palette swatches, type scale, panel chassis, button/chip/tile
components, chart tokens, status indicators, the core sigil at three sizes).

Use realistic placeholder data throughout — real tickers, plausible prices and P&L,
believable agent names — never lorem ipsum.
