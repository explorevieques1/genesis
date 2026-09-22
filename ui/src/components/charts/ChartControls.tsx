// Spec: Genesis Markdown/60-UI/Chart Tools.md
//
// The chart's own chrome: the drawing tools in the middle of the banner, the
// settings gear at its right end.
//
// Icons are inline SVG rather than a dependency. Nine glyphs of four path
// commands each do not justify an icon package, and a drawing tool whose button
// is a picture of the shape it draws needs no label.
//
// Every control here is a *view* control. Nothing in this file changes data,
// which is why the settings live in `localStorage` and the drawings do not.

import { useEffect, useRef } from 'react'
import { TOOLS, DEFAULT_SETTINGS, type ChartSettings, type ToolId } from './drawings'

// ---------------------------------------------------------------------------
// the toolbar
// ---------------------------------------------------------------------------

const ICONS: Record<ToolId, JSX.Element> = {
  none: <path d="M3 2l8 6-3.4.6L9.4 12 8 12.7 6.2 9.6 3.7 11z" fill="currentColor" stroke="none" />,
  level: <path d="M1.5 8h11" />,
  line: <path d="M2 11.5L12 3" />,
  zone: <rect x="2" y="4" width="10" height="7" />,
  fib: <path d="M2 3h10M2 6h10M2 9h10M2 12h10" strokeOpacity="0.75" />,
  long: <><rect x="3" y="7" width="8" height="5" /><path d="M7 6.5V2m0 0L5 4m2-2l2 2" /></>,
  short: <><rect x="3" y="2" width="8" height="5" /><path d="M7 7.5V12m0 0l-2-2m2 2l2-2" /></>,
  marker: <path d="M7 2.5l3.5 6h-7z" fill="currentColor" />,
  text: <path d="M3 3.5h8M7 3.5v8" />,
  trade_plan: <rect x="2" y="4" width="10" height="7" />,
}

function Glyph({ tool }: { tool: ToolId }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none"
      stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
      {ICONS[tool]}
    </svg>
  )
}

interface ToolbarProps {
  tool: ToolId
  onPick: (tool: ToolId) => void
  canDelete: boolean
  onDelete: () => void
  count: number
  onClear: () => void
  /** A zone is selected: it has the two time anchors a mark is made of. */
  canJournal: boolean
  onJournal: () => void
}

