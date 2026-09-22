# Running Genesis with a microphone

```bash
# 1. the backend — loopback only, idle until you speak to it
genesis serve

# 2. the UI, in another terminal
cd ui && npm run dev
```

Open the printed URL, **hold the button** (or hold the space bar) and speak.
Release to send.

## What works today

| Say | What happens |
|---|---|
| "open trading view" | Launches TradingView Desktop with the CDP port open. Idempotent — says "already open" if it is. |
| "what is NVDA" / "tell me about AAPL" | Full company profile: price, market cap, PE, margins, analyst targets. |
| "chart NVDA" / "chart ES on 1h" | Marked-up chart into the vault. |
| "status" | What Genesis is doing. Usually nothing, honestly. |

Anything else is refused, not guessed at — it says what it *can* do instead.
Guessing an action from a half-heard sentence is the failure mode that makes a
voice assistant frightening rather than useful.

## The microphone

Audio is captured by the browser and transcribed **on this machine** by
faster-whisper (`tiny.en`). Nothing is uploaded. An external USB mic works with
no configuration — the browser uses the system default, so plug it in and
reload the page.

**Nothing listens until you press the button.** No hot mic, no ring buffer, no
wake-word model running in the background. The browser's own recording
indicator is therefore an honest signal of when audio is being captured.

Say "genesis" first if you like — it is stripped. The tap is the addressing.

### If the mic does not work

- **"Microphone permission denied"** — allow it in the browser address bar.
- **"No microphone found"** — plug one in, then reload.
- **The dot does not grow while you speak** — the level meter is reading
  silence, so the browser has the wrong input device. Check the OS default.
- **"I could not reach Genesis"** — `genesis serve` is not running.

## Idle costs nothing

The surface runs at 1 Hz when nothing is in flight and 10 fps while a task is
running. There is no autonomous loop and no simulated fleet: the server emits
events when you ask it for something, and is silent otherwise.

If you want the old demo feed for UI work without a backend:

```bash
VITE_GENESIS_MOCK=1 npm run dev
```

## Typed commands

The same path, minus the audio — useful for testing, and for when a mic
failure would otherwise be indistinguishable from a broken command:

```bash
curl -X POST http://127.0.0.1:8765/v1/command \
  -H 'content-type: application/json' -d '{"text":"open trading view"}'
```
