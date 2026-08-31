---
title: Voice UX
tags: [ui, voice]
status: building
implemented_by: [src/genesis/voice/speech.py]
---

# 🗣️ Voice UX

How Genesis sounds, and when it speaks. Technical pipeline: [[10-Architecture/Voice Stack]].

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

Tickers are spelled unless they're conventionally pronounced. Prices are read the way
traders say them, not the way a screen reader would.

## Verbosity levels

Configurable, and switchable mid-conversation ("give me the full version").

| Level | Example |
|---|---|
| `terse` | "Four ideas. Top is NVDA long." |
| `brief` *(default)* | "Four ideas ranked. Top is NVDA long from one twenty-one, invalidation one eighteen forty, confidence point seven two. Chart's on the dashboard." |
| `full` | Adds the thesis, the catalyst, the conflicts, and the runners-up. |

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

[[10-Architecture/Voice Stack]] · [[Orchestrator]] · [[Approval Modes]] · [[Agent — Digest]] ·
[[Kill Switch]] · [[Dashboard]]