export function ChartToolbar({
  tool, onPick, canDelete, onDelete, count, onClear, canJournal, onJournal,
}: ToolbarProps) {
  return (
    <div className="flex items-center gap-0.5" style={{ flexShrink: 0 }}>
      {TOOLS.map((t) => (
        <button
          key={t.id}
          className="btn-ghost"
          data-active={tool === t.id}
          title={`${t.title} — ${t.hint}`}
          aria-label={t.title}
          aria-pressed={tool === t.id}
          style={{ padding: '2px 4px', lineHeight: 1 }}
          // A tool already out is turned off by pressing it again, which is
          // the same gesture as Escape and the one people reach for first.
          onClick={() => onPick(tool === t.id ? 'none' : t.id)}
        >
          <Glyph tool={t.id} />
        </button>
      ))}

      <span style={{ width: 1, height: 12, background: 'var(--hairline)', margin: '0 3px' }} />

      <button
        className="btn-ghost" title="delete the selected drawing (Del)"
        disabled={!canDelete} onClick={onDelete}
        style={{ padding: '2px 4px', lineHeight: 1, opacity: canDelete ? 1 : 0.35 }}
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.2">
          <path d="M2.5 4h9M5.5 4V2.5h3V4M4 4l.6 8h4.8L10 4" strokeLinecap="round" />
        </svg>
      </button>
      {/* Draw a zone over the bars, then say what it was: an entry, an exit,
          or an idea you did not take. The journal's only hand-authored door. */}
      <button
        className="btn-ghost"
        title={canJournal
          ? 'journal this range of candles — entry, exit or idea'
          : 'select a zone drawn over the bars to journal it'}
        disabled={!canJournal} onClick={onJournal}
        style={{ opacity: canJournal ? 1 : 0.35 }}
      >
        journal
      </button>
      {/* Destructive and irreversible, so it says how many it will take. */}
      <button
        className="btn-ghost" title={`clear all ${count} drawings on this series`}
        disabled={!count}
        onClick={() => {
          if (count && confirm(`Delete all ${count} drawings on this chart?`)) onClear()
        }}
        style={{ opacity: count ? 1 : 0.35 }}
      >
        clear
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// the settings menu
// ---------------------------------------------------------------------------

/** The theme's own candle colours, so the pickers open on what is on screen. */
function themeColour(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  // `<input type=color>` speaks hex and nothing else; a token that is not hex
  // (a colour function, say) falls back rather than rendering black.
  return /^#[0-9a-f]{6}$/i.test(value) ? value : fallback
}

interface MenuProps {
  settings: ChartSettings
  onChange: (settings: ChartSettings) => void
  onClose: () => void
}

export function ChartSettingsMenu({ settings, onChange, onClose }: MenuProps) {
  const card = useRef<HTMLDivElement>(null)

  // Click-away and Escape. A popover that can only be closed by finding the
  // gear again is a popover people leave open over their chart.
  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (card.current && !card.current.contains(e.target as Node)) onClose()
    }
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    // Deferred a tick: the click that opened this must not immediately close it.
    const timer = setTimeout(() => document.addEventListener('mousedown', away), 0)
    document.addEventListener('keydown', key)
    return () => {
      clearTimeout(timer)
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', key)
    }
  }, [onClose])

  const set = <K extends keyof ChartSettings>(key: K, value: ChartSettings[K]) =>
    onChange({ ...settings, [key]: value })

  const up = settings.up || themeColour('--verdict-pass', '#35c48a')
  const down = settings.down || themeColour('--verdict-blocked', '#ff4d5e')

  return (
    <div
      ref={card}
      className="flex flex-col gap-1"
      style={{
        position: 'absolute', top: 26, right: 6, zIndex: 20, width: 208,
        padding: '8px 9px', borderRadius: 'var(--r-sm)',
        background: 'var(--bg-panel)', border: '1px solid var(--hairline-bright)',
        boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
      }}
    >
      <div className="label" style={{ color: 'var(--ink-ghost)' }}>chart</div>
      <Toggle label="grid lines" on={settings.grid} onToggle={(v) => set('grid', v)} />
      <Toggle label="volume" on={settings.volume} onToggle={(v) => set('volume', v)} />
      <Toggle label="crosshair" on={settings.crosshair} onToggle={(v) => set('crosshair', v)} />
      <Toggle label="clock on time axis" on={settings.timeVisible} onToggle={(v) => set('timeVisible', v)} />

      <div className="label" style={{ color: 'var(--ink-ghost)', marginTop: 4 }}>candles</div>
      <Toggle label="wicks" on={settings.wicks} onToggle={(v) => set('wicks', v)} />
      <Toggle label="hollow up bars" on={settings.hollow} onToggle={(v) => set('hollow', v)} />
      <div className="flex items-center gap-2">
        <Swatch label="up" value={up} onPick={(v) => set('up', v)} />
        <Swatch label="down" value={down} onPick={(v) => set('down', v)} />
      </div>

      <div className="label" style={{ color: 'var(--ink-ghost)', marginTop: 4 }}>price axis</div>
      <select
        className="field"
        value={settings.scale}
        onChange={(e) => set('scale', e.target.value as ChartSettings['scale'])}
      >
        <option value="normal">linear</option>
        <option value="logarithmic">logarithmic</option>
        <option value="percentage">percent</option>
      </select>
      <div className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}>
        drag the price axis to stretch it · double-click it to re-fit
      </div>

      <button
        className="btn-ghost"
        style={{ alignSelf: 'flex-start', marginTop: 4 }}
        onClick={() => onChange(DEFAULT_SETTINGS)}
      >
        reset
      </button>
    </div>
  )
}

function Toggle({
  label, on, onToggle,
}: { label: string; on: boolean; onToggle: (on: boolean) => void }) {
  return (
    <label className="flex items-center gap-2" style={{ fontSize: 'var(--fs-sm)', cursor: 'pointer' }}>
      <input type="checkbox" checked={on} onChange={(e) => onToggle(e.target.checked)} />
      <span style={{ color: 'var(--ink-dim)' }}>{label}</span>
    </label>
  )
}

function Swatch({
  label, value, onPick,
}: { label: string; value: string; onPick: (value: string) => void }) {
  return (
    <label className="flex items-center gap-1" style={{ fontSize: 'var(--fs-sm)', cursor: 'pointer' }}>
      <input
        type="color" value={value}
        onChange={(e) => onPick(e.target.value)}
        style={{ width: 22, height: 16, padding: 0, border: '1px solid var(--hairline)', background: 'none' }}
      />
      <span style={{ color: 'var(--ink-dim)' }}>{label}</span>
    </label>
  )
}
