// Spec: Genesis Markdown/10-Architecture/Web Access.md §The presentation surface
//
// The web, in a dock panel. A real Chromium runs beside the daemon with its own
// profile; this shows its viewport and sends your clicks and keys back.
//
// **Why not an iframe.** Because the half of the web worth opening refuses to
// be framed — `X-Frame-Options` and `frame-ancestors` are on TradingView,
// Google, X and every broker portal, and a panel that renders a blank box for
// all of them is not a browser. The pixels come from a browser the daemon owns
// instead, which also means a persistent profile: log into your subscription
// once and it is still logged in tomorrow.
//
// **The stream is one `<img>`.** `multipart/x-mixed-replace` is a native
// browser feature and it carries the whole video path — no decode loop, no
// frame buffer, no reconnect. Changing the query string is how it restarts,
// which is why a resize re-keys the element rather than messaging anything.
//
// **The viewport is the panel.** `?w=&h=` sets the remote viewport to the size
// this element renders at, so the image is 1:1 and a click at (x, y) here is a
// click at (x, y) there. Scale them and every coordinate is wrong in a way that
// looks like a browser ignoring you.
//
// **Nothing on this surface is Genesis data.** It is a web page. Nothing it
// shows has provenance, and a number read off it is a number you read on the
// internet — same standing as reading it on your phone, which is the honest
// framing and the reason this needs no tier badge of its own.

import { useCallback, useEffect, useRef, useState } from 'react'
import { HTTP, get, post } from '@/api/client'
import { Absent, Loading } from '@/components/States'

interface BrowserState {
  url: string
  title: string
  can_back: boolean
  can_forward: boolean
  headless: boolean
}

/** Keys the remote side has a virtual key code for. Everything else is text. */
const NAV_KEYS = new Set([
  'Enter', 'Backspace', 'Tab', 'Escape', 'Delete',
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'Home', 'End', 'PageUp', 'PageDown',
])

/** CDP's modifier bitmask. Alt 1, Ctrl 2, Meta 4, Shift 8. */
function modifiers(e: { altKey: boolean; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean }) {
  return (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0)
}

const BUTTONS = ['left', 'middle', 'right'] as const

/**
 * Mouse moves at 60 Hz would be sixty POSTs a second and the CDP socket is
 * serialised with the frame capture, so they would starve it. Hover still
 * works — menus open, links highlight — just at a rate a person cannot see.
 */
const MOVE_INTERVAL_MS = 60

