// Spec: Genesis Markdown/10-Architecture/Market Data Plane.md §Live session · deploy/ib-gateway/README.md
//
// CON — connect a data provider. Four steps, in the order they can fail:
//
//   1. login     the IBKR username/password the gateway logs in with
//   2. gateway   the headless IB Gateway container that holds the session
//   3. feed      which contracts to stream into the store, delayed or realtime
//   4. test      a layered check: login saved → container → socket → logged in → bars
//
// Every button here writes a file or runs a command a person can do by hand —
// `~/.genesis/.env`, `docker compose`, `~/.genesis/config.yaml`, `genesis ibkr
// check` (parity, Operating Model §1). The password is sent once and never
// shown again; the server only says whether one is saved.
//
// Also rendered inside ACC as its "setup" tab.

import { useEffect, useState } from 'react'
import { api, TransportError, type BrokerSettingsBody, type LiveSeries } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Loading } from '@/components/States'
import { Chip, PanelBody, Section } from '@/components/Primitives'
import { useWorkspace } from '@/workspace/context'

const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1H', '4H', '1D'] as const

export type Step = { step: string; ok: boolean; detail: string }

const note = { textTransform: 'none', letterSpacing: 0, color: 'var(--ink-faint)' } as const

export function BrokerSetupPanel() {
  return <BrokerSetup />
}

export function BrokerSetup() {
  const { state, reload } = useRead(() => api.brokerSettings(), [])
  if (state.status === 'loading') return <Loading rows={6} label="data connections" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />
  return <SetupForm initial={state.data} reload={reload} />
}

