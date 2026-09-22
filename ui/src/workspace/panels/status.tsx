// Spec: Genesis Markdown/10-Architecture/Biological Design.md §Proprioception ·
//       70-Schemas/Event Schema.md §System health
//
// HLT — the status module. One place to answer "is Genesis healthy, and on what".
//
// The chrome's status row is a summary: six glyphs and a tier. This is the
// readout behind it, and the split is deliberate — the row must fit in 26px of
// permanent chrome, and everything that did not fit was previously nowhere.
//
// Four sections, in the order you would ask them:
//
//   1. **Daemon** — is there a connection at all, is it live or mock data, when
//      did the last event arrive. Nothing else works if this is down.
//   2. **Organs** — the six health states, with `unknown` rendered as its own
//      thing. A health panel that shows green before it has heard from anything
//      is a proprioceptive lie (Biological Design §3), so the glyph for
//      "nothing has reported" is `?`, not a grey tick.
//   3. **Models** — which model runs each tier, whether its key is present, and
//      what the day has cost. A tier configured against a missing key is a
//      capability that will fail on first use, and this is where you see that
//      before an agent does.
//   4. **Data sources** — which feed each held series came from, and at what
//      trust tier. Aggregated from what is actually stored, not from config:
//      a feed named in config that has delivered nothing is not a data source.
//      The news collector gets its own row, from its run log: when it last
//      ran, whether that worked, and how much it holds.
//
// It reads. It does not act — no reconnect button, no re-key. Every write path
// here already lives in Settings, and a second door to the same write is a
// second place for it to drift (Operating Model §1 wants one door, not two).
// `re-probe` is the exception and it is a read.

import { useEffect, useMemo, useState } from 'react'
import { api, type BrokerAccount, type BrokerAccountBody } from '@/api/client'
import { useRead } from '@/api/useRead'
import { HEALTH_COLOR, HEALTH_GLYPH, ORGANS } from '@/components/SystemHealth'
import { Absent, Empty, Loading } from '@/components/States'
import { Chip, Num, PanelBody, Section } from '@/components/Primitives'
import { ago } from '@/lib/format'
import { useGenesis } from '@/store/useGenesis'

