// Spec: Genesis Markdown/10-Architecture/Market Data Plane.md §Live session · deploy/ib-gateway/README.md
//
// ACC — the IBKR account. Connection, login, balances, positions.
//
// Read-only, and so is the socket behind it: the gateway runs with Read-Only
// API on. Paper or live is the broker's own answer (the account id it returned),
// not something this panel infers from a port number.
//
// Loaded once on mount, then kept current by `broker.account` and
// `broker.connection` pushes from the server — it never polls.

import { useEffect, useState } from 'react'
import { api, TransportError, type BrokerAccount, type BrokerAccountBody } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { Chip, Metric, PanelBody, Section, Table } from '@/components/Primitives'
import { useGenesis } from '@/store/useGenesis'
import { BrokerSetup, CheckSteps, type Step } from './broker'

const STATE_TONE = { live: 'good', syncing: 'good', quiet: 'neutral', starting: 'neutral', connecting: 'neutral', down: 'bad' } as const

const BALANCES: [tag: string, label: string][] = [
  ['NetLiquidation', 'net liquidation'],
  ['TotalCashValue', 'cash'],
  ['BuyingPower', 'buying power'],
  ['AvailableFunds', 'available funds'],
  ['ExcessLiquidity', 'excess liquidity'],
  ['InitMarginReq', 'initial margin'],
  ['MaintMarginReq', 'maint. margin'],
  ['UnrealizedPnL', 'unrealized P&L'],
  ['RealizedPnL', 'realized P&L'],
]

export function AccountPanel() {
  const [tab, setTab] = useState<'account' | 'setup'>('account')
  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex gap-1 hairline-b" style={{ padding: '3px 8px', flexShrink: 0 }}>
        {(['account', 'setup'] as const).map((t) => (
          <button key={t} className="btn-ghost" data-active={tab === t} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>{tab === 'account' ? <Account onSetup={() => setTab('setup')} /> : <BrokerSetup />}</div>
    </div>
  )
}

function Account({ onSetup }: { onSetup: () => void }) {
  const { state, reload } = useRead(() => api.brokerAccount(), [])
  const [pushed, setPushed] = useState<Partial<BrokerAccountBody>>({})
  const [steps, setSteps] = useState<Step[] | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  // Reconnect (backfill + account resync) and validate every layer. The live
  // session's pushes then update this panel on their own.
  async function refresh() {
    setRefreshing(true); setSteps(null)
    try {
      setSteps((await api.brokerRefresh()).steps)
    } catch (e) {
      setSteps([{ step: 'refresh', ok: false, detail: e instanceof TransportError ? e.message : String(e) }])
    } finally {
      setRefreshing(false)
      reload()
    }
  }

  useEffect(() => useGenesis.subscribe((s, prev) => {
    const e = s.events[0] as { event: string; data: unknown } | undefined
    if (!e || e === prev.events[0]) return
    if (e.event === 'broker.account') setPushed((p) => ({ ...p, account: e.data as BrokerAccount }))
    if (e.event === 'broker.connection') {
      const d = e.data as { state: BrokerAccountBody['state']; detail: string }
      setPushed((p) => ({ ...p, state: d.state, detail: d.detail, since: new Date().toISOString() }))
    }
  }), [])

  if (state.status === 'loading') return <Loading rows={5} label="IBKR account" />
  if (state.status !== 'ready') {
    return (
      <div className="flex flex-col h-full">
        <Absent reason={state.reason} onRetry={reload} />
        <button className="btn-ghost" onClick={onSetup} style={{ alignSelf: 'center' }}>open setup</button>
      </div>
    )
  }

  const body = { ...state.data, ...pushed }
  const account = body.account

  return (
    <PanelBody>
      <Section
        title="connection"
        dense
        actions={
          <button className="btn-ghost" onClick={refresh} disabled={refreshing}
            title="reconnect to IBKR, fill any gap in the live series, resync the account, and check every layer">
            {refreshing ? 'refreshing…' : 'refresh'}
          </button>
        }
      >
        <div className="flex items-baseline gap-2 flex-wrap" style={{ fontSize: 'var(--fs-tiny)' }}>
          <Chip tone={STATE_TONE[body.state]}>{body.state}</Chip>
          {account && <Chip tone={account.mode === 'paper' ? 'spinal' : 'bad'}>{account.mode}</Chip>}
          <Chip tone={body.market_data_type === 'realtime' ? 'good' : 'warn'}>{body.market_data_type} data</Chip>
          <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>
            gateway {body.gateway} · client {body.client_id}
          </span>
        </div>
        {body.detail && (
          <div className="label" style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--ink-faint)', marginTop: 4 }}>
            {body.detail}
          </div>
        )}
        {steps && <CheckSteps steps={steps} />}
        <div className="label" style={{ textTransform: 'none', letterSpacing: 0, marginTop: 4 }}>
          login {body.login ?? '— (IB_USERID not in ~/.genesis/.env)'}
          {account && <> · account {account.accounts.join(', ') || '—'}</>}
          {' · '}streaming {body.series.map((s) => `${s.symbol_id} ${s.timeframe}`).join(', ') || 'nothing (marketdata.live is empty)'}
        </div>
      </Section>

      {!account ? (
        <Empty hint="Balances arrive once the gateway is up and logged in. `cd deploy/ib-gateway && docker compose ps`">
          no account reported yet
        </Empty>
      ) : (
        <>
          {account.accounts.map((id) => (
            <Section key={id} title={`balances · ${id}`} dense>
              <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8 }}>
                {BALANCES.map(([tag, label]) => {
                  const v = account.values[id]?.[tag]
                  return (
                    <Metric
                      key={tag}
                      label={label}
                      value={v?.value ?? null}
                      suffix={v ? ` ${v.currency}` : undefined}
                      signed={tag.endsWith('PnL')}
                      tone={tag.endsWith('PnL')}
                    />
                  )
                })}
              </div>
            </Section>
          ))}

          <Section title="positions" dense>
            <Table
              rows={account.positions}
              keyOf={(p) => `${p.account}:${p.symbol}`}
              empty={<Empty>flat — no positions</Empty>}
              columns={[
                { key: 'symbol', header: 'symbol', render: (p) => p.symbol },
                { key: 'type', header: 'type', render: (p) => p.sec_type },
                { key: 'qty', header: 'qty', align: 'right', render: (p) => p.position },
                { key: 'avg', header: 'avg cost', align: 'right', render: (p) => p.average_cost.toFixed(2) },
                { key: 'mkt', header: 'mark', align: 'right', render: (p) => p.market_price.toFixed(2) },
                { key: 'upl', header: 'unrl P&L', align: 'right', render: (p) => p.unrealized_pnl.toFixed(2) },
              ]}
            />
          </Section>

          <div className="label" style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--ink-ghost)' }}>
            as reported by IBKR at {new Date(account.as_of).toLocaleTimeString()}
          </div>
        </>
      )}
    </PanelBody>
  )
}
