---
title: Voice Stack
tags: [architecture, voice]
status: built
implemented_by: [src/genesis/voice/capture.py, src/genesis/voice/vad.py, src/genesis/voice/wake.py, src/genesis/voice/stt.py, src/genesis/voice/tts.py, src/genesis/voice/player.py, src/genesis/voice/speaker.py, src/genesis/voice/echo.py, src/genesis/voice/reflex.py, src/genesis/voice/earcons.py, src/genesis/voice/policy.py, src/genesis/orchestrator/build.py, tests/orchestrator/test_build.py, evals/corpora/intent.py, evals/test_intent_classification.py, src/genesis/server/voice_routes.py, ui/src/components/TapToSpeak.tsx, ui/src/lib/speak.ts]
---

# Voice Stack

ElevenLabs in and out, with a local wake gate so audio only leaves the machine
once you've addressed it.

## Pipeline

```
 mic ──► ring buffer ──► VAD ──► wake detection ──► [gate]
                                                      │
                    ┌─────────────────────────────────┘
                    ▼
             ElevenLabs Scribe (batch STT — see below)
                    │  transcript
                    ▼
             intent classification  (nano tier)
                    │  directed?
                    ▼
             [[Orchestrator]] planner ──► agents
                    │  reply text (streamed)
                    ▼
             ElevenLabs TTS (streaming)  ──► speakers
                    │
             echo detection ◄── loopback of what we said
```

## Components

| Stage | Choice | Notes |
|---|---|---|
| Capture | local mic, continuous ring buffer | keeps ~30 s of rolling audio so the wake word can be *anywhere* in a sentence |
| VAD | local (webrtcvad / silero) | cheap gate before anything expensive |
| Wake | on-device keyword ("Genesis") | **no audio leaves until this fires** |
| STT | ElevenLabs Scribe, **batch** | one request per utterance — see *What is not streaming* |
| Intent | nano-tier classifier | see [[Orchestrator]] |
| TTS | ElevenLabs streaming, custom voice id | interruptible mid-sentence |
| Earcons | short local tones | see [[Voice UX]] |
| Echo | compare heard text to last spoken text | prevents self-triggering |

Pattern reference: [[Repo — jarvis]] `src/jarvis/listening/` — `wake_detection.py`,
`echo_detection.py`, `transcript_buffer.py`, `state_manager.py`, `intent_judge.py`;
and `src/jarvis/output/tts.py`, `tune_player.py`.

> [!warning] What is not streaming — recorded 2026-08-31
> The diagram above once said *"partials start the planner early"*. It never
> did. `ScribeSTT` sends one request per utterance and waits, which is why the
> measured line reads *"~670 ms (Scribe, batch)"*. The note now says batch in
> both places, because a pipeline diagram describing a stage the system does not
> have is [[Biological Design|proprioceptive drift]] — the system reasons
> confidently about itself and is wrong.
>
> The budget line moved with it: 300 ms priced a *partial*, and there is no
> partial. 700 ms is what a whole-utterance round trip actually costs, and the
> measurement sits just inside it. Streaming would buy roughly 300 ms back, and
> the budget line goes back to 300 ms on the day it lands — but it
> is a change to the STT client, not to the pipeline shape: the wake gate still
> owns the audio and still releases it only after a local detector fires.

## Wake anywhere

The wake word does not have to lead the sentence. "Give me the semis setup,
Genesis" must work. Implementation: keep a rolling transcript buffer; when the wake
word is detected, hand the **whole surrounding utterance** to intent classification,
not just what followed the wake word.

## Barge-in

While TTS is playing, the mic stays live and VAD stays armed. User speech above
threshold → stop TTS immediately, flush the audio queue, listen. This is what makes
it feel like a conversation rather than a kiosk.

Guard: echo detection must run *before* barge-in, or the assistant interrupts itself.
(Known failure mode in [[Repo — jarvis]] — "stop" during speech sometimes filtered
as echo. Fix: exact-match echo filtering, but always honour `stop` keywords even if
they look like echo.)