export function StatusPanel() {
  const health = useGenesis((s) => s.health)
  const tier = useGenesis((s) => s.tier)
  const connection = useGenesis((s) => s.connection)
  const models = useRead(() => api.models(), [])
  const symbols = useRead(() => api.symbols(), [])

  const live = connection.status === 'open'
  const now = Date.now()

  // Feeds, from what is held rather than from what is configured. One row per
  // (source, tier) pair: the same vendor at two trust tiers is two answers to
  // "can I believe this", and collapsing them would hide the worse one.
  const feeds = useMemo(() => {
    if (symbols.state.status !== 'ready') return []
    const by = new Map<string, { source: string; tier: number; series: number; bars: number }>()
    for (const row of symbols.state.data.symbols) {
      for (const cov of row.coverage) {
        const key = `${cov.source}:${cov.tier}`
        const seen = by.get(key) ?? { source: cov.source, tier: cov.tier, series: 0, bars: 0 }
        seen.series += 1
        seen.bars += row.bars
        by.set(key, seen)
      }
    }
    return [...by.values()].sort((a, b) => a.tier - b.tier || b.bars - a.bars)
  }, [symbols.state])

  return (
    <PanelBody>
      <Section title="daemon" dense>
        <Row
          color={live ? (connection.gap ? 'var(--state-degraded)' : 'var(--verdict-pass)') : 'var(--state-down)'}
          glyph={live ? (connection.gap ? '╌' : '━') : '✕'}
          label={connection.status}
          note={live ? 'event socket open' : 'is `genesis serve` running?'}
        >
          {connection.kind === 'mock' && <Chip tone="warn">MOCK DATA</Chip>}
          <Chip tone={tier === 'degraded' ? 'warn' : 'neutral'}>tier {tier}</Chip>
        </Row>
        <Row
          color={connection.lastEventAt ? 'var(--ink-faint)' : 'var(--ink-ghost)'}
          glyph="·"
          label="last event"
          note={connection.lastEventAt ? `${ago(now - connection.lastEventAt)} ago` : 'none yet'}
        >
          {connection.gap && <Chip tone="warn">gap — replay incomplete</Chip>}
        </Row>
      </Section>

      <Section title="organs" dense>
        {ORGANS.map((o) => (
          <Row
            key={o.key}
            color={HEALTH_COLOR[health[o.key]]}
            glyph={HEALTH_GLYPH[health[o.key]]}
            label={o.label}
            note={o.organ}
          >
            <Chip tone={health[o.key] === 'ok' ? 'good' : health[o.key] === 'unknown' ? 'neutral' : 'bad'}>
              {health[o.key]}
            </Chip>
          </Row>
        ))}
      </Section>

      <Section title="models" dense>
        {models.state.status === 'loading' ? <Loading rows={4} label="model tiers" />
          : models.state.status === 'absent'
            ? <Absent reason={models.state.reason} onRetry={models.reload} />
            : !models.state.data ? <Empty>no model tiers reported</Empty>
              : (
                <>
                  {models.state.data.tiers.map((t) => {
                    // Local models need no key. A remote tier without one is
                    // configured to fail, and that is what this says.
                    const missing = !t.local && !t.key_present
                    return (
                      <Row
                        key={t.tier}
                        color={missing ? 'var(--state-down)' : t.local ? 'var(--ink-faint)' : 'var(--verdict-pass)'}
                        glyph={missing ? '✕' : '━'}
                        label={t.tier}
                        note={`${t.backend}/${t.model}`}
                      >
                        {t.local && <Chip tone="neutral">local</Chip>}
                        {t.dev_only && <Chip tone="warn">dev only</Chip>}
                        {missing && <Chip tone="bad">no key{t.env_var ? ` — ${t.env_var}` : ''}</Chip>}
                      </Row>
                    )
                  })}
                  <div className="flex items-baseline gap-2" style={{ marginTop: 4 }}>
                    <span className="label">today</span>
                    <span className="num" style={{ fontSize: 'var(--fs-sm)' }}>
                      <Num value={models.state.data.tokens_today} digits={0} />
                    </span>
                    <span className="label">
                      of {models.state.data.daily_token_budget.toLocaleString()} tokens
                    </span>
                    <span style={{ flex: 1 }} />
                    {models.state.data.live_broker && <Chip tone="bad">live broker</Chip>}
                  </div>
                </>
              )}
      </Section>

      <Section title="data sources" dense>
        <IbkrRow />
        <NewsRow now={now} />
        {symbols.state.status === 'loading' ? <Loading rows={2} />
          : symbols.state.status === 'absent'
            ? <Absent reason={symbols.state.reason} onRetry={symbols.reload} />
            : feeds.length === 0 ? <Empty>nothing ingested — no feed has delivered a bar</Empty>
              : feeds.map((f) => (
                <Row
                  key={`${f.source}:${f.tier}`}
                  color={f.tier <= 1 ? 'var(--verdict-pass)' : 'var(--state-degraded)'}
                  glyph="━"
                  label={f.source}
                  note={`${f.series} series · ${f.bars.toLocaleString()} bars`}
                >
                  <Chip tone={f.tier <= 1 ? 'good' : 'warn'}>tier {f.tier}</Chip>
                </Row>
              ))}
      </Section>
    </PanelBody>
  )
}

/**
 * The IBKR session: is it connected, and to a paper or a live account.
 *
 * Paper/live is the broker's answer (the account id), not the configured mode,
 * so a live login saved by mistake shows as live here. Kept current by the same
 * `broker.connection` / `broker.account` pushes `ACC` uses — no polling.
 */
