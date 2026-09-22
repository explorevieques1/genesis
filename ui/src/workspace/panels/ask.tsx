// Spec: Genesis Markdown/60-UI/Ask Genesis.md
//
// The command line, as a module. `⌘K` and the Home canvas are transient — they
// answer once, into the shell's reply strip, and forget. This is the same
// input with a memory: a conversation you can put in any workspace, that
// survives a refresh because the daemon saved it.
//
// It is deliberately NOT a second command path. Every message goes to
// `POST /v1/command` — the exact endpoint `⌘K` and voice post to — so the
// deterministic table still runs first and an unmatched sentence still falls
// through to the analyst ladder. What this adds is the `conversation` id on
// the request, which is the whole of what makes the turn persist.
//
// No model selector, by design (Ask Genesis.md §The model is not a knob here):
// the orchestrator answers on the tier set in Settings → Model Tiers, and a
// per-message override would be a second place that setting lives.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type ConversationTurn, type ScreenPayload } from '@/api/client'
import { useRead } from '@/api/useRead'
import { Loading } from '@/components/States'
import { revealPanel } from '@/workspace/dock'
import { stagger } from '@/lib/motion'
import { ScreenTable } from './screener'

/** A turn as the panel holds it — the persisted shape, plus an in-flight flag. */
type Turn = ConversationTurn & { pending?: boolean }

// The SCR panel hands plain-English refinements to the open conversation, so
// the screen's dialogue lives in one thread. A module slot, not a store: there
// is one Ask Genesis input that matters, the mounted one, and before it mounts
// the text waits for it.
let deliver: ((text: string) => void) | null = null
let queued: string | null = null

/** Send `text` through Ask Genesis, opening it if needed. Same `POST /v1/command` door. */
export function askGenesis(text: string, { refinement = true } = {}) {
  const message = refinement ? `refine the current screen: ${text}` : text
  revealPanel('ask-genesis', { title: 'Ask Genesis' })
  if (deliver) deliver(message)
  else queued = message
}

const OPENERS = [
  'what is the market doing',
  'why is Nvidia down today',
  'chart NVDA daily',
  'find cheap, profitable tech companies still growing revenue',
  'status',
]

