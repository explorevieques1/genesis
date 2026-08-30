---
title: Voice Stack
tags: [architecture, voice]
status: spec
implemented_by: []
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
             ElevenLabs Scribe (streaming STT)
                    │  partials
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
| STT | ElevenLabs Scribe, streaming | partial transcripts start the planner early |
| Intent | nano-tier classifier | see [[Orchestrator]] |
| TTS | ElevenLabs streaming, custom voice id | interruptible mid-sentence |
| Earcons | short local tones | see [[Voice UX]] |
| Echo | compare heard text to last spoken text | prevents self-triggering |

Pattern reference: [[Repo — jarvis]] `src/jarvis/listening/` — `wake_detection.py`,
`echo_detection.py`, `transcript_buffer.py`, `state_manager.py`, `intent_judge.py`;
and `src/jarvis/output/tts.py`, `tune_player.py`.

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

| Stage | Budget |
|---|---|
| wake detect | 150 ms |
| STT (streaming, to usable partial) | 300 ms |
| intent (nano) | 100 ms |
| plan / trivial answer | 400 ms |
| TTS first chunk | 400 ms |

Anything needing agents exceeds this — so **acknowledge immediately** with an earcon
plus a one-liner ("Working on it — screening semis") and speak the result when it lands.

## Privacy note

[[Repo — jarvis]]'s `CLAUDE.md` forbids ElevenLabs on offline-first principle.
Genesis deliberately diverges — see [[Open Questions]] §7. The line we hold: **voice
and market data may be cloud; strategy, memory, journal, and risk are local.** Audio
leaves only after the local wake gate fires.

## Acceptance criteria

- Wake word detected in any sentence position, ≥95% on a 100-utterance eval set.
- Zero actions triggered by 10 minutes of ambient conversation.
- Barge-in stops speech in <300 ms; "stop" is never swallowed as echo.
- Pulling the network cable mid-session degrades voice but does not crash the daemon.

## Related

[[Orchestrator]] · [[Voice UX]] · [[LLM Model Tiers]] · [[Error Handling And Degradation]]