export function BrowserPanel() {
  const observer = useRef<ResizeObserver | null>(null)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const [state, setState] = useState<BrowserState | null>(null)
  const [reason, setReason] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const lastMove = useRef(0)
  const down = useRef(false)

  // Fire-and-forget. An input event that failed is worth a line in the console
  // and nothing on screen: the next frame already shows whether it landed,
  // which is the proprioception the panel has for free.
  const input = useCallback((body: Record<string, unknown>) => {
    post('/v1/browser/input', body).catch(() => {})
  }, [])

  const refresh = useCallback(async () => {
    try {
      const body = await get<BrowserState>('/v1/browser/state')
      if (body.available) {
        setState(body)
        setReason(null)
      } else {
        setReason(body.reason)
      }
    } catch (err) {
      setReason(err instanceof Error ? err.message : String(err))
    }
  }, [])

  // The panel's size is the remote viewport's size, so it is measured rather
  // than assumed. Rounded to 8px because a drag-resize would otherwise restart
  // the stream on every pixel, and each restart costs a fresh CDP round trip.
  //
  // **A callback ref, not an effect.** This element does not exist on the first
  // render — the panel is showing `Loading` until the first state read returns,
  // so a `useEffect` with `[]` deps runs against a null ref, returns early and
  // never runs again. The symptom is a panel with a toolbar, a footer and a
  // black hole where the web should be, which looks like a broken stream and is
  // not. A callback ref fires when the node appears, which is the point of one.
  const host = useCallback((element: HTMLDivElement | null) => {
    observer.current?.disconnect()
    observer.current = null
    if (!element) return
    const next = new ResizeObserver(([entry]) => {
      const w = Math.max(320, Math.round(entry.contentRect.width / 8) * 8)
      const h = Math.max(240, Math.round(entry.contentRect.height / 8) * 8)
      setSize((prev) => (prev?.w === w && prev?.h === h ? prev : { w, h }))
    })
    next.observe(element)
    observer.current = next
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  // The URL bar follows the page, except while you are typing in it.
  const [editing, setEditing] = useState(false)
  useEffect(() => {
    if (!editing && state) setDraft(state.url === 'about:blank' ? '' : state.url)
  }, [state, editing])

  const navigate = useCallback(async (body: Record<string, unknown>) => {
    try {
      await post<{ ok: boolean; url: string }>('/v1/browser/navigate', body)
      setReason(null)
      // The navigate route answers before the page is the page — for the few
      // hundred ms a navigation is in flight the remote side cannot even say
      // what its history is. So the URL bar and the back/forward buttons come
      // from a read afterwards, twice: once for the request, once for wherever
      // the redirects ended up.
      window.setTimeout(() => void refresh(), 400)
      window.setTimeout(() => void refresh(), 2000)
    } catch (err) {
      setReason(err instanceof Error ? err.message : String(err))
    }
  }, [refresh])

  const onKey = (e: React.KeyboardEvent) => {
    // Every key here belongs to the page, not to the shell. Without this the
    // command bar answers `/`, the dock answers arrows, and the browser is a
    // surface you cannot type a slash into.
    if (e.ctrlKey || e.metaKey) {
      if (e.key === 'v' || e.key === 'c' || e.key === 'x') return  // let the clipboard work
    }
    if (NAV_KEYS.has(e.key)) {
      e.preventDefault()
      e.stopPropagation()
      input({ kind: 'key', name: e.key, modifiers: modifiers(e) })
      return
    }
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
      e.preventDefault()
      e.stopPropagation()
      input({ kind: 'text', value: e.key })
    }
  }

  const point = (e: React.MouseEvent) => {
    const box = (e.currentTarget as HTMLElement).getBoundingClientRect()
    return { x: e.clientX - box.left, y: e.clientY - box.top }
  }

  if (reason) return <Absent reason={reason} onRetry={() => void refresh()} />
  if (!state) return <Loading label="starting the browser" />

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 hairline-b" style={{ padding: '4px 8px', flexShrink: 0 }}>
        <Button onClick={() => void navigate({ action: 'back' })} disabled={!state.can_back} title="Back">←</Button>
        <Button onClick={() => void navigate({ action: 'forward' })} disabled={!state.can_forward} title="Forward">→</Button>
        <Button onClick={() => void navigate({ action: 'reload' })} title="Reload">↻</Button>
        <form
          style={{ flex: 1, display: 'flex' }}
          onSubmit={(e) => { e.preventDefault(); setEditing(false); void navigate({ url: draft }) }}
        >
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onFocus={() => setEditing(true)}
            onBlur={() => setEditing(false)}
            onKeyDown={(e) => e.stopPropagation()}
            placeholder="address, or anything else to search"
            spellCheck={false}
            style={{
              background: 'var(--bg-inset)', border: '1px solid var(--hairline)',
              borderRadius: 'var(--r-sm)', color: 'var(--ink)',
              fontSize: 'var(--fs-tiny)', padding: '1px var(--s-3)',
              width: '100%', outline: 'none',
            }}
          />
        </form>
        {/* [[Web Access]]: the external browser is the right answer for a page
            you want to keep after closing Genesis. Explicit, never default. */}
        <Button onClick={() => window.open(state.url, '_blank', 'noopener')} title="Open in your own browser">
          ↗
        </Button>
      </div>

      <div
        ref={host}
        tabIndex={0}
        onKeyDown={onKey}
        onPaste={(e) => {
          const text = e.clipboardData.getData('text')
          if (text) { e.preventDefault(); input({ kind: 'text', value: text }) }
        }}
        style={{ flex: 1, minHeight: 0, outline: 'none', background: 'var(--bg-inset)', overflow: 'hidden' }}
      >
        {size && (
          <img
            // The query string is the stream's identity: change the size and
            // this is a different element with a different connection, which
            // is how the remote viewport is resized without a second route.
            key={`${size.w}x${size.h}`}
            src={`${HTTP}/v1/browser/stream?w=${size.w}&h=${size.h}`}
            width={size.w}
            height={size.h}
            draggable={false}
            alt=""
            style={{ display: 'block', width: size.w, height: size.h, cursor: 'default' }}
            onMouseDown={(e) => {
              e.preventDefault()
              ;(e.currentTarget.parentElement as HTMLElement).focus()
              down.current = true
              const { x, y } = point(e)
              input({ kind: 'down', x, y, button: BUTTONS[e.button] ?? 'left', clicks: e.detail || 1, modifiers: modifiers(e) })
            }}
            onMouseUp={(e) => {
              down.current = false
              const { x, y } = point(e)
              input({ kind: 'up', x, y, button: BUTTONS[e.button] ?? 'left', clicks: e.detail || 1, modifiers: modifiers(e) })
            }}
            onMouseMove={(e) => {
              const now = Date.now()
              // A drag is a selection or a chart tool and every skipped move
              // is a kink in the line, so it is throttled less hard than hover.
              if (now - lastMove.current < (down.current ? MOVE_INTERVAL_MS / 2 : MOVE_INTERVAL_MS)) return
              lastMove.current = now
              const { x, y } = point(e)
              input({ kind: 'move', x, y, modifiers: modifiers(e) })
            }}
            onWheel={(e) => {
              const { x, y } = point(e)
              input({ kind: 'wheel', x, y, dx: e.deltaX, dy: e.deltaY, modifiers: modifiers(e) })
            }}
            onContextMenu={(e) => e.preventDefault()}
            onError={() => setReason('the frame stream stopped — the browser may have exited')}
          />
        )}
      </div>

      <div
        className="hairline-t label"
        style={{ padding: '2px 8px', flexShrink: 0, color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}
      >
        {state.headless ? 'headless' : 'windowed'} · a streamed browser, not Genesis data · its profile keeps your logins
      </div>
    </div>
  )
}

function Button({ children, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...rest}
      style={{
        background: 'var(--bg-inset)', border: '1px solid var(--hairline)',
        borderRadius: 'var(--r-sm)', color: rest.disabled ? 'var(--ink-ghost)' : 'var(--ink)',
        fontSize: 'var(--fs-tiny)', padding: '0 6px', lineHeight: '18px',
        cursor: rest.disabled ? 'default' : 'pointer', flexShrink: 0,
      }}
    >
      {children}
    </button>
  )
}