function SetupForm({ initial, reload }: { initial: BrokerSettingsBody; reload: () => void }) {
  const { select } = useWorkspace()
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  const [userid, setUserid] = useState(initial.login.userid)
  const [password, setPassword] = useState('')
  const [mode, setMode] = useState(initial.login.trading_mode)

  const [gateway, setGateway] = useState(initial.gateway)
  const [output, setOutput] = useState('')

  const [feed, setFeed] = useState(initial.feed)
  const [symbol, setSymbol] = useState('')
  const [timeframe, setTimeframe] = useState<string>('1m')

  const [steps, setSteps] = useState<Step[] | null>(null)

  useEffect(() => { setGateway(initial.gateway) }, [initial.gateway])

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label); setErr(null); setSaved(null)
    try {
      await fn()
    } catch (e) {
      setErr(e instanceof TransportError ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  const addSeries = () => {
    const s = symbol.trim().toUpperCase()
    if (!s) return
    setFeed((f) => ({ ...f, live: [...f.live, { symbol_id: s, timeframe }] }))
    setSymbol('')
  }
  const removeSeries = (row: LiveSeries) =>
    setFeed((f) => ({ ...f, live: f.live.filter((x) => x !== row) }))

  const running = gateway.status === 'running'

  return (
    <PanelBody>
      {err && <div className="label" style={{ ...note, color: 'var(--verdict-blocked)' }}>{err}</div>}
      {saved && <div className="label" style={{ ...note, color: 'var(--verdict-pass)' }}>{saved}</div>}

      <Section title="1 · IBKR login" dense>
        <form
          className="flex flex-col gap-1"
          onSubmit={(e) => {
            e.preventDefault()
            run('login', async () => {
              await api.brokerLogin({ userid, trading_mode: mode, ...(password ? { password } : {}) })
              setPassword('')
              setSaved(running ? 'login saved — restart the gateway to use it' : 'login saved')
              reload()
            })
          }}
        >
          <div className="flex items-center gap-1 flex-wrap">
            <input className="field" placeholder="username (the paper login for paper)" autoComplete="username"
              spellCheck={false} value={userid} onChange={(e) => setUserid(e.target.value)} style={{ flex: 1, minWidth: 140 }} />
            <input className="field" type="password" autoComplete="new-password"
              placeholder={initial.login.password_saved ? 'password saved — type to replace' : 'password'}
              value={password} onChange={(e) => setPassword(e.target.value)} style={{ flex: 1, minWidth: 140 }} />
            <select className="field" value={mode} onChange={(e) => setMode(e.target.value as 'paper' | 'live')} style={{ width: 72 }}>
              <option value="paper">paper</option>
              <option value="live">live</option>
            </select>
            <button type="submit" className="btn-ghost"
              disabled={!!busy || !userid.trim() || (!password && !initial.login.password_saved)}>
              {busy === 'login' ? 'saving…' : 'save'}
            </button>
          </div>
          <div className="label" style={note}>
            written to {initial.login.env_file} (0600), read only by the gateway container. No API key exists for
            IBKR — this login is the credential. The API stays read-only in both modes: nothing here can place an order.
          </div>
        </form>
      </Section>

      <Section title="2 · gateway" dense>
        <div className="flex items-center gap-2 flex-wrap">
          <Chip tone={running ? (gateway.health === 'unhealthy' ? 'warn' : 'good') : 'bad'}>
            {gateway.status}{gateway.health ? ` · ${gateway.health}` : ''}
          </Chip>
          <button className="btn-ghost" disabled={!!busy || !initial.login.password_saved}
            onClick={() => run('start', async () => {
              const r = await api.brokerGateway('start')
              setGateway(r); setOutput(r.output)
              if (!r.ok) throw new Error('docker compose failed — see output below')
              setSaved('gateway starting — login takes a few minutes; approve 2FA on your phone if asked')
            })}>
            {busy === 'start' ? 'starting… (first run pulls the image)' : running ? 'restart with saved login' : 'start'}
          </button>
          {running && (
            <button className="btn-ghost" disabled={!!busy}
              onClick={() => run('stop', async () => { const r = await api.brokerGateway('stop'); setGateway(r); setOutput(r.output) })}>
              stop
            </button>
          )}
          <span className="label" style={note}>{gateway.detail}</span>
        </div>
        {output && (
          <pre className="num" style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-faint)', whiteSpace: 'pre-wrap', maxHeight: 120, overflowY: 'auto', margin: '4px 0 0' }}>
            {output}
          </pre>
        )}
      </Section>

      <Section title="3 · data feed" dense>
        <div className="flex items-center gap-2 flex-wrap" style={{ fontSize: 'var(--fs-tiny)' }}>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={feed.enabled} onChange={(e) => setFeed({ ...feed, enabled: e.target.checked })} />
            IBKR feed on
          </label>
          <select className="field" value={feed.market_data_type}
            onChange={(e) => setFeed({ ...feed, market_data_type: e.target.value as 'delayed' | 'realtime' })} style={{ width: 96 }}>
            <option value="delayed">delayed (free)</option>
            <option value="realtime">realtime</option>
          </select>
          <span className="label" style={note}>port</span>
          <input className="field num" type="number" value={feed.port}
            onChange={(e) => setFeed({ ...feed, port: Number(e.target.value) })} style={{ width: 64 }} />
        </div>

        <div className="flex flex-col" style={{ marginTop: 6 }}>
          {feed.live.length === 0 && <span className="label" style={note}>no contracts streamed yet — add one below</span>}
          {feed.live.map((row) => (
            <div key={`${row.symbol_id}:${row.timeframe}`} className="flex items-center gap-2" style={{ fontSize: 'var(--fs-tiny)', minHeight: 20 }}>
              <span className="num" style={{ color: 'var(--ink)' }}>{row.symbol_id}</span>
              <span className="label">{row.timeframe}</span>
              <span style={{ flex: 1 }} />
              <button className="btn-ghost" onClick={() => select({ symbolId: row.symbol_id, timeframe: row.timeframe })}
                title="show this series in the chart on this page">chart</button>
              <button className="btn-ghost" onClick={() => removeSeries(row)} title="stop streaming this">✕</button>
            </div>
          ))}
        </div>

        <form className="flex items-center gap-1" style={{ marginTop: 4 }} onSubmit={(e) => { e.preventDefault(); addSeries() }}>
          <input className="field" placeholder="contract — NQZ6, ESZ6, or FUT:CME:NQ:2026-12" spellCheck={false}
            value={symbol} onChange={(e) => setSymbol(e.target.value)} style={{ flex: 1, minWidth: 120 }} />
          <select className="field" value={timeframe} onChange={(e) => setTimeframe(e.target.value)} style={{ width: 58 }}>
            {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
          </select>
          <button type="submit" className="btn-ghost" disabled={!symbol.trim()}>add</button>
        </form>

        <div className="flex items-center gap-2" style={{ marginTop: 6 }}>
          <button className="btn-ghost" disabled={!!busy}
            onClick={() => run('feed', async () => {
              const r = await api.brokerFeed(feed)
              setFeed({ ...feed, live: r.live })
              setSaved('feed saved and applied — the session reconnects, backfills, then streams')
            })}>
            {busy === 'feed' ? 'saving…' : 'save & apply'}
          </button>
          <span className="label" style={note}>
            a contract month, not bare NQ — Genesis never guesses the front month. NQZ6 = Dec 2026.
          </span>
        </div>
      </Section>

      <Section title="4 · test connection" dense>
        <button className="btn-ghost" disabled={!!busy}
          onClick={() => run('test', async () => { setSteps(null); setSteps((await api.brokerTest()).steps) })}>
          {busy === 'test' ? 'testing… (up to 30s)' : 'run test'}
        </button>
        {steps && <CheckSteps steps={steps} />}
      </Section>
    </PanelBody>
  )
}

/** The layered check, one line per layer. Shared with ACC's refresh. */
export function CheckSteps({ steps }: { steps: Step[] }) {
  return (
    <div className="flex flex-col gap-1" style={{ marginTop: 6 }}>
      {steps.map((s) => (
        <div key={s.step} className="flex items-baseline gap-2" style={{ fontSize: 'var(--fs-tiny)' }}>
          <span className="num" style={{ color: s.ok ? 'var(--verdict-pass)' : 'var(--state-down)', width: 10 }}>{s.ok ? '✓' : '✕'}</span>
          <span style={{ color: 'var(--ink)', minWidth: 110 }}>{s.step}</span>
          <span className="label" style={note}>{s.detail}</span>
        </div>
      ))}
    </div>
  )
}