## Follow-up window

After a reply, keep a ~4 s window where speech is treated as `directed` without the
wake word. Extend the window if the reply asked a question ("which timeframe?").

## Degradation

| Failure | Behaviour |
|---|---|
| ElevenLabs STT down | fall back to local Whisper; log degraded; keep working |
| ElevenLabs TTS down | fall back to local TTS (Piper/Kokoro); voice changes, system doesn't stop |
| Internet down | wake + local STT/TTS still work; agents needing data return typed failures; see [[Error Handling And Degradation]] |
| Mic unavailable | switch to text input on the [[Dashboard]]; announce via desktop notification |

Never hard-fail the whole system on a voice fault. Voice is a surface, not the spine.

## Latency budget

Target: wake → first spoken syllable **< 1.5 s** for a trivial request.

| Stage | Budget | Measured (2026-08-30, this machine) |
|---|---|---|
| wake detect | 150 ms | **~1200 ms** ⚠️ — see below |
| STT (batch, whole utterance) | 700 ms | ~670 ms (Scribe, batch) |
| intent (nano) | 100 ms | **0.1–3 ms** — deterministic, no model |
| plan / trivial answer | 400 ms | <1 ms (calendar, no model) |
| TTS first chunk | 400 ms | ~210 ms warm / ~740 ms cold |

### Where the measurements changed the design

**Wake detection is over budget and the budget was wrong.** The 150 ms figure
assumed a keyword spotter that emits a timestamp. Genesis uses a local Whisper
transcription instead, because the note *also* requires handing "the whole
surrounding utterance" to intent classification — a spotter cannot do that, and
would need a transcriber behind it anyway. So the ~1200 ms buys wake detection
**and** the transcript **and** the offline STT fallback in one pass, against a
budget line that priced only the first. It is still the dominant cost; a GPU,
a smaller segment window, or a dedicated spotter feeding a transcriber are the
three ways down.

**The TLS handshake is a latency stage.** A fresh HTTPS connection costs ~400 ms
against a 400 ms budget, so `ElevenLabsTTS` holds one client for the process
life and `warm()` opens it at startup. Cold: 741 ms. Warm: 206 ms.

**Intent classification does not use the nano tier.** See
[[LLM Model Tiers]] §Measured latency. It is deterministic and ~1000x faster.

Anything needing agents exceeds this — so **acknowledge immediately** with an earcon
plus a one-liner ("Working on it — screening semis") and speak the result when it lands.

**Built.** The [[Voice UX|acknowledged earcon]] fires when a plan is dispatched,
*before* the await window, and the one-liner comes from the plan itself
("Running it now — 3 steps"). The result is spoken when it lands, from the voice
loop's idle path rather than a second thread, so nothing races the speaker.

## Privacy note

[[Repo — jarvis]]'s `CLAUDE.md` forbids ElevenLabs on offline-first principle.
Genesis deliberately diverges — see [[Open Questions]] §7. The line we hold: **voice
and market data may be cloud; strategy, memory, journal, and risk are local.** Audio
leaves only after the local wake gate fires.

**This is enforced structurally, not by convention.** `WakeGate` owns the captured
audio; the only way out is `take()`, which returns `None` until a *local* detector
has fired. Nothing in the codebase hands the ring buffer to Scribe directly, so the
invariant cannot be broken by wiring the pipeline wrong later — the same reasoning
that puts orders behind `propose_order` → `place_approved` instead of a documented
rule to always call the risk engine first.

## Acceptance criteria

- Wake word detected in any sentence position, ≥95% on a 100-utterance eval set.
- Zero actions triggered by 10 minutes of ambient conversation.
- Barge-in stops speech in <300 ms; "stop" is never swallowed as echo.
- Pulling the network cable mid-session degrades voice but does not crash the daemon.

## Related

[[Orchestrator]] · [[Voice UX]] · [[LLM Model Tiers]] · [[Error Handling And Degradation]]
