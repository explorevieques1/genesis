// Spec: Genesis Markdown/60-UI/Economic Calendar.md §Countdown
//
// The ambient half of the red folder: the next high-impact print, and how long
// until it lands, in the status row.
//
// It is the one thing in the chrome that is not system health, and it earns the
// place by the same argument the kill switch does — a number that matters
// behind a click is a number nobody reads. A print you have forgotten about is
// the one that takes a position with it, and "check the calendar" is not a
// habit anybody keeps under load.
//
// **It is not a notification.** Nothing pops, nothing speaks, nothing opens
// (Operating Model §3). It is a label that is simply always true, and clicking
// it opens `EC` — the same module ⌘K → EC opens, by the same call, which is the
// parity rule.
//
// **It shows nothing rather than something wrong.** No calendar pulled, no
// prints ahead, or a daemon that is not answering, and the segment is absent.
// A stale countdown is worse than no countdown.

import { useEffect, useState } from 'react'
import { api, type EconEvent } from '@/api/client'
import { openPanel } from '@/workspace/dock'
import { toneFor, until } from '@/workspace/panels/econ'

/** The schedule changes daily at most; this re-reads every ten minutes. */
const RELOAD_MS = 10 * 60 * 1000
/** The label is minute-resolution, so it ticks on the half-minute. */
const TICK_MS = 30 * 1000

const TONE_COLOR: Record<string, string> = {
  bad: 'var(--state-down)',
  warn: 'var(--state-degraded)',
  neutral: 'var(--ink-faint)',
}

export function EconCountdown() {
  const [event, setEvent] = useState<EconEvent | null>(null)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    let live = true
    const read = async () => {
      try {
        const body = await api.econ({ impacts: 'High', countries: 'USD', limit: 20 })
        // `available` is the envelope's discriminant and must be checked before
        // the payload is touched: on an absent answer there is no `events`, and
        // `.find` on undefined throws into the catch below — where it reads as
        // a transport failure rather than "no calendar".
        if (!body.available) return
        // Timed prints only: an all-day row has no clock to count down to.
        const next = body.events.find((e) => !e.all_day) ?? null
        if (live) setEvent(next)
      } catch {
        // The chrome never shows a transport error. Absent is the honest state.
        if (live) setEvent(null)
      }
    }
    read()
    const reload = setInterval(read, RELOAD_MS)
    const tick = setInterval(() => setNow(Date.now()), TICK_MS)
    return () => { live = false; clearInterval(reload); clearInterval(tick) }
  }, [])

  if (!event) return null

  return (
    <>
      {/* The separator belongs to the segment: a divider with nothing after it
          is chrome that lies about having something to show. */}
      <span className="hairline-l" style={{ margin: '4px 0' }} />
      <button
        className="flex items-center gap-[5px] px-[9px]"
        title={`${event.title} — ${new Date(event.at).toLocaleString('en-GB', {
          weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
          timeZone: 'America/New_York',
        })} New York · high impact. Click for the calendar (EC).`}
        onClick={() => openPanel('econ-calendar', { id: 'econ-calendar', title: 'Economic calendar' })}
      >
        <span className="label" style={{ color: 'var(--state-down)' }}>▮</span>
        <span
          className="label"
          style={{ color: 'var(--ink-faint)', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        >
          {event.title}
        </span>
        <span className="num" style={{ fontSize: 'var(--fs-tiny)', color: TONE_COLOR[toneFor(event.at, now)] }}>
          {until(event.at, now)}
        </span>
      </button>
    </>
  )
}
