// Spec: Genesis Markdown/60-UI/Voice UX.md · Genesis Markdown/10-Architecture/Voice Stack.md
//
// Hold to talk. Release to send.
//
// Push-to-talk rather than always-listening, and that is the whole design:
//
//   - **The tap is the addressing.** Voice UX makes the wake word a way to get
//     attention, not a ritual — and a button press is a clearer, faster and
//     more reliable way to say "I am talking to you" than a hotword detector
//     that has to run continuously and still guesses. Saying "genesis" first
//     still works; it is stripped server-side.
//   - **Nothing listens until you ask it to.** No hot mic, no ring buffer, no
//     background model. The stream is opened on press and torn down on
//     release, so the browser's own recording indicator is an honest signal of
//     when audio is being captured.
//   - **It costs nothing at rest**, which matters on the machine this runs on.
//
// The audio goes to the local server and is transcribed on this machine by
// faster-whisper. It does not leave the host.

import { useCallback, useEffect, useRef, useState } from 'react'
import { followAnalyser } from '@/lib/envelope'

type Phase = 'idle' | 'arming' | 'listening' | 'thinking' | 'error'

export interface VoiceReply {
  ok: boolean
  heard: string
  command: string
  spoken: string
  detail?: string
  ms?: number
}

/** Longest single utterance. A stuck button must not record forever. */
const MAX_MS = 15_000

