// Spec: Genesis Markdown/10-Architecture/Voice Stack.md · 60-UI/Genesis Core.md
//
// Play what Genesis said.
//
// The command routes answer with `spoken` — a string. Until now the UI printed
// it and stopped, while `voice.state_changed → speaking` still fired and the
// Genesis Core rendered its speaking state. The surface claimed Genesis was
// talking and nothing came out.
//
// This closes it: `POST /v1/voice/say` returns WAV, an `<audio>` element plays
// it, and the element is handed to `followMediaElement` so the Core pulses to
// the **real** amplitude rather than to a timer.
//
// Two rules it follows:
//
// **One voice at a time.** A new utterance stops the previous one. Two replies
// overlapping is worse than a truncated reply, and it is what happens by
// default if each call makes its own element.
//
// **Speech is allowed to fail without the reply failing.** The text is already
// on screen. If synthesis 503s because no key is configured, the caller gets a
// reason it can show beside the text — silence with no explanation leaves you
// wondering whether it heard you at all.

import { HTTP } from '@/api/client'
import { followMediaElement } from './envelope'

export interface SpeechAttempt {
  ok: boolean
  /** Why it did not speak, phrased for a person. `null` when it did. */
  reason: string | null
}

/**
 * The single audio element, reused.
 *
 * Reused rather than created per utterance because `createMediaElementSource`
 * may only be called once per element for the life of the page — a second call
 * throws, and the failure is silent enough to look like the Core simply
 * stopped responding. One element means one source node, created once.
 */
let element: HTMLAudioElement | null = null
let stopEnvelope: (() => void) | null = null
let currentUrl: string | null = null

function audio(): HTMLAudioElement {
  if (!element) {
    element = new Audio()
    element.preload = 'auto'
  }
  return element
}

/** Stop whatever is playing and release its blob. */
export function stopSpeaking(): void {
  stopEnvelope?.()
  stopEnvelope = null
  if (element) {
    element.pause()
    element.currentTime = 0
  }
  if (currentUrl) {
    // Blob URLs are held by the document until revoked. Leaking one per reply
    // is a slow memory leak in a surface meant to run all day.
    URL.revokeObjectURL(currentUrl)
    currentUrl = null
  }
}

/**
 * Speak `text`. Resolves when playback *starts*, not when it finishes.
 *
 * Resolving on start is deliberate: the caller wants to know whether it will be
 * heard, and awaiting the end would hold the UI for the length of the sentence.
 */
export async function speak(text: string): Promise<SpeechAttempt> {
  const trimmed = text.trim()
  if (!trimmed) return { ok: false, reason: null }

  stopSpeaking()

  let response: Response
  try {
    response = await fetch(`${HTTP}/v1/voice/say`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: trimmed }),
    })
  } catch {
    return { ok: false, reason: 'could not reach the daemon to synthesise speech' }
  }

  if (!response.ok) {
    // The daemon's own explanation, which is the useful one — it knows whether
    // a key is missing or a vendor timed out.
    try {
      const body = await response.json()
      return { ok: false, reason: String(body.error ?? `synthesis failed (${response.status})`) }
    } catch {
      return { ok: false, reason: `synthesis failed (${response.status})` }
    }
  }

  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  currentUrl = url

  const player = audio()
  player.src = url
  // Release the blob when the sentence ends, rather than waiting for the next
  // utterance to displace it.
  player.onended = () => {
    stopEnvelope?.()
    stopEnvelope = null
    if (currentUrl === url) {
      URL.revokeObjectURL(url)
      currentUrl = null
    }
  }

  try {
    await player.play()
  } catch {
    // Autoplay policy. In practice a reply follows a button press or a hotkey,
    // so a gesture exists and this does not fire — but a reply arriving from a
    // background task with no interaction will, and it should say so.
    URL.revokeObjectURL(url)
    currentUrl = null
    return {
      ok: false,
      reason: 'the browser blocked playback — interact with the page once and try again',
    }
  }

  // Only after play() resolves: an AudioContext created before a gesture is
  // suspended, and an analyser on a suspended context reports silence, which
  // would leave the Core flat through the whole sentence.
  stopEnvelope = followMediaElement(player)
  return { ok: true, reason: null }
}
