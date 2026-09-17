// Spec: Genesis Markdown/60-UI/Desktop Shell.md §Settings window · 50-Risk/Safety Invariants.md #5
//
// Settings: microphone, data, agents, tools, and approval mode.
//
// Two rules run through all of it.
//
// **Everything shown is read from the running system.** The device list is
// enumerated from this machine's audio hardware; the agents are the ones whose
// modules import; the tools are the configured catalogue; the config is the
// effective config the daemon loaded. Nothing is a plausible-looking default.
//
// **Approval mode is displayed and not editable here.** `Safety Invariants` #9:
// loosening autonomy *"requires an explicit action in the Dashboard, logged.
// Never by voice alone. Never by an agent."* A select box in a settings panel is
// not that action — it is the frictionless version of exactly the thing the
// invariant exists to prevent. So this panel shows the current mode, explains
// what it means, and says where the change is made.

import { useEffect, useState } from 'react'
import { api, get, type AgentRow, type AudioDevice } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { Chip, Metric, Num, PanelBody, Section, Table } from '@/components/Primitives'
import { SafetyFloor } from '@/components/SafetyFloor'
import { speak } from '@/lib/speak'
import { useGenesis } from '@/store/useGenesis'
import { stagger } from '@/lib/motion'

// ---------------------------------------------------------------------------
// Microphone
// ---------------------------------------------------------------------------

/**
 * Input devices, from `sounddevice` on the daemon side.
 *
 * The selection is remembered per viewer in `localStorage` and handed to
 * `getUserMedia` as a `deviceId` constraint. It is deliberately *not* sent to
 * the daemon: the microphone belongs to the browser that is capturing, and a
 * machine-wide default stored server-side would be wrong the moment the UI is
 * opened from a second device.
 */
interface VoiceStatus {
  backends: string[]
  reason: string | null
  cached_clips: number
}

export function AudioSettingsPanel() {
  const { state, reload } = useRead(() => api.audioDevices(), [])
  const tts = useRead(
    () => get<VoiceStatus>('/v1/voice/status'), [],
  )
  const [test, setTest] = useState<string | null>(null)
  const [chosen, setChosen] = useState<string | null>(() => {
    try { return localStorage.getItem('genesis.audio.input') } catch { return null }
  })

  const choose = (device: AudioDevice) => {
    const value = String(device.index)
    setChosen(value)
    try { localStorage.setItem('genesis.audio.input', value) } catch { /* private window */ }
  }

  if (state.status === 'loading') return <Loading rows={3} label="audio devices" />
  if (state.status === 'absent') {
    return (
      <Absent
        reason={`${state.reason} — the device list comes from the daemon, so voice capture in the browser still works; only the picker is unavailable.`}
        onRetry={reload}
      />
    )
  }
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  const devices = state.data.devices
  if (!devices.length) return <Empty>no input devices found on this machine</Empty>

  return (
    <PanelBody>
      <Section title="microphone" dense>
        <div className="flex flex-col" style={{ gap: 2 }}>
          {devices.map((device, index) => {
            const selected = chosen === String(device.index)
            return (
              <button
                key={device.index}
                className="row-hit lift flex items-center gap-2"
                data-selected={selected}
                style={{ ['--i' as string]: stagger(index, 18), padding: '4px 7px', textAlign: 'left' }}
                onClick={() => choose(device)}
              >
                <span
                  aria-hidden
                  style={{
                    width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                    background: selected ? 'var(--core)' : 'transparent',
                    border: `1px solid ${selected ? 'var(--core)' : 'var(--ink-ghost)'}`,
                  }}
                />
                <span
                  style={{
                    fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}
                >
                  {device.name}
                </span>
                <span style={{ flex: 1 }} />
                {device.default && <Chip tone="neutral">system default</Chip>}
                <span className="label" style={{ color: 'var(--ink-ghost)' }}>
                  {device.channels}ch · {Math.round(device.sample_rate / 1000)}kHz
                </span>
              </button>
            )
          })}
        </div>
      </Section>

      <Section title="transcription" dense>
        <div style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)', lineHeight: 1.6 }}>
          Speech is transcribed <strong style={{ color: 'var(--ink)' }}>locally</strong> by
          faster-whisper (<span className="num">tiny.en</span>, CPU). Audio does
          not leave this machine, and the whole listening path works with no API
          key.
        </div>
      </Section>

      {/* Whether Genesis can talk back. Shown explicitly, because the failure
          mode of a missing key is *silence* — indistinguishable from not having
          been heard, which is the worst possible way for this to break. */}
      <Section title="speech" dense>
        {tts.state.status === 'loading' ? (
          <Loading rows={1} />
        ) : tts.state.status !== 'ready' ? (
          <Absent reason={tts.state.reason} onRetry={tts.reload} />
        ) : tts.state.data.backends.length === 0 ? (
          <div style={{ fontSize: 'var(--fs-tiny)', color: 'var(--state-blocked)', lineHeight: 1.6 }}>
            {tts.state.data.reason ?? 'no TTS backend configured'} — Genesis will
            answer in text and stay silent.
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2">
              <Chip tone="good">{tts.state.data.backends[0]}</Chip>
              <span className="label" style={{ color: 'var(--ink-ghost)' }}>
                {tts.state.data.backends.length > 1
                  ? `+${tts.state.data.backends.length - 1} fallback`
                  : 'no fallback'}
                {tts.state.data.cached_clips > 0 && ` · ${tts.state.data.cached_clips} cached`}
              </span>
              <span style={{ flex: 1 }} />
              <button
                className="btn"
                onClick={async () => {
                  setTest('speaking…')
                  const attempt = await speak('Genesis is online.')
                  setTest(attempt.ok ? 'spoke' : attempt.reason)
                }}
              >
                test voice
              </button>
            </div>
            {test && (
              <div
                style={{
                  fontSize: 'var(--fs-micro)',
                  color: test === 'spoke' ? 'var(--verdict-pass)' : 'var(--state-blocked)',
                  lineHeight: 1.5,
                }}
              >
                {test}
              </div>
            )}
          </div>
        )}
      </Section>

      <div className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0, lineHeight: 1.5 }}>
        The chosen device is stored in this browser and passed to getUserMedia.
        It is not sent to the daemon — the microphone belongs to whichever
        machine is capturing.
      </div>
    </PanelBody>
  )
}

