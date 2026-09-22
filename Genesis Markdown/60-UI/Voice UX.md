---
title: Voice UX
tags: [ui, voice]
status: built
implemented_by: [src/genesis/voice/speech.py, src/genesis/voice/earcons.py, src/genesis/voice/policy.py, src/genesis/orchestrator/verbosity.py, tests/test_earcons.py, tests/test_speech.py, tests/test_speech_dates.py, tests/test_speech_policy.py, tests/test_verbosity.py, src/genesis/server/voice_routes.py, ui/src/components/TapToSpeak.tsx, ui/src/shell/CommandBar.tsx]
---

# 🗣️ Voice UX

How Genesis sounds, and when it speaks. Technical pipeline: [[10-Architecture/Voice Stack]].

> [!note] Voice is a peer input, not the door
> [[Operating Model]] §4 — the typed sentence and the spoken one reach the same
> command table and the same orchestrator behind it, and **unplugging the
> microphone must remove no capability**. Everything below is about the spoken
> *channel*; none of it is about what the system can be asked to do.

## Persona

Calm, concise, precise. A capable colleague, not an assistant and not a hype machine.

- **Never** hypes a setup. "NVDA long, confidence 0.72" — not "great setup on NVDA!"
- **Never** reassures after a loss. Reports it and moves on.
- Speaks numbers exactly. Rounds only where precision is meaningless.
- Volunteers the uncomfortable thing.
- Short. Detail goes to the [[Dashboard]] and the vault.

## Speaking numbers

The most common way a voice trading assistant becomes unusable is by reading numbers
badly.

| Written | Spoken |
|---|---|
| `121.06` | "one twenty-one oh six" |
| `1,642.00` | "sixteen forty-two" |
| `$312` | "three hundred twelve dollars" |
| `0.72` (confidence) | "point seven two" or "seventy-two percent" |
| `+1.2R` | "plus one point two R" |
| `-2.1%` | "down two point one percent" |
| `NVDA` | "N-V-D-A" — never "nividia" |
| `SPY` | "spy" |
| `ES`/`NQ` | "E-S" / "N-Q" |
| `08:30` | "eight thirty" |
| `2.4x` | "two point four times" |
| `1993` (year) | "nineteen ninety-three" — never "one thousand nine hundred ninety-three" |
| `2026` (year) | "twenty twenty-six" |
| `2005` (year) | "two thousand five" |
| `April 5, 1993` | "April fifth, nineteen ninety-three" |
| `2026-09-02` | "September second, twenty twenty-six" |
| `1995` (a count) | "one thousand nine hundred ninety-five" — **unchanged** |

Tickers are spelled unless they're conventionally pronounced. Prices are read the way
traders say them, not the way a screen reader would.

> [!important] A year is not a number, and the difference is context, not digits
> `1995` is a year in *"founded in 1995"* and a share count in *"sold 1995
> shares"*. Nothing about the digits distinguishes them, so a bare number is
> **left as a cardinal** unless something nearby says otherwise — a month name,
> a date pattern, or a cue word (`in`, `since`, `founded`, `fiscal`, `Q3`, …).
>
> The default is deliberately the clumsy reading rather than the confident one.
> A missing cue costs *"one thousand nine hundred ninety-three"*, which is ugly;
> a false positive would read a fill at `2000` as *"twenty hundred"*, which is
> wrong about money. `at`, `to` and `of` are excluded from the cue list for
> exactly that reason.
>
> Found the honest way: asked aloud when NVIDIA was founded, Genesis said
> *"April five, one thousand nine hundred ninety-three"*. Two bugs in one
> sentence.

## Verbosity levels

Configurable, and switchable mid-conversation ("give me the full version").

| Level | Example |
|---|---|
| `terse` | "Four ideas. Top is NVDA long." |
| `brief` *(default)* | "Four ideas ranked. Top is NVDA long from one twenty-one, invalidation one eighteen forty, confidence point seven two. Chart's on the dashboard." |
| `full` | Adds the thesis, the catalyst, the conflicts, and the runners-up. |

**Built** — `orchestrator/verbosity.py`. The level reaches the model as a length
instruction appended *after* the frozen persona, so a change invalidates the
prompt-cache tail rather than the whole prefix. It is never enforced by
truncating a reply: cutting a sentence in half mid-number is worse than one that
ran long, and this system speaks prices aloud.