function IbkrRow() {
  const { state } = useRead(() => api.brokerAccount(), [])
  const [pushed, setPushed] = useState<Partial<BrokerAccountBody>>({})

  useEffect(() => useGenesis.subscribe((s, prev) => {
    const e = s.events[0] as { event: string; data: unknown } | undefined
    if (!e || e === prev.events[0]) return
    if (e.event === 'broker.account') setPushed((p) => ({ ...p, account: e.data as BrokerAccount }))
    if (e.event === 'broker.connection') {
      const d = e.data as { state: BrokerAccountBody['state']; detail: string }
      setPushed((p) => ({ ...p, state: d.state, detail: d.detail }))
    }
  }), [])

  if (state.status === 'loading') return null
  if (state.status !== 'ready') {
    return (
      <Row color="var(--ink-ghost)" glyph="·" label="ibkr" note="not enabled — CON to connect">
        <Chip tone="neutral">off</Chip>
      </Row>
    )
  }

  const body = { ...state.data, ...pushed }
  const live = body.state === 'live'
  const account = body.account
  const note = live && account
    ? `${account.accounts.join(', ')} · ${body.market_data_type} data`
    : body.detail || body.gateway

  return (
    <Row
      color={live ? 'var(--verdict-pass)' : body.state === 'down' ? 'var(--state-down)' : 'var(--state-degraded)'}
      glyph={live ? '━' : body.state === 'down' ? '✕' : '╌'}
      label="ibkr"
      note={note}
    >
      {live && account && (
        <Chip tone={account.mode === 'paper' ? 'spinal' : 'bad'}>{account.mode}</Chip>
      )}
      <Chip tone={live ? 'good' : body.state === 'down' ? 'bad' : 'neutral'}>
        {live ? 'connected' : body.state}
      </Chip>
    </Row>
  )
}

/**
 * The news collector, from its own run log in `news.db`.
 *
 * Stale is judged against the collector's slowest cadence (hourly when the
 * market is closed): no successful run in two hours means it is not running,
 * whatever the last run said.
 */
function NewsRow({ now }: { now: number }) {
  const { state, reload } = useRead(() => api.newsStatus(), [])
  useEffect(() => useGenesis.subscribe((s, prev) => {
    const e = s.events[0] as { event: string; data: { agent?: string } } | undefined
    if (e && e !== prev.events[0] && e.event === 'task.completed' && e.data?.agent === 'news-collector') reload()
  }), [reload])

  if (state.status === 'loading') return null
  if (state.status !== 'ready') {
    return (
      <Row color="var(--state-down)" glyph="✕" label="news" note={state.reason}>
        <Chip tone="bad">unavailable</Chip>
      </Row>
    )
  }
  const s = state.data
  const run = s.last_run
  const lastOk = s.last_ok_at ? now - new Date(s.last_ok_at).getTime() : null
  const stale = lastOk === null || lastOk > 2 * 3.6e6
  const failing = run !== null && !run.ok
  const note = run
    ? `${s.source} · ${s.last_24h} stories in 24h · ${s.articles.toLocaleString()} held · ran ${ago(now - new Date(run.at).getTime())}`
      + (run.detail ? ` · ${run.detail}` : '')
    : `${s.source} · never run — start the daemon, or refresh in NW`
  return (
    <Row
      color={failing || !run ? 'var(--state-down)' : stale ? 'var(--state-degraded)' : 'var(--verdict-pass)'}
      glyph={failing || !run ? '✕' : stale ? '╌' : '━'}
      label="news"
      note={note}
    >
      <Chip tone="warn">tier {s.tier}</Chip>
      <Chip tone={failing || !run ? 'bad' : stale ? 'warn' : 'good'}>
        {!run ? 'idle' : failing ? 'failing' : stale ? 'stale' : 'collecting'}
      </Chip>
    </Row>
  )
}

/** One health line: glyph, name, what it is, and whatever qualifies it. */
function Row({
  color, glyph, label, note, children,
}: {
  color: string
  glyph: string
  label: string
  note: string
  children?: React.ReactNode
}) {
  return (
    <div className="flex items-baseline gap-2" style={{ fontSize: 'var(--fs-tiny)', minHeight: 18 }}>
      <span className="num" style={{ color, width: 10, flexShrink: 0 }}>{glyph}</span>
      <span style={{ color: 'var(--ink)', minWidth: 74, flexShrink: 0 }}>{label}</span>
      <span
        className="label"
        style={{
          textTransform: 'none', letterSpacing: 0, color: 'var(--ink-faint)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}
      >
        {note}
      </span>
      <span style={{ flex: 1 }} />
      {children}
    </div>
  )
}