// ---------------------------------------------------------------------------
// Agents
// ---------------------------------------------------------------------------

/**
 * The fleet as code.
 *
 * `reflex` — `model_tier: none` — is rendered as a distinct chip rather than as
 * one tier among six, because `Biological Design` §1 makes it a categorically
 * different thing: *"`tier: none` components are not agents without a model
 * yet; they are spinal cord, and giving one a model is the bug."* A settings
 * screen that lists it as a dropdown option invites exactly that bug.
 */
export function AgentSettingsPanel() {
  const { state, reload } = useRead(() => api.agents(), [])

  if (state.status === 'loading') return <Loading rows={6} label="fleet" />
  if (state.status !== 'ready') return <Absent reason={state.reason} onRetry={reload} />

  const { agents, families, count } = state.data

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 hairline-b" style={{ padding: '4px 8px', flexShrink: 0 }}>
        <span className="label">{count} agents on disk</span>
        <span style={{ flex: 1 }} />
        {Object.entries(families).map(([family, n]) => (
          <span key={family} className="label" style={{ color: 'var(--ink-ghost)' }}>
            {family} <span className="num">{n}</span>
          </span>
        ))}
      </div>

      <Table
        rows={agents}
        keyOf={(row) => row.id}
        columns={[
          {
            key: 'name', header: 'agent', width: 150,
            render: (row: AgentRow) => (
              <span style={{ color: row.built ? 'var(--ink)' : 'var(--state-down)' }}>
                {row.name ?? row.id}
              </span>
            ),
          },
          {
            key: 'family', header: 'family', width: 76,
            render: (row: AgentRow) => <span className="label">{row.family}</span>,
          },
          {
            key: 'tier', header: 'model', width: 88,
            render: (row: AgentRow) =>
              row.reflex ? (
                <Chip tone="spinal" title="tier: none — deterministic, cannot hallucinate. Spinal cord, not an agent awaiting a model.">
                  reflex
                </Chip>
              ) : (
                <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>
                  {row.model_tier}
                </span>
              ),
          },
          {
            key: 'cadence', header: 'fires on',
            render: (row: AgentRow) => (
              <span className="label" style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--ink-faint)' }}>
                {row.cadence.map((c) =>
                  c.interval_sec ? `${c.type} ${c.interval_sec}s` : c.type,
                ).join(', ') || '—'}
              </span>
            ),
          },
          {
            key: 'tools', header: 'tools', align: 'right', width: 54,
            render: (row: AgentRow) => <Num value={row.tools.length} digits={0} />,
          },
          {
            key: 'concurrency', header: 'max', align: 'right', width: 44,
            render: (row: AgentRow) => <Num value={row.max_concurrent} digits={0} />,
          },
        ]}
      />

      <div
        className="label hairline-t"
        style={{ padding: '4px 8px', color: 'var(--ink-ghost)', flexShrink: 0,
          textTransform: 'none', letterSpacing: 0, lineHeight: 1.5 }}
      >
        Discovered by importing every module under `genesis.agents`. An agent
        appears because its code exists — the vault specifies more than this,
        and the difference is the honest one.
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

