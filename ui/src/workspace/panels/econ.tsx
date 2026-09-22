// Spec: Genesis Markdown/60-UI/Economic Calendar.md · 10-Architecture/Market Data Catalog.md §7
//
// `EC` — the red folder. Which day, what time, and how long until it lands.
//
// It is a clock with names on it, and the design follows from that. Rows are
// grouped by day and read *forwards* — the only panel on the surface that does
// — because nothing here has happened yet. The next timed print carries a live
// countdown, and everything else carries a time you can read at a glance.
//
// **Forecast and previous are on the row.** A calendar that says only "CPI,
// 08:30" tells you to be at your desk; one that says "0.2% expected, 0.3% last"
// tells you what would be a surprise, which is the thing that moves price.
//
// **Tier 3, and the footer says so.** Somebody else's schedule, with their own
// impact rating. It informs a person and nothing else: no risk check, no sizing
// and no agent reads this table (`Safety Invariants`).
//
// It never opens itself. A print approaching is not a request (Operating Model
// §3) — the countdown in the status row is the ambient half, and clicking it
// opens this.

import { useMemo, useState } from 'react'
import { api, TransportError, type EconEvent } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { Chip, Section } from '@/components/Primitives'
import { stagger } from '@/lib/motion'

/** The desk's own clock. Every calendar convention here is New York's. */
const ET = 'America/New_York'

/** `2026-09-16T18:00:00+00:00` → `14:00`, in the named zone. */
function clockIn(iso: string, tz?: string): string {
  try {
    return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: tz })
  } catch {
    return iso
  }
}

/** `Wed 16 Sep`, in New York — the day a print belongs to is the desk's day. */
function dayLabel(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('en-GB', {
      weekday: 'short', day: '2-digit', month: 'short', timeZone: ET,
    })
  } catch {
    return iso.slice(0, 10)
  }
}

/**
 * How long until it prints. Coarse on purpose above an hour — "in 3d 4h" is as
 * much as anyone acts on, and a ticking seconds field would be a second clock
 * on the surface disagreeing with the first by a frame.
 */
export function until(iso: string, now: number): string {
  const mins = Math.round((new Date(iso).getTime() - now) / 60000)
  if (mins < 0) return `${-mins < 60 ? `${-mins}m` : `${Math.round(-mins / 60)}h`} ago`
  if (mins < 1) return 'now'
  if (mins < 60) return `in ${mins}m`
  if (mins < 24 * 60) return `in ${Math.floor(mins / 60)}h ${mins % 60}m`
  return `in ${Math.floor(mins / 1440)}d ${Math.floor((mins % 1440) / 60)}h`
}

/** Inside an hour it is a warning, inside a day it is worth noticing. */
export function toneFor(iso: string, now: number): 'bad' | 'warn' | 'neutral' {
  const mins = (new Date(iso).getTime() - now) / 60000
  if (mins < 60) return 'bad'
  if (mins < 24 * 60) return 'warn'
  return 'neutral'
}

function byDay(events: EconEvent[]): [string, EconEvent[]][] {
  const groups = new Map<string, EconEvent[]>()
  for (const e of events) {
    const key = dayLabel(e.at)
    groups.set(key, [...(groups.get(key) ?? []), e])
  }
  return [...groups.entries()]
}

export function EconCalendarPanel() {
  // Two filters, both defaulting to the desk: US, red folder only. Widening is
  // a click, and the same widening the API takes as query params.
  const [usOnly, setUsOnly] = useState(true)
  const [redOnly, setRedOnly] = useState(true)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const { state, reload } = useRead(
    () => api.econ({
      impacts: redOnly ? 'High' : 'High,Medium',
      countries: usOnly ? 'USD' : '',
    }),
    [usOnly, redOnly],
  )

  // One value for the whole render, so every row on screen counts down from the
  // same instant. Re-read on the minute: the data is a schedule, not a feed.
  const now = Date.now()
  const events = useMemo(
    () => (state.status === 'ready' ? state.data.events : []),
    [state],
  )

  async function refresh() {
    setBusy(true)
    setErr(null)
    try {
      await api.econRefresh()
      reload()
    } catch (e) {
      setErr(e instanceof TransportError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (state.status === 'loading') return <Loading rows={4} label="calendar" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  const fetched = state.data.fetched_at

  return (
    <div className="flex flex-col h-full min-h-0" data-focus-scope="true">
      <div className="flex items-center gap-1 hairline-b" style={{ padding: '4px 8px', flexShrink: 0 }}>
        <button className="btn-ghost" onClick={() => setRedOnly(!redOnly)}
          title="High impact only, or high and medium">
          {redOnly ? 'red folder' : 'red + orange'}
        </button>
        <button className="btn-ghost" onClick={() => setUsOnly(!usOnly)}
          title="United States only, or every country the vendor covers">
          {usOnly ? 'US' : 'all countries'}
        </button>
        <span style={{ flex: 1 }} />
        <button className="btn-ghost" onClick={refresh} disabled={busy}>
          {busy ? 'pulling…' : 'refresh'}
        </button>
      </div>

      {err && (
        <div className="label" style={{ padding: '3px 8px', color: 'var(--verdict-blocked)', textTransform: 'none', letterSpacing: 0 }}>
          {err}
        </div>
      )}

      {events.length === 0 ? (
        <Empty hint={fetched
          ? 'Nothing left this week at this impact. The vendor publishes one rolling week, so next week appears when it starts.'
          : 'The calendar has not been pulled yet. It rides the news collector’s run, or press refresh.'}>
          no prints ahead
        </Empty>
      ) : (
        <div className="scroll-y flex flex-col" style={{ flex: 1, padding: 8, gap: 10 }}>
          {byDay(events).map(([day, rows]) => (
            <Section key={day} title={day} dense>
              {rows.map((e, i) => (
                <div
                  key={e.id}
                  className="flex items-baseline gap-2"
                  style={{ ['--i' as string]: stagger(i), padding: '2px 0' }}
                  title={`${e.title} — ${clockIn(e.at, ET)} New York · ${clockIn(e.at)} local · ${e.impact} impact`}
                >
                  <span className="num" style={{ width: 44, flexShrink: 0, color: 'var(--ink)' }}>
                    {e.all_day ? 'all day' : clockIn(e.at, ET)}
                  </span>
                  <span style={{ fontSize: 'var(--fs-sm)', flex: 1, minWidth: 0 }}>
                    {!usOnly && (
                      <span className="num" style={{ color: 'var(--ink-faint)', marginRight: 6 }}>{e.country}</span>
                    )}
                    {e.title}
                  </span>
                  {(e.forecast || e.previous) && (
                    <span className="num" style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-faint)', flexShrink: 0 }}>
                      {e.forecast || '—'} <span style={{ color: 'var(--ink-ghost)' }}>vs {e.previous || '—'}</span>
                    </span>
                  )}
                  {!e.all_day && (
                    <Chip tone={toneFor(e.at, now)}>{until(e.at, now)}</Chip>
                  )}
                </div>
              ))}
            </Section>
          ))}
        </div>
      )}

      <div
        className="label hairline-t"
        style={{ padding: '3px 8px', flexShrink: 0, color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}
      >
        times New York · tier 3, ForexFactory — their schedule and their impact rating
        {fetched ? ` · pulled ${clockIn(fetched)} local` : ' · never pulled'}
      </div>
    </div>
  )
}