export function AskGenesisPanel() {
  const list = useRead(() => api.conversations(), [])
  const [convId, setConvId] = useState<string | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loadingThread, setLoadingThread] = useState(false)
  const [railOpen, setRailOpen] = useState(true)
  const scroller = useRef<HTMLDivElement>(null)

  // New turns pin the view to the bottom, the way every chat does. Not on
  // thread load — landing at the top of an old conversation is correct.
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight })
  }, [turns])

  const openThread = useCallback(async (id: string) => {
    setLoadingThread(true)
    try {
      const res = await api.conversation(id)
      if (res.available && res.conversation) {
        setConvId(res.conversation.id)
        setTurns(res.conversation.turns)
      }
    } finally {
      setLoadingThread(false)
    }
  }, [])

  const newThread = useCallback(() => {
    setConvId(null)
    setTurns([])
    setInput('')
  }, [])

  // `override` is a tapped screener choice: sent as-is, the draft left alone.
  const send = useCallback(async (override?: string) => {
    const text = (override ?? input).trim()
    if (!text || sending) return
    if (override === undefined) setInput('')
    setSending(true)
    setTurns((t) => [
      ...t,
      { ts: '', role: 'operator', text, ok: null, command: null, detail: null, data: null, trace: null },
      { ts: '', role: 'genesis', text: '', ok: null, command: null, detail: null, data: null, trace: null, pending: true },
    ])
    try {
      // '' means "new conversation" — the daemon mints the id and echoes it
      // back; from then on we send the real id and it appends.
      const r = await api.command(text, convId ?? '')
      setTurns((t) => [
        ...t.slice(0, -1),
        {
          ts: '', role: 'genesis', text: r.spoken, ok: r.ok,
          command: r.command, detail: r.detail ?? null,
          data: r.data ?? null, trace: r.trace ?? null,
        },
      ])
      if (r.conversation) {
        if (!convId) setConvId(r.conversation)
        list.reload()
      }
      // Genesis putting a panel on screen through the same dock API a person
      // uses (Operating Model §3) — the one sanctioned unasked-for appearance.
      // ponytail: mirrors the canvas snippet in App.tsx; if a third data-driven
      // open appears, hoist both into one helper.
      if (r.data?.canvas_id) {
        revealPanel('research-canvas', { title: 'Canvas' })
        window.location.hash = 'research'
      }
      // A screen was asked for; its full form is SCR, beside this chat.
      if (r.data?.screen) revealPanel('screener', { title: 'Screener' })
    } catch {
      setTurns((t) => [
        ...t.slice(0, -1),
        {
          ts: '', role: 'genesis', text: 'The daemon did not answer.', ok: false,
          command: 'transport_error', detail: null, data: null, trace: null,
        },
      ])
    } finally {
      setSending(false)
    }
  }, [input, sending, convId, list])

  useEffect(() => {
    deliver = (text) => void send(text)
    if (queued) { const text = queued; queued = null; void send(text) }
    return () => { deliver = null }
  }, [send])

  const rows = list.state.status === 'ready' ? list.state.data.conversations : []

  return (
    <div className="flex h-full" style={{ background: 'var(--bg-void)' }}>
      {/* -- conversation rail -------------------------------------------- */}
      {railOpen ? (
        <div
          className="flex flex-col hairline-r"
          style={{ width: 200, flexShrink: 0, background: 'var(--bg-deep)' }}
        >
          <div className="flex items-center gap-1 hairline-b" style={{ padding: 'var(--s-2) var(--s-3)' }}>
            <button className="btn-ghost" style={{ flex: 1, textAlign: 'left', textTransform: 'none', letterSpacing: 0 }} onClick={newThread}>
              + New conversation
            </button>
            <button className="btn-ghost" title="collapse" onClick={() => setRailOpen(false)}>‹</button>
          </div>
          <div className="scroll-y" style={{ flex: 1 }}>
            {list.state.status === 'loading' && <Loading rows={3} />}
            {rows.length === 0 && list.state.status === 'ready' && (
              <div className="label" style={{ padding: 'var(--s-3)', color: 'var(--ink-ghost)' }}>
                nothing saved yet
              </div>
            )}
            {rows.map((row, i) => (
              <div
                key={row.id}
                className="row-hit flex items-center gap-1 group"
                data-selected={row.id === convId}
                style={{ ['--i' as string]: stagger(i, 10), padding: 'var(--s-2) var(--s-3)' }}
              >
                <button
                  className="truncate"
                  style={{ flex: 1, textAlign: 'left', fontSize: 'var(--fs-tiny)', color: row.id === convId ? 'var(--ink)' : 'var(--ink-dim)' }}
                  onClick={() => openThread(row.id)}
                  title={row.title}
                >
                  {row.title || 'Untitled'}
                </button>
                <button
                  className="btn-ghost"
                  title="delete conversation"
                  style={{ opacity: 0.5 }}
                  onClick={async () => {
                    await api.conversationDelete(row.id)
                    if (row.id === convId) newThread()
                    list.reload()
                  }}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <button
          className="hairline-r btn-ghost"
          style={{ flexShrink: 0, width: 22, background: 'var(--bg-deep)' }}
          title="conversations"
          onClick={() => setRailOpen(true)}
        >
          ›
        </button>
      )}

      {/* -- transcript + composer -------------------------------------- */}
      <div className="flex flex-col" style={{ flex: 1, minWidth: 0 }}>
        <div ref={scroller} className="scroll-y" style={{ flex: 1, padding: 'var(--s-5) var(--s-6)' }}>
          {loadingThread ? (
            <Loading rows={4} label="conversation" />
          ) : turns.length === 0 ? (
            <div className="flex flex-col" style={{ gap: 'var(--s-4)', maxWidth: 520 }}>
              <div style={{ fontSize: 'var(--fs-base)', color: 'var(--ink-dim)' }}>
                Ask Genesis anything. This conversation is saved.
              </div>
              <div className="flex flex-col" style={{ gap: 'var(--s-1)' }}>
                {OPENERS.map((text, i) => (
                  <button
                    key={text}
                    className="row-hit lift"
                    style={{ ['--i' as string]: stagger(i, 20), textAlign: 'left', padding: 'var(--s-2) var(--s-4)', fontSize: 'var(--fs-sm)', color: 'var(--ink-faint)' }}
                    onClick={() => setInput(text)}
                  >
                    {text}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex flex-col" style={{ gap: 'var(--s-5)' }}>
              {turns.map((turn, i) => (
                <TurnView key={i} turn={turn} onChoice={i === turns.length - 1 ? send : undefined} />
              ))}
            </div>
          )}
        </div>

        <div className="hairline-t" style={{ padding: 'var(--s-3) var(--s-4)', background: 'var(--bg-panel)' }}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send() }
            }}
            placeholder="Message Genesis…  (↵ send · ⇧↵ newline)"
            rows={2}
            style={{
              width: '100%', resize: 'none', background: 'var(--bg-inset)',
              border: '1px solid var(--hairline)', borderRadius: 'var(--r-sm)',
              padding: 'var(--s-3)', fontSize: 'var(--fs-sm)', color: 'var(--ink)', outline: 'none',
            }}
          />
          <div className="label" style={{ marginTop: 'var(--s-1)', color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}>
            {sending ? 'Genesis is working…' : 'answers use the tier set in Settings → Model Tiers'}
          </div>
        </div>
      </div>
    </div>
  )
}

function TurnView({ turn, onChoice }: { turn: Turn; onChoice?: (text: string) => void }) {
  if (turn.role === 'operator') {
    return (
      <div style={{ alignSelf: 'flex-end', maxWidth: '82%' }}>
        <div
          style={{
            background: 'var(--bg-raised)', border: '1px solid var(--hairline)',
            borderRadius: 'var(--r-sm)', padding: 'var(--s-2) var(--s-3)',
            fontSize: 'var(--fs-sm)', color: 'var(--ink)', whiteSpace: 'pre-wrap',
          }}
        >
          {turn.text}
        </div>
      </div>
    )
  }

  const bad = turn.ok === false
  return (
    <div style={{ alignSelf: 'flex-start', maxWidth: '90%' }}>
      <div
        style={{
          borderLeft: `2px solid ${bad ? 'var(--state-down)' : 'var(--core-hot)'}`,
          paddingLeft: 'var(--s-3)',
        }}
      >
        {turn.pending ? (
          <span className="anim-pulse label" style={{ color: 'var(--ink-faint)' }}>…</span>
        ) : (
          <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--ink)', whiteSpace: 'pre-wrap' }}>
            {turn.text}
          </div>
        )}
        {turn.data?.screen && !turn.pending && <ScreenSummary raw={turn.data.screen} onChoice={onChoice} />}
        {(turn.command || turn.detail) && !turn.pending && (
          <div className="label" style={{ marginTop: 'var(--s-1)', color: 'var(--ink-faint)', textTransform: 'none', letterSpacing: 0 }}>
            {turn.command}{turn.detail ? ` · ${turn.detail}` : ''}
          </div>
        )}
      </div>
    </div>
  )
}

// -- screener ---------------------------------------------------------------
// Spec: Genesis Markdown/60-UI/Screener.md
//
// The chat keeps the conversation's half: how the words were read, what could
// not be expressed, the first rows, and tap-to-send refinements. The whole
// table, sorting and hand edits are `SCR`.

function ScreenSummary({ raw, onChoice }: { raw: string; onChoice?: (text: string) => void }) {
  let s: ScreenPayload
  try { s = JSON.parse(raw) } catch { return null }
  const chip = { fontSize: 'var(--fs-tiny)', padding: '1px 6px', border: '1px solid var(--hairline)', borderRadius: 'var(--r-sm)' }
  const shown = Math.min(8, s.matches?.length ?? 0)

  return (
    <div className="flex flex-col" style={{ gap: 'var(--s-2)', marginTop: 'var(--s-2)' }}>
      {s.readings.length > 0 && (
        <div className="flex" style={{ gap: 4, flexWrap: 'wrap' }}>
          {s.readings.map((r, i) => (
            <span key={i} title={r.why} style={{ ...chip, color: 'var(--ink-dim)' }}>
              “{r.phrase}” → <span style={{ color: 'var(--ink)' }}>{r.as}</span>
            </span>
          ))}
        </div>
      )}
      {s.unsupported.map((u, i) => (
        <div key={i} style={{ fontSize: 'var(--fs-tiny)', color: 'var(--state-down)' }}>not expressible: {u.phrase} — {u.why}</div>
      ))}
      {shown > 0 && (
        <div style={{ overflowX: 'auto', border: '1px solid var(--hairline)', borderRadius: 'var(--r-sm)' }}>
          <ScreenTable screen={s} max={shown} />
        </div>
      )}
      {s.count !== undefined && (
        <button type="button" className="btn-ghost" style={{ alignSelf: 'flex-start', textTransform: 'none', letterSpacing: 0 }}
          onClick={() => revealPanel('screener', { title: 'Screener' })}>
          {s.count > shown ? `all ${s.count} in SCR →` : 'open in SCR →'}
        </button>
      )}
      {onChoice && s.choices.length > 0 && (
        <div className="flex" style={{ gap: 4, flexWrap: 'wrap' }}>
          {s.choices.map((c) => (
            <button key={c} type="button" className="btn-ghost" style={{ ...chip, textTransform: 'none', letterSpacing: 0 }} onClick={() => onChoice(c)}>{c}</button>
          ))}
        </div>
      )}
    </div>
  )
}