export function DataSettingsPanel() {
  const symbols = useRead(() => api.symbols(), [])
  const config = useRead(() => api.config(), [])

  return (
    <PanelBody>
      <Section title="series held" dense>
        {symbols.state.status === 'ready' ? (
          symbols.state.data.symbols.length ? (
            <div className="flex flex-col gap-1">
              {symbols.state.data.symbols.map((row) => (
                <div key={`${row.symbol_id}:${row.timeframe}`} className="flex items-baseline gap-2" style={{ fontSize: 'var(--fs-tiny)' }}>
                  <span style={{ color: 'var(--ink)', width: 60 }}>{row.symbol}</span>
                  <span className="label">{row.timeframe}</span>
                  <span className="num" style={{ color: 'var(--ink-faint)' }}>{row.bars} bars</span>
                  <span style={{ flex: 1 }} />
                  <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>
                    {row.coverage[0]?.source}
                  </span>
                  <Chip tone={(row.coverage[0]?.tier ?? 9) <= 1 ? 'good' : 'warn'}>
                    tier {row.coverage[0]?.tier ?? '?'}
                  </Chip>
                </div>
              ))}
            </div>
          ) : <Empty>nothing ingested</Empty>
        ) : <Loading rows={2} />}
      </Section>

      <Section title="feeds" dense>
        {config.state.status === 'ready' ? (
          <ConfigTree
            value={(config.state.data.config as Record<string, unknown>).marketdata}
            depth={0}
          />
        ) : config.state.status === 'loading' ? <Loading rows={3} />
          : <Absent reason={config.state.reason} onRetry={config.reload} />}
      </Section>
    </PanelBody>
  )
}

/**
 * Config, rendered as a tree.
 *
 * Read-only, and that is the honest shape today: the daemon has no route that
 * writes config, so an editable field here would be a control that silently
 * does nothing. Showing the effective values and where they came from is the
 * true version of this panel until a write path exists.
 */
