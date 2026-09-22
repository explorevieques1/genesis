---
title: Genesis Core
tags: [ui]
status: building
implemented_by: [ui/src/components/GenesisCore.tsx, ui/src/shell/CommandBar.tsx, ui/src/graph/nodes/CoreNode.tsx, ui/src/components/Primitives.tsx, ui/src/lib/motion.ts, ui/src/lib/speak.ts]
---

# 🔮 Genesis Core

The animated presence at the centre of the idle screen, and the corner sigil once
panels are up. [[Desktop Shell]] calls this the **face widget** and is right about
why it exists: *it makes the difference between "is it listening?" and knowing it is.*

This note specifies what it shows, what it may never be trusted to show, and how it
is built.

## What it is for

A voice-first system has a hard problem: between the wake word and the first
syllable of a reply there are several seconds in which the operator cannot tell
whether they were heard, whether anything is happening, or whether it has hung. Text
status fills that gap badly — it demands reading, at exactly the moment the operator
is looking somewhere else.

The core fills it pre-attentively. It is [[Voice UX]]'s earcons rendered as light:
the same state machine, a second sensory channel, no words.

That is its entire job. It is **an ambient indicator of liveness and mode** — not a
data display, and never the only place a fact appears.

The idle screen is **Home** (`CommandBar` inline variant), where it sits above the
command line. It is *not* rendered inside [[Fleet View]]: a particle canvas driven
by `requestAnimationFrame` inside React Flow churned the graph and let the node
overlap the inner band, so the fleet centre is a plain bold node (`CoreNode`) and
the animated presence lives only where it has a job to do.

## States

Five, one-to-one with the [[Voice UX]] state machine. Same source of truth as the
tray icon in [[Desktop Shell]]; three renderings, one machine.

| State | Reading | Motion |
|---|---|---|
| `idle` | listening for the wake word | slow orbital drift, dim nucleus, one breathing ring |
| `listening` | actively hearing you | shell tightens, particle density rises toward the nucleus |
| `working` | agents are running | rings counter-rotate and accelerate; particles stream inward; emission spikes fire per completed task |
| `speaking` | replying | nucleus pulses to the TTS envelope; a waveform modulates the outer shell |
| `alert` | risk breach, degraded, or **halted** | palette flips amber→red, the outer shell closes into a containment ring, orbit freezes |

Transitions are eased uniform interpolations, not scene swaps — the whole point is
that the change is perceived without being looked at. `alert` is the exception: it
snaps. A frozen orbit reads as *wrong* instantly, which is the intent.

`working` carries real information, cheaply: emission events are keyed to
`task.completed` ([[Fleet View]] §Events), so a busy fleet visibly seethes and a
stalled one visibly does not. An operator learns the difference between "thinking"
and "hung" in about a day, without being taught it.

## What it may never be

> [!important] The core is decoration over a state machine, and it is not evidence
> Halt, risk breach and degradation appear on the core **in addition to** the plain
> DOM safety floor ([[UI Stack]] §6), never instead of it. If the WebGL context is
> lost the operator must lose no safety-critical information — only the ambience.

Three prohibitions follow:

1. **Never the sole indicator of `halted`.** [[Kill Switch]] state is DOM, always painted.
2. **Never a control.** Clicking the core does nothing. A large glowing target in the
   centre of the screen must not be able to act.
3. **Never a number.** It shows *mode*, not P&L, not heat, not headroom. Numbers are
   tabular and readable, or they are not shown ([[Dashboard]] §Glanceable).

The design failure to avoid is the one where the animation is beautiful, the operator
learns to read it, and then a dropped GPU context makes the system look calm while it
is halted.

## Build

**three.js + React Three Fiber**, with `postprocessing` for selective bloom — bloom
is most of the look. Positions live in a data texture and are stepped in a compute
pass, so the CPU never touches per-particle state.

Technique: points sampled on a sphere by Fibonacci distribution, displaced per frame
by curl noise sampled at `position * frequency + time`, additive blending,
`depthWrite: false`, size attenuation, colour ramped by displacement magnitude — the
ramp is what produces the warm crest flare against the cool shell.

The five states are uniform sets — `noiseAmplitude`, `rotationSpeed`, `bloomIntensity`,
`colorRampOffset`, `shellRadius` — lerped between. This is why transitions are cheap
and why `alert` can be authored as a snap rather than a different scene.

Prefer **three.js TSL / WebGPURenderer** where available, with a WebGL2 fallback: TSL
compiles compute shaders from JS, which puts a million-particle sim within reach
without hand-written ping-pong FBOs. Use **Leva** in development to tune the look
live; the resulting values are committed as presets, and Leva is not shipped.

### The sigil is a different technology

Once panels are up the core shrinks to a persistent corner sigil, and at that point
it is **Rive**, not three.js — a state-machine-driven vector animation, same five
states, no WebGL context alive at all.

This is [[UI Stack]] §6's `ambient` tier, and it is the whole reason the tier exists.
Keeping a particle simulation running behind a wall of live charts costs frames that
[[Dashboard]] needs and buys nothing: at sigil size the particle detail is invisible.
Two technologies, because the two jobs are genuinely different.

A static SVG in the same five states is the `reduced` and `degraded` fallback.

## Accessibility

`prefers-reduced-motion` drops to the static SVG sigil. Every state is distinguishable
by **shape and value**, not by hue alone — `alert` closes the shell and freezes, which
survives both a monochrome screenshot and a red-green colour deficiency. The state is
also exposed as text to assistive technology and to the tray tooltip.

## Acceptance criteria

- All five states are identifiable in a still frame, in greyscale.
- `hero` tier holds 60 fps on the target GPU with bloom enabled.
- `ambient` tier holds **no live WebGL context** — verifiable, not asserted.
- Killing the WebGL context leaves every safety-critical value readable.
- The core, tray icon and [[Voice UX]] earcons never disagree about state.
- `prefers-reduced-motion` yields the static sigil with no animation frames scheduled.
- Clicking the core has no effect.

## Related

[[UI Stack]] · [[Dashboard]] · [[Fleet View]] · [[Voice UX]] · [[Desktop Shell]] ·
[[Kill Switch]] · [[Error Handling And Degradation]]
