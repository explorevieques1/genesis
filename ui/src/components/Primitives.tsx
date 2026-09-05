// Spec: Genesis Markdown/60-UI/UI Stack.md §4 Chrome · 60-UI/Genesis Core.md
//
// The handful of shapes every panel is built from.
//
// `UI Stack §4` rules out a pre-styled component kit — live mode and stale data
// are whole-surface states that a themed kit fights — so these are defined once
// on Genesis tokens and reused. They are small on purpose: a primitives file
// that grows past a screen has stopped being primitives.
//
// The rule they all obey, from `Genesis Core`: **"Numbers are tabular and
// readable, or they are not shown."** Every figure below is monospaced and
// tabular-aligned, and a missing value renders as an em dash rather than as
// `0`, `—`, `N/A` or the empty string. A zero and an absence are different
// facts and the second one must never be able to masquerade as the first.

import type { ReactNode } from 'react'
import { stagger } from '@/lib/motion'

/** The em dash every absent value renders as. One place, so it is consistent. */
export const NONE = '—'

/**
 * A number, formatted, or the em dash.
 *
 * Takes `string | number | null`. Strings pass through untouched — that is the
 * money path (`UI Stack §8`), and reformatting a Decimal string would undo the
 * precision it was kept as a string to preserve.
 */
export function Num({
  value,
  digits = 2,
  suffix,
  signed = false,
  tone = false,
  className = '',
}: {
  value: string | number | null | undefined
  digits?: number
  suffix?: string
  /** Show a leading `+` for positives. For P&L and returns. */
  signed?: boolean
  /** Colour by sign. Only where the sign is the point. */
  tone?: boolean
  className?: string
}) {
  if (value === null || value === undefined || value === '') {
    return <span className={`num ${className}`} style={{ color: 'var(--ink-ghost)' }}>{NONE}</span>
  }

  const numeric = typeof value === 'number' ? value : Number(value)
  const text =
    typeof value === 'string' && !Number.isFinite(numeric)
      ? value
      : Number.isFinite(numeric)
        ? `${signed && numeric > 0 ? '+' : ''}${numeric.toLocaleString(undefined, {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
          })}`
        : NONE

  const colour = !tone || !Number.isFinite(numeric)
    ? undefined
    : numeric > 0 ? 'var(--verdict-pass)'
      : numeric < 0 ? 'var(--verdict-blocked)'
        : 'var(--ink-dim)'

  return (
    <span className={`num ${className}`} style={{ color: colour }}>
      {text}{suffix && <span style={{ color: 'var(--ink-faint)' }}>{suffix}</span>}
    </span>
  )
}

/**
 * One figure with its name. The unit of a statistics panel.
 *
 * `hint` exists because a statistic without its caveat is a statistic that
 * will be over-read — "Sharpe Ratio (252 days)" over eleven trades is a number
 * with no meaning, and the tile should be able to say so beside it.
 */
export function Metric({
  label, value, digits = 2, suffix, signed, tone, hint, wide,
}: {
  label: string
  value: string | number | null | undefined
  digits?: number
  suffix?: string
  signed?: boolean
  tone?: boolean
  hint?: string
  wide?: boolean
}) {
  return (
    <div
      className="flex flex-col gap-0.5"
      style={{
        padding: '6px 8px',
        background: 'var(--bg-raised)',
        border: '1px solid var(--hairline)',
        borderRadius: 'var(--r-sm)',
        minWidth: wide ? 128 : 92,
      }}
      title={hint}
    >
      <div className="label" style={{ letterSpacing: '0.1em' }}>{label}</div>
      <div style={{ fontSize: 'var(--fs-lg)', lineHeight: 1.15 }}>
        <Num value={value} digits={digits} suffix={suffix} signed={signed} tone={tone} />
      </div>
      {hint && (
        <div className="label" style={{ color: 'var(--ink-ghost)', textTransform: 'none', letterSpacing: 0 }}>
          {hint}
        </div>
      )}
    </div>
  )
}

/** A titled region inside a panel. */
export function Section({
  title, children, actions, dense,
}: {
  title: string
  children: ReactNode
  actions?: ReactNode
  dense?: boolean
}) {
  return (
    // `flexShrink: 0` matters: inside a scrolling column, a section allowed to
    // shrink collapses to less than its content and the header lands on top of
    // the first row. The scroll container is the thing that should give, not
    // the sections in it.
    <section
      className="flex flex-col"
      style={{ gap: dense ? 4 : 6, flexShrink: 0 }}
    >
      <header className="flex items-center gap-2" style={{ paddingBottom: 2 }}>
        <span className="label">{title}</span>
        <span style={{ flex: 1, height: 1, background: 'var(--hairline)' }} />
        {actions}
      </header>
      {children}
    </section>
  )
}