function ConfigTree({ value, depth }: { value: unknown; depth: number }) {
  if (value === null || value === undefined) {
    return <span className="num" style={{ color: 'var(--ink-ghost)' }}>—</span>
  }
  if (typeof value !== 'object') {
    return (
      <span className="num" style={{ color: 'var(--ink-dim)', fontSize: 'var(--fs-tiny)' }}>
        {String(value)}
      </span>
    )
  }
  if (Array.isArray(value)) {
    return (
      <span className="num" style={{ color: 'var(--ink-dim)', fontSize: 'var(--fs-tiny)' }}>
        {value.length ? value.map(String).join(', ') : '—'}
      </span>
    )
  }
  if (depth > 2) {
    return <span className="label" style={{ color: 'var(--ink-ghost)' }}>…</span>
  }
  return (
    <div className="flex flex-col gap-0.5" style={{ paddingLeft: depth ? 10 : 0 }}>
      {Object.entries(value as Record<string, unknown>).map(([key, child]) => (
        <div key={key} className="flex gap-3" style={{ alignItems: 'baseline' }}>
          <span className="label" style={{ letterSpacing: '0.06em', minWidth: 118, flexShrink: 0 }}>
            {key.replace(/_/g, ' ')}
          </span>
          <div style={{ flex: 1, minWidth: 0, overflow: 'hidden' }}>
            <ConfigTree value={child} depth={depth + 1} />
          </div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Approval — shown, never changed here
// ---------------------------------------------------------------------------

const MODES: Record<string, { label: string; note: string; tone: 'good' | 'warn' | 'bad' }> = {
  advisory: { label: 'ADVISORY', note: 'Genesis proposes. Nothing reaches a broker.', tone: 'good' },
  confirm: { label: 'CONFIRM', note: 'Every order needs your word before it is placed.', tone: 'good' },
  'auto-within-limits': {
    label: 'AUTO', note: 'Orders inside the risk envelope place without asking.', tone: 'warn',
  },
  halt: { label: 'HALT', note: 'Nothing places. The kill switch has fired or you set this.', tone: 'bad' },
}

export function ApprovalSettingsPanel() {
  const mode = useGenesis((s) => s.safety.approvalMode)
  const halted = useGenesis((s) => s.safety.halted)
  const current = MODES[mode] ?? MODES.confirm
  // One clock, read here rather than threaded down: this panel is where the
  // full safety readout now lives, and staleness is a function of *now*.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  return (
    <PanelBody>
      <Section title="approval mode" dense>
        <div className="flex items-baseline gap-3">
          <span
            className="num"
            style={{
              fontSize: 'var(--fs-xl)', fontWeight: 700, letterSpacing: '0.06em',
              color: current.tone === 'bad' ? 'var(--state-down)'
                : current.tone === 'warn' ? 'var(--state-blocked)' : 'var(--verdict-pass)',
            }}
          >
            {current.label}
          </span>
          {halted && <Chip tone="bad">halted</Chip>}
        </div>
        <div style={{ fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)', lineHeight: 1.6 }}>
          {current.note}
        </div>
      </Section>

      {/* The full safety readout.
        *
        * It used to be five permanent cells in the shell chrome. In this phase
        * four of them render an em dash -- no broker, no position, no
        * reconciliation -- so it collapsed to a one-line strip up there and
        * lives in full here. Same component, so the summary and the detail
        * cannot disagree.
        *
        * `UI Stack §6` still holds: the strip is plain DOM, first painted, and
        * inside its own boundary. This is the expanded view, not a second
        * implementation. It returns to the chrome in Phase 7. */}
      <Section title="risk readout" dense>
        <SafetyFloor now={now} variant="full" defaultOpen />
        <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', lineHeight: 1.5, marginTop: 6 }}>
          Also on the strip at the top of the window — click it to expand in place.
          Heat and headroom read as em dashes until there is a position to
          measure; that is the absence of a broker, not a zero.
        </div>
      </Section>

      <Section title="the other modes" dense>
        <div className="flex flex-col gap-1.5">
          {Object.entries(MODES).filter(([id]) => id !== mode).map(([id, value]) => (
            <div key={id} className="flex flex-col" style={{ opacity: 0.6 }}>
              <span className="label" style={{ letterSpacing: '0.12em' }}>{value.label}</span>
              <span style={{ fontSize: 'var(--fs-micro)', color: 'var(--ink-faint)', lineHeight: 1.5 }}>
                {value.note}
              </span>
            </div>
          ))}
        </div>
      </Section>

      {/* The reason there is no control here. Stated, not implied by absence. */}
      <div
        style={{
          fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)', lineHeight: 1.6,
          padding: '7px 9px', background: 'var(--bg-inset)',
          border: '1px solid var(--hairline)', borderLeft: '2px solid var(--state-blocked)',
          borderRadius: 'var(--r-sm)',
        }}
      >
        Mode is not changeable from this panel, deliberately. Safety Invariants
        #9: loosening autonomy “requires an explicit action in the Dashboard,
        logged. Never by voice alone. Never by an agent.” A dropdown in a
        settings screen is the frictionless version of the thing that rule
        exists to prevent.
      </div>
    </PanelBody>
  )
}

// ---------------------------------------------------------------------------
// Models
// ---------------------------------------------------------------------------

/**
 * Which model serves each tier, whether it can be reached, and what it cost.
 *
 * Three things this panel refuses to do.
 *
 * **It does not probe on render.** Reachability here is "is the key present",
 * not "did a call succeed" — a settings page that fires four completions on
 * open bills the operator for looking at it. The live probe is
 * `genesis config check`, which a person chooses to run.
 *
 * **It does not claim a change took effect.** Fleets bind their backends once,
 * at construction, so a switched tier applies on the next daemon restart. The
 * panel says exactly that instead of showing a satisfied green tick over a
 * daemon still talking to the old provider.
 *
 * **It never renders an unpriced model as $0.00.** `cost_usd` comes back null
 * for local models and for anything absent from the price table, and null is
 * shown as "local" or "—". A zero would be a number the operator would budget
 * against.
 */
export function ModelSettingsPanel() {
  const { state, reload } = useRead(() => api.models(), [])
  const [pending, setPending] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  if (state.status === 'loading') return <Loading rows={4} label="model tiers" />
  if (state.status === 'absent') return <Absent reason={state.reason} onRetry={reload} />

  // `ready` with a null body is the daemon answering "available, nothing to
  // report" — a fresh install before any model has been called.
  const body = state.data
  if (!body) return <Empty>no model tiers reported</Empty>

  const usageFor = (tier: string) => body.usage_today.filter((u) => u.tier === tier)
  const spend = body.usage_today.reduce((sum, u) => sum + (u.cost_usd ?? 0), 0)
  const budgetPct = body.daily_token_budget
    ? body.tokens_today / body.daily_token_budget : 0

  const switchTo = async (tier: string, backend: string, model: string) => {
    setPending(tier)
    setNote(null)
    try {
      const result = await api.setModelTier(tier, backend, model)
      setNote(
        result.changed
          ? `${result.tier} → ${result.backend}/${result.model} · restart the daemon to apply`
          : `${result.tier} was already ${result.backend}/${result.model}`,
      )
      reload()
    } catch (error) {
      setNote(error instanceof Error ? error.message : 'could not switch tier')
    } finally {
      setPending(null)
    }
  }

  return (
    <PanelBody>
      <Section title="today" dense>
        <div className="flex flex-wrap gap-1">
          <Metric label="tokens" value={body.tokens_today} digits={0} />
          <Metric
            label="of budget"
            value={budgetPct * 100}
            digits={1}
            suffix="%"
            hint={`${body.daily_token_budget.toLocaleString()} token/day budget`}
          />
          <Metric
            label="est. spend"
            value={spend ? spend : null}
            digits={4}
            hint="priced tiers only; local models are free"
            wide
          />
          <Metric label="calls" value={body.usage_today.reduce((n, u) => n + u.calls, 0)} digits={0} />
        </div>
        {/* The budget refuses now (`llm/usage.py` Budget), so this says what
            happens at the ceiling rather than that nothing does. Degraded, not
            halted: every tier-none path has no model in it and keeps working. */}
        <div className="label" style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--ink-ghost)' }}>
          {budgetPct >= 1
            ? 'budget spent — hosted tiers are closed until midnight UTC; deterministic agents unaffected'
            : 'at the ceiling, hosted tiers degrade until midnight UTC — deterministic agents keep working'}
        </div>
      </Section>

      <Section title="tiers" dense>
        <div className="flex flex-col gap-1">
          {body.tiers.map((tier) => {
            const used = usageFor(tier.tier)
            const tokens = used.reduce((n, u) => n + u.total_tokens, 0)
            const failures = used.reduce((n, u) => n + u.failures, 0)
            const blocked = tier.dev_only && body.live_broker
            return (
              <div
                key={tier.tier}
                className="flex items-baseline gap-2"
                style={{ fontSize: 'var(--fs-tiny)' }}
              >
                <span style={{ color: 'var(--ink)', width: 64 }}>{tier.tier}</span>
                <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>
                  {tier.backend === 'none' ? 'deterministic code' : `${tier.backend}/${tier.model}`}
                </span>
                <span style={{ flex: 1 }} />
                {tokens > 0 && (
                  <span className="num" style={{ color: 'var(--ink-faint)' }}>
                    {tokens.toLocaleString()} tok
                  </span>
                )}
                {failures > 0 && <Chip tone="bad">{failures} failed</Chip>}
                {tier.local && <Chip tone="good">local</Chip>}
                {blocked ? (
                  <Chip tone="bad">blocked — live broker</Chip>
                ) : tier.dev_only ? (
                  <Chip tone="warn">dev only</Chip>
                ) : null}
                {!tier.key_present && (
                  <Chip tone="bad">{tier.env_var} missing</Chip>
                )}
                {/* A local tier with nothing pulled has no key to be missing
                    and no vendor to be down — it just silently 404s every
                    call. The daemon checks that over loopback, for free. */}
                {tier.blocker && <Chip tone="bad" title={tier.blocker}>{tier.blocker}</Chip>}
              </div>
            )
          })}
        </div>
      </Section>

      <Section title="switch" dense>
        {/* The same call `genesis config set-tier` makes — one door, two
            callers, per the parity rule. */}
        <div className="flex flex-col gap-1">
          {SWITCHES.map((choice) => (
            <button
              key={`${choice.tier}:${choice.backend}:${choice.model}`}
              type="button"
              className="flex items-baseline gap-2"
              disabled={pending !== null}
              onClick={() => switchTo(choice.tier, choice.backend, choice.model)}
              style={{
                fontSize: 'var(--fs-tiny)',
                padding: '3px 6px',
                background: 'var(--bg-raised)',
                border: '1px solid var(--hairline)',
                borderRadius: 'var(--r-sm)',
                cursor: pending ? 'wait' : 'pointer',
                textAlign: 'left',
                opacity: pending === choice.tier ? 0.5 : 1,
              }}
            >
              <span style={{ color: 'var(--ink)', width: 58 }}>{choice.tier}</span>
              <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>
                {choice.backend}/{choice.model}
              </span>
              <span style={{ flex: 1 }} />
              <span className="label" style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--ink-ghost)' }}>
                {choice.why}
              </span>
            </button>
          ))}
        </div>
        {note && (
          <div className="label" style={{ textTransform: 'none', letterSpacing: 0, color: 'var(--ink-faint)' }}>
            {note}
          </div>
        )}
      </Section>

      {body.history.length > 1 && (
        <Section title="last days" dense>
          <div className="flex flex-col gap-0.5">
            {body.history.slice(-7).reverse().map((day) => (
              <div key={day.day} className="flex items-baseline gap-2" style={{ fontSize: 'var(--fs-tiny)' }}>
                <span className="num" style={{ color: 'var(--ink-faint)', width: 78 }}>{day.day}</span>
                <span className="num" style={{ color: 'var(--ink)' }}>
                  {(day.input_tokens + day.output_tokens).toLocaleString()}
                </span>
                <span className="label" style={{ textTransform: 'none', letterSpacing: 0 }}>
                  {day.input_tokens.toLocaleString()} in · {day.output_tokens.toLocaleString()} out
                </span>
              </div>
            ))}
          </div>
        </Section>
      )}
    </PanelBody>
  )
}

/**
 * The switches offered.
 *
 * A fixed list rather than free text: these are the combinations that have
 * actually been run on this machine, and a text box inviting any model string
 * is a way to write a tier that 404s at the provider and only fails at the
 * next restart. `genesis config set-tier` takes anything, for the case where
 * you know what you are doing.
 */
const SWITCHES: { tier: string; backend: string; model: string; why: string }[] = [
  // `small` is the planner — the rung that turns a sentence into dispatched
  // agents. It had no hosted free option here, so the only way off Anthropic
  // was Ollama, and picking that on a machine with nothing pulled left the
  // planner answering 404 with nothing on screen to say so.
  { tier: 'small', backend: 'gemini', model: 'gemini-flash-lite-latest', why: 'free tier, trains on prompts' },
  { tier: 'small', backend: 'ollama', model: 'qwen2.5:3b', why: 'free, local, needs `ollama pull`' },
  { tier: 'small', backend: 'anthropic', model: 'claude-haiku-4-5', why: 'production' },
  // Flash-lite before flash: same free tier, far higher daily quota, and it is
  // the one that keeps answering after flash has spent its allowance.
  { tier: 'large', backend: 'gemini', model: 'gemini-flash-lite-latest', why: 'free tier, highest quota' },
  { tier: 'large', backend: 'gemini', model: 'gemini-flash-latest', why: 'free tier, smarter, lower quota' },
  { tier: 'large', backend: 'anthropic', model: 'claude-opus-5', why: 'production' },
  { tier: 'vision', backend: 'gemini', model: 'gemini-flash-lite-latest', why: 'free tier, highest quota' },
  { tier: 'vision', backend: 'gemini', model: 'gemini-flash-latest', why: 'free tier, smarter, lower quota' },
  { tier: 'vision', backend: 'anthropic', model: 'claude-opus-5', why: 'production' },
]
