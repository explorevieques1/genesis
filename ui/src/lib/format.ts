// Spec: Genesis Markdown/60-UI/UI Stack.md §8 Type discipline
//
// Prices and sizes arrive as strings and stay strings until formatted. Python
// uses Decimal (Conventions §Money); JSON numbers are IEEE 754 doubles, so
// parsing a price into a JS `number` silently discards that guarantee at the
// boundary. Everything here formats from the string. Nothing here computes.

/**
 * Group a decimal string for display without ever parsing it as a float.
 *
 * Accepts `undefined`. That is not defensive-programming reflex — these
 * formatters render the safety floor, which `UI Stack §6` requires to be "the
 * first thing painted and the last thing to fail". A missing field reaching
 * `.startsWith` threw, React unmounted the tree, and the whole surface went
 * black: heat, headroom, approval mode and the kill switch all gone because one
 * value was absent.
 *
 * An absent value is an em dash. The floor keeps painting.
 */
export function money(v: string | null | undefined, opts: { prefix?: string } = {}): string {
  if (v === null || v === undefined || v === '' || v === '—') return '—'
  const neg = v.startsWith('-')
  const body = neg ? v.slice(1) : v
  const [whole = '0', frac] = body.split('.')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${neg ? '-' : ''}${opts.prefix ?? ''}${grouped}${frac ? `.${frac}` : ''}`
}

/** Percentage strings are already percentages. Append the sign, do not scale. */
export const pct = (v: string | null | undefined) =>
  v === null || v === undefined || v === '' || v === '—' ? '—' : `${v}%`

export function elapsed(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60_000)
  return `${m}m${String(Math.floor((ms % 60_000) / 1000)).padStart(2, '0')}s`
}

export function ago(ms: number): string {
  if (ms < 1200) return 'now'
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`
  return `${Math.floor(ms / 3_600_000)}h ago`
}

export function clock(ts: string | number): string {
  const d = new Date(ts)
  return (
    d.toLocaleTimeString('en-GB', { hour12: false }) +
    '.' +
    String(d.getMilliseconds()).padStart(3, '0')
  )
}

/**
 * A ratio of two decimal strings, for gauge geometry only.
 *
 * This crosses into float, so it is confined to *pixel width* and is never shown
 * to the operator as a number. The displayed value is always the original string.
 */
export function gaugeFraction(
  value: string | null | undefined, limit: string | null | undefined,
): number {
  const v = Number.parseFloat(value ?? '')
  const l = Number.parseFloat(limit ?? '')
  if (!Number.isFinite(v) || !Number.isFinite(l) || l === 0) return 0
  return Math.max(0, Math.min(1, v / l))
}

/**
 * A colour with an alpha, as `rgba(...)`.
 *
 * Charting libraries parse colour strings themselves rather than handing them to
 * the browser, and most of them predate `color-mix()`. Lightweight Charts
 * throws outright — *"Failed to parse color: color-mix(in oklab, …)"* — which
 * killed the volume series and left an empty chart with no visible error.
 *
 * So CSS-level colour mixing stays in CSS, and anything destined for a canvas
 * library comes through here. Accepts `#rgb`, `#rrggbb`, or an `rgb()` string —
 * i.e. whatever `getComputedStyle` hands back for a token.
 */
export function withAlpha(color: string, alpha: number): string {
  const value = color.trim()

  if (value.startsWith('#')) {
    const hex = value.slice(1)
    const full = hex.length === 3 ? hex.split('').map((c) => c + c).join('') : hex
    const int = Number.parseInt(full.slice(0, 6), 16)
    if (!Number.isFinite(int)) return value
    return `rgba(${(int >> 16) & 255}, ${(int >> 8) & 255}, ${int & 255}, ${alpha})`
  }

  const match = value.match(/rgba?\(([^)]+)\)/)
  if (match) {
    const [r, g, b] = match[1].split(/[\s,/]+/).filter(Boolean)
    return `rgba(${r}, ${g}, ${b}, ${alpha})`
  }
  // An unrecognised format (a named colour, an oklch token) is returned
  // unchanged rather than mangled — losing the alpha beats losing the colour.
  return value
}

/**
 * Decimal places to *display* a price at.
 *
 * Inferring this from the data does not work, and it is worth saying why
 * because it is the obvious first attempt. yfinance returns float64, the
 * normalizer stores it as Decimal, and DuckDB hands the column back at full
 * scale — so AAPL's close arrives as `319.97000122`. Those trailing digits are
 * float representation noise, not quoted precision, and they do not strip as
 * trailing zeros. A max-decimals-seen rule reads that as eight significant
 * places and prints all of them.
 *
 * So this is a magnitude rule, which is what trading surfaces use in practice:
 * two places for anything priced above a dollar, more as the price gets small
 * enough for them to matter. It is a *display* decision only — the underlying
 * string keeps every digit, and `price()` slices rather than rounds, so nothing
 * is computed from the shortened form.
 */
export function pricePrecision(values: string[]): number {
  const sample = values[values.length - 1] ?? values[0] ?? ''
  const magnitude = Math.abs(Number.parseFloat(sample))
  if (!Number.isFinite(magnitude) || magnitude >= 1) return 2
  if (magnitude >= 0.01) return 4
  return 6
}

/** Format a decimal string to `places`, without ever parsing it as a float. */
export function price(value: string | null | undefined, places: number): string {
  if (value === null || value === undefined || value === '') return '—'
  const [whole, frac = ''] = value.split('.')
  if (places === 0) return whole
  return `${whole}.${frac.padEnd(places, '0').slice(0, places)}`
}