Switching is deterministic — *"be terse"* is a command, not a question, and
routing it through a model would make the cheapest request the most expensive.
It requires an imperative framing and refuses when the sentence names a subject,
so *"give me the full picture on NVDA"* stays a question about NVDA rather than
being swallowed as a settings change.

## Earcons

Non-verbal status. Faster than words and less intrusive.

| Sound | Meaning |
|---|---|
| Soft rising tone | Heard you, working on it |
| Soft double tone | Done, no speech follows |
| Low neutral tone | Acknowledged, no action needed |
| Distinct chime | **Order placed** |
| Low buzz | **Risk rejection** |
| Urgent triple | **Invalidation on an open position** |
| Descending tone | Something went down (health) |

The order-placed and risk-rejection sounds must be immediately distinguishable from
each other with no words attached. You will learn them within a week and then never
need to look at the screen for confirmation.

Pattern: [[Repo — jarvis]] `output/tune_player.py`.

**Built** — `voice/earcons.py`. Synthesised rather than shipped as files: a sine
with a raised-cosine envelope is a few lines, has no licensing question, and
follows the player's sample rate. All seven are rendered at startup, because an
earcon computed on demand is not an earcon.

The *distinguishable blind* criterion is a constraint on the waveforms, so
order-placed and risk-rejected are separated on four independent axes at once —
rising vs flat, bright vs low (more than two octaves apart), three notes vs two,
pure vs harsh. No single degradation — a bad speaker, a noisy room, hearing loss
at one end of the range — can collapse them into each other. A test asserts all
four.

## When it speaks unprompted

Restraint is the whole design. An assistant that talks too much gets muted, and a
muted assistant is worthless.

**Always speaks:**
- Invalidation on an open position
- Risk breach or approaching a hard limit
- Order filled (in `auto-within-limits` mode)
- Prop-firm warning
- Reconciliation failure or `halt`
- Execution-path component down

**Speaks if you're present** (recent voice activity):
- New high-confidence idea
- Level touched on an active idea
- Scheduled brief and recap

**Never speaks** — dashboard only:
- Routine agent completions
- Level approaches
- Health issues that don't affect execution
- Research findings without an actionable conclusion

**Built** — `voice/policy.py`. The table above is the code, keyed by
[[Event Schema]] event kinds, with three properties worth stating:

- **An unknown event kind is silent.** A new event cannot start talking merely
  by existing. Silence is safe here in a way it rarely is: the event is still on
  the [[Dashboard]] and still in the [[Episodic Log]], so the cost of holding it
  is delay, while the cost of speaking is the operator muting the system.
- **Muting cannot silence a safety event.** Otherwise *"be quiet"* becomes a
  safety control by accident.
- **Work you asked for is not an unprompted event.** A backtest you requested
  answers to you whether it took two seconds or four minutes, and is spoken
  regardless of presence. It is not a *"routine agent completion"*.

Presence is recent voice activity, including ambient speech — which is the
strongest evidence you are in the room precisely because it was not addressed to
Genesis.

## Confirmation dialogue

```
🤖 "NVDA long, one twenty shares, stop one eighteen forty. Risk three
    hundred twelve dollars, point three one percent. Confirm?"
👤 "Confirm NVDA one twenty."
🔔 [order placed]
🤖 "Filled one twenty at one twenty-one oh six."
```

Rules ([[Approval Modes]]):
- The proposal always states side, symbol, size, stop, dollar risk, and % of equity
- Confirmation must **name the ticker** — a bare "yes" never places a trade
- 60-second expiry, then re-propose with a fresh price
- Never asks twice for the same proposal

## Interruption

Barge-in always works. "Stop" cuts speech mid-word. "Genesis, halt" triggers
[[Kill Switch]] and is recognized **before** intent classification — it never waits
for an LLM.

Health notifications are queued during an active confirmation dialogue, never
interleaved. Nothing interrupts a trade confirmation except an invalidation on an
open position.

## Acceptance criteria

- Numbers are read per the table above, verified on a spoken eval set.
- Order-placed and risk-rejected earcons are distinguishable blind.
- A bare "yes" never places a trade.
- "Stop" cuts speech in under 300 ms and is never filtered as echo.
- Ten minutes of ambient conversation produces zero unprompted speech.
- Morning brief is under 90 seconds.

## Related

[[Operating Model]] · [[Terminal]] · [[10-Architecture/Voice Stack]] · [[Orchestrator]] · [[Approval Modes]] · [[Agent — Digest]] ·
[[Web Access]] ·
[[Kill Switch]] · [[Dashboard]]
