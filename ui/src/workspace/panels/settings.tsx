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

import { useState } from 'react'
import { api, get, type AgentRow, type AudioDevice } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Absent, Empty, Loading } from '@/components/States'
import { Chip, Num, PanelBody, Section, Table } from '@/components/Primitives'
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