export function TapToSpeak({
  http,
  onReply,
  disabled,
}: {
  http: string
  onReply: (r: VoiceReply) => void
  disabled?: boolean
}) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [level, setLevel] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const recorder = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const stream = useRef<MediaStream | null>(null)
  const audioCtx = useRef<AudioContext | null>(null)
  const stopEnvelope = useRef<(() => void) | null>(null)
  const raf = useRef(0)
  const cutoff = useRef<number | null>(null)

  // Tearing the stream down is not optional housekeeping: a MediaStream left
  // open keeps the OS microphone indicator lit, which would make the "nothing
  // is listening" promise visibly false.
  const teardown = useCallback(() => {
    cancelAnimationFrame(raf.current)
    if (cutoff.current !== null) { clearTimeout(cutoff.current); cutoff.current = null }
    stopEnvelope.current?.()
    stopEnvelope.current = null
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
    void audioCtx.current?.close().catch(() => {})
    audioCtx.current = null
    recorder.current = null
    setLevel(0)
  }, [])

  useEffect(() => teardown, [teardown])

  const send = useCallback(
    async (blob: Blob) => {
      setPhase('thinking')
      const body = new FormData()
      body.append('audio', blob, 'utterance.webm')
      try {
        const res = await fetch(`${http}/v1/voice/utterance`, { method: 'POST', body })
        if (!res.ok) throw new Error(`server ${res.status}`)
        onReply((await res.json()) as VoiceReply)
        setPhase('idle')
      } catch (e) {
        // A failed round trip is reported, never swallowed. Silence after a
        // button press is indistinguishable from a broken microphone.
        setError(e instanceof Error ? e.message : 'send failed')
        setPhase('error')
        onReply({
          ok: false, heard: '', command: 'transport',
          spoken: 'I could not reach Genesis. Is `genesis serve` running?',
        })
      }
    },
    [http, onReply],
  )

  const start = useCallback(async () => {
    if (phase !== 'idle' && phase !== 'error') return
    setError(null)
    setPhase('arming')
    try {
      const media = await navigator.mediaDevices.getUserMedia({
        audio: {
          // An external mic is usually the reason someone plugged one in, so
          // let the browser pick the system default rather than pinning a
          // device id that goes stale the moment it is unplugged.
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
      stream.current = media

      // A live level meter, because the single most common voice failure is a
      // muted or wrong input and the only honest fix is showing the user that
      // nothing is arriving.
      const ctx = new AudioContext()
      audioCtx.current = ctx
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 512
      ctx.createMediaStreamSource(media).connect(analyser)
      // Publish the same analyser to the shared envelope so the Genesis Core
      // pulses to the operator's actual voice while the button is held,
      // rather than to a timer.
      stopEnvelope.current = followAnalyser(analyser, 'mic')
      const buf = new Uint8Array(analyser.frequencyBinCount)
      const meter = () => {
        analyser.getByteTimeDomainData(buf)
        let peak = 0
        for (let i = 0; i < buf.length; i++) peak = Math.max(peak, Math.abs(buf[i] - 128))
        setLevel(Math.min(1, peak / 48))
        raf.current = requestAnimationFrame(meter)
      }
      meter()

      chunks.current = []
      const rec = new MediaRecorder(media)
      rec.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data) }
      rec.onstop = () => {
        const blob = new Blob(chunks.current, { type: rec.mimeType || 'audio/webm' })
        teardown()
        void send(blob)
      }
      rec.start()
      recorder.current = rec
      cutoff.current = window.setTimeout(() => rec.state === 'recording' && rec.stop(), MAX_MS)
      setPhase('listening')
    } catch (e) {
      teardown()
      // Permission denial and "no device" are different problems with
      // different fixes, and collapsing them into "mic error" helps nobody.
      const name = e instanceof DOMException ? e.name : ''
      setError(
        name === 'NotAllowedError'
          ? 'Microphone permission denied — allow it in the browser address bar.'
          : name === 'NotFoundError'
            ? 'No microphone found. Plug one in, then reload.'
            : e instanceof Error ? e.message : 'microphone unavailable',
      )
      setPhase('error')
    }
  }, [phase, send, teardown])

  const stop = useCallback(() => {
    const rec = recorder.current
    if (rec && rec.state === 'recording') rec.stop()
    else if (phase === 'arming') { teardown(); setPhase('idle') }
  }, [phase, teardown])

  // Space bar, held. Ignored while typing, because a push-to-talk key that
  // fires inside a text field is a key you have to disable.
  useEffect(() => {
    const typing = (t: EventTarget | null) =>
      t instanceof HTMLElement &&
      (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
    const down = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || e.repeat || typing(e.target) || disabled) return
      e.preventDefault()
      void start()
    }
    const up = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || typing(e.target)) return
      e.preventDefault()
      stop()
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [start, stop, disabled])

  const listening = phase === 'listening'
  const label =
    phase === 'listening' ? 'Listening — release to send'
      : phase === 'thinking' ? 'Thinking…'
        : phase === 'arming' ? 'Opening mic…'
          : phase === 'error' ? (error ?? 'Microphone error')
            : 'Hold to speak  ·  space'

  return (
    <div className="flex items-center gap-2" style={{ minWidth: 0 }}>
      <button
        type="button"
        disabled={disabled || phase === 'thinking'}
        onPointerDown={(e) => { e.preventDefault(); void start() }}
        onPointerUp={stop}
        onPointerLeave={() => listening && stop()}
        title="Hold to speak, or hold the space bar"
        style={{
          display: 'flex', alignItems: 'center', gap: 7,
          padding: '3px 11px', borderRadius: 3, cursor: disabled ? 'default' : 'pointer',
          border: '1px solid',
          borderColor: listening ? 'var(--core-hot)'
            : phase === 'error' ? 'var(--state-down)' : 'var(--hairline)',
          background: listening ? 'color-mix(in srgb, var(--core-hot) 14%, transparent)'
            : 'var(--bg-panel)',
          color: phase === 'error' ? 'var(--state-down)' : 'var(--ink)',
          font: 'inherit', fontSize: 'var(--fs-sm)',
          opacity: disabled ? 0.45 : 1,
        }}
      >
        <span
          aria-hidden
          style={{
            width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
            background: listening ? 'var(--core-hot)'
              : phase === 'thinking' ? 'var(--core-warm, var(--ink-faint))'
                : phase === 'error' ? 'var(--state-down)' : 'var(--ink-faint)',
            // Scales with the actual input level, so a muted mic is visibly
            // muted rather than looking identical to a silent room.
            transform: listening ? `scale(${1 + level * 1.5})` : 'scale(1)',
            transition: 'transform 90ms linear',
          }}
        />
        <span style={{ whiteSpace: 'nowrap' }}>{label}</span>
      </button>
    </div>
  )
}
