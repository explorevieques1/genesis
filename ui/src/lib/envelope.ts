// Spec: Genesis Markdown/60-UI/Genesis Core.md — "pulses to the TTS envelope while speaking"
//
// One number: how loud Genesis is, right now.
//
// The Core was pulsing to `Math.sin(t * 6)` — a convincing-looking animation
// that is not connected to anything. It moves identically whether Genesis is
// mid-sentence, silent, or disconnected, which makes it decoration dressed as
// telemetry. On a surface whose entire argument is that it does not display
// numbers it has not vouched for, a fake amplitude is the same category of
// error as a fake equity curve, just prettier.
//
// So this is the real envelope, from a Web Audio `AnalyserNode`:
//
//   - **listening** — RMS of the microphone stream, so the Core responds to the
//     operator's voice while they hold the button.
//   - **speaking** — RMS of the TTS playback, so it responds to Genesis' own.
//
// A module-level store rather than React state: this updates at frame rate and
// is consumed by a canvas that React does not draw. Putting it in state would
// re-render the tree sixty times a second to animate something React is not
// responsible for.
//
// **When there is no audio source, the value is 0 and the Core does not pulse.**
// That is the honest resting state — a silent Genesis looks silent.

type Listener = (level: number) => void

let level = 0
let source: 'mic' | 'tts' | null = null
const listeners = new Set<Listener>()

/** The current envelope, 0…1. Read directly by animation loops. */
export function amplitude(): number {
  return level
}

/** Which source is driving it, or `null` when nothing is. */
export function envelopeSource(): 'mic' | 'tts' | null {
  return source
}

export function subscribeEnvelope(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function publish(next: number, from: 'mic' | 'tts' | null) {
  level = next
  source = from
  for (const listener of listeners) listener(next)
}

/**
 * Follow an `AnalyserNode` until `stop()` is called.
 *
 * Returns a teardown. The caller owns the AudioContext — this only reads.
 *
 * The smoothing is asymmetric on purpose: fast attack, slow release. Speech is
 * spiky, and a symmetric filter either lags the onset of a word (too slow) or
 * makes the Core flicker between syllables (too fast). Rising quickly and
 * falling gently is what reads as *a voice* rather than as a level meter.
 */
export function followAnalyser(
  analyser: AnalyserNode,
  from: 'mic' | 'tts',
): () => void {
  const buffer = new Uint8Array(analyser.frequencyBinCount)
  let frame = 0
  let smoothed = 0
  let stopped = false

  const tick = () => {
    if (stopped) return
    analyser.getByteTimeDomainData(buffer)

    // RMS around the 128 midpoint of unsigned 8-bit PCM.
    let sum = 0
    for (let i = 0; i < buffer.length; i++) {
      const deviation = (buffer[i] - 128) / 128
      sum += deviation * deviation
    }
    const rms = Math.sqrt(sum / buffer.length)

    // Speech RMS rarely exceeds ~0.35; scaled so normal talking reaches the
    // top of the range rather than sitting in the bottom fifth of it.
    const scaled = Math.min(1, rms * 2.8)
    smoothed = scaled > smoothed
      ? smoothed + (scaled - smoothed) * 0.55   // attack
      : smoothed + (scaled - smoothed) * 0.12   // release

    publish(smoothed, from)
    frame = requestAnimationFrame(tick)
  }
  frame = requestAnimationFrame(tick)

  return () => {
    stopped = true
    cancelAnimationFrame(frame)
    // Back to silence explicitly. Leaving the last value would freeze the Core
    // mid-pulse, which reads as "still speaking".
    publish(0, null)
  }
}

/**
 * Attach the envelope to an `<audio>` element — the TTS playback path.
 *
 * Each element may only be connected to one `MediaElementSourceNode` for the
 * life of the page, so the node is cached on the element. Connecting twice
 * throws, and the second failure is silent enough to look like the Core simply
 * stopped working.
 */
const attached = new WeakMap<HTMLMediaElement, { ctx: AudioContext; analyser: AnalyserNode }>()

export function followMediaElement(element: HTMLMediaElement): () => void {
  try {
    let wiring = attached.get(element)
    if (!wiring) {
      const ctx = new AudioContext()
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 512
      const node = ctx.createMediaElementSource(element)
      node.connect(analyser)
      // Still routed to the speakers: an analyser is a tap, not a sink, and
      // forgetting this connection is how the voice goes silent.
      analyser.connect(ctx.destination)
      wiring = { ctx, analyser }
      attached.set(element, wiring)
    }
    void wiring.ctx.resume()
    return followAnalyser(wiring.analyser, 'tts')
  } catch {
    // Autoplay policy, a missing AudioContext, a cross-origin source. The Core
    // falls back to its resting state rather than the page breaking.
    return () => publish(0, null)
  }
}