export interface Column<T> {
  key: string
  header: string
  /** Right-align numbers, left-align text. Nothing centres. */
  align?: 'left' | 'right'
  width?: number
  render: (row: T) => ReactNode
}

/**
 * A dense table with a staggered arrival.
 *
 * The stagger is capped in `lib/motion.ts` — an uncapped one means the sixtieth
 * row appears two seconds after the first, and the operator is waiting on data
 * that is already in the browser.
 */
export function Table<T>({
  rows, columns, keyOf, onSelect, selectedKey, empty,
}: {
  rows: T[]
  columns: Column<T>[]
  keyOf: (row: T, index: number) => string
  onSelect?: (row: T) => void
  selectedKey?: string | null
  empty?: ReactNode
}) {
  if (!rows.length) return <>{empty ?? null}</>

  return (
    <div className="scroll-y" style={{ flex: 1 }}>
      <table
        style={{
          width: '100%', borderCollapse: 'collapse',
          fontSize: 'var(--fs-tiny)', tableLayout: 'fixed',
        }}
      >
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                className="label"
                style={{
                  textAlign: column.align ?? 'left',
                  padding: '3px 6px',
                  width: column.width,
                  position: 'sticky', top: 0, zIndex: 1,
                  background: 'var(--bg-panel)',
                  borderBottom: '1px solid var(--hairline)',
                  fontWeight: 500,
                }}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const key = keyOf(row, index)
            return (
              <tr
                key={key}
                className="row-hit lift"
                data-selected={selectedKey === key}
                style={{ ['--i' as string]: stagger(index), cursor: onSelect ? 'pointer' : 'default' }}
                onClick={onSelect ? () => onSelect(row) : undefined}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    style={{
                      textAlign: column.align ?? 'left',
                      padding: '3px 6px',
                      borderBottom: '1px solid var(--bg-raised)',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/**
 * A caveat attached to data. Rendered as prose, not an icon.
 *
 * Backtest warnings, staleness notices and tier flags all land here. They are
 * deliberately verbose: *"2 closed positions is below the threshold at which
 * these statistics are conclusive"* is longer than a ⚠ and is the only version
 * that actually changes what a person concludes.
 */
export function Caveats({ items, tone = 'warn' }: { items: string[]; tone?: 'warn' | 'info' }) {
  if (!items.length) return null
  const colour = tone === 'warn' ? 'var(--state-blocked)' : 'var(--ink-faint)'
  return (
    <ul
      className="flex flex-col gap-1"
      style={{ listStyle: 'none', margin: 0, padding: '6px 8px',
        background: 'var(--bg-inset)', border: `1px solid var(--hairline)`,
        borderLeft: `2px solid ${colour}`, borderRadius: 'var(--r-sm)' }}
    >
      {items.map((item, index) => (
        <li
          key={index}
          className="lift"
          style={{ ['--i' as string]: stagger(index, 40),
            fontSize: 'var(--fs-tiny)', color: 'var(--ink-dim)', lineHeight: 1.5 }}
        >
          {item}
        </li>
      ))}
    </ul>
  )
}

/** A small labelled pill. Used for tier, source, status. */
export function Chip({
  children, tone = 'neutral', title,
}: {
  children: ReactNode
  tone?: 'neutral' | 'good' | 'warn' | 'bad' | 'spinal' | 'core'
  title?: string
}) {
  const colours: Record<string, string> = {
    neutral: 'var(--ink-faint)',
    good: 'var(--verdict-pass)',
    warn: 'var(--state-blocked)',
    bad: 'var(--state-down)',
    spinal: 'var(--spinal)',
    core: 'var(--core)',
  }
  const colour = colours[tone]
  return (
    <span
      title={title}
      className="label"
      style={{
        color: colour,
        border: `1px solid color-mix(in oklab, ${colour} 34%, transparent)`,
        background: `color-mix(in oklab, ${colour} 10%, transparent)`,
        borderRadius: 'var(--r-sm)',
        padding: '1px 5px',
        letterSpacing: '0.1em',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  )
}

/** The panel's own scroll container, with consistent padding. */
export function PanelBody({ children, pad = 8 }: { children: ReactNode; pad?: number }) {
  return (
    <div className="flex flex-col h-full min-h-0 scroll-y" style={{ padding: pad, gap: 8 }}>
      {children}
    </div>
  )
}
