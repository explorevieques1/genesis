// Spec: Genesis Markdown/10-Architecture/Charting Engine.md · 10-Architecture/Market Data Sources.md
//
// TradingView's Advanced Chart, embedded. The **third** charting surface, and
// the only one whose data Genesis does not hold.
//
// The other two are ours. `ChartPanel` (`CH`) draws bars out of the store and
// refuses to render a symbol we have not ingested — a deliberate constraint, and
// the right one for research and for anything an agent computed. But it is a
// time-series viewer, not a charting platform: no drawing tools, no indicator
// library, no symbol we have not paid to collect.
//
// This panel is the other half of that trade. TradingView brings its own feed,
// so any symbol on their platform charts instantly with no ingest, no adapter
// and no storage. That is exactly what makes it useful and exactly what makes
// it dangerous, so:
//
// > **Nothing here is Genesis data.** [[Market Data Sources]] puts a public
// > third-party feed at **tier 3**: research, screening and closed-market work,
// > *never* an intraday execution decision, and [[Safety Invariants]] §11 keeps
// > tier 1 as the only thing the risk engine reads. A price on this chart has
// > no provenance line, no gap detection and no reconciliation. It may not be
// > cited as a number Genesis knows.
//
// The panel says so on its face rather than in this comment, because the person
// reading a chart is not reading the source.
//
// **This is not [[genesis-tradingview-mcp]].** That server drives the *Desktop
// app* over CDP to read your paid tier-2 subscription and to put Genesis's
// [[Markup Spec]] on your real chart. This is an embedded widget with a public
// feed and no read path back. They share a vendor and nothing else.

import { useEffect, useRef, useState } from 'react'
import { Empty } from '@/components/States'
import { Chip } from '@/components/Primitives'
import { symbolLink, useWorkspace } from '@/workspace/context'

const SCRIPT_SRC =
  'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'

/**
 * MIC → TradingView exchange prefix. Deliberately short.
 *
 * [[Operating Model]] §4: *nobody knows the ticker* — resolution is a
 * deterministic lookup, and **ambiguity is surfaced, never guessed**. A wrong
 * guess here is worse than no guess: `XNYM:CL` silently charting the wrong
 * instrument is a chart the operator trusts and should not.
 *
 * So this table holds only mappings that are unambiguous, and everything else
 * falls through to the symbol box with a note saying why. Futures are
 * deliberately absent: `FUT:CME:ES:2025-12` is one dated contract and
 * TradingView's `ES1!` is a continuous series — a different price series, which
 * is the whole reason `normalize.py` refuses to conflate them.
 */
const EXCHANGE: Record<string, string> = {
  XNAS: 'NASDAQ',
  XNYS: 'NYSE',
  BATS: 'BATS',
  XCBO: 'CBOE',
}

/** Genesis timeframe → TradingView interval. */
const INTERVAL: Record<string, string> = {
  '1m': '1', '5m': '5', '15m': '15', '30m': '30',
  '1h': '60', '4h': '240',
  '1D': 'D', '1W': 'W', '1M': 'M',
}

/**
 * A canonical symbol id, as TradingView spells it — or why it cannot be.
 *
 * Returns the reason rather than a best effort, so the panel can say
 * *"no TradingView mapping for FUT:CME:ES:2025-12"* instead of charting
 * something plausible and wrong.
 */
export function toTradingViewSymbol(
  symbolId: string,
): { symbol: string } | { reason: string } {
  const parts = symbolId.split(':')
  const [assetClass, exchange, root] = parts
  if (assetClass !== 'EQ' || parts.length !== 3) {
    return {
      reason: `${symbolId} is not an equity — only EQ ids map cleanly, and a `
        + `dated future is not TradingView's continuous series`,
    }
  }
  const prefix = EXCHANGE[exchange]
  if (!prefix) return { reason: `no TradingView exchange known for ${exchange}` }
  return { symbol: `${prefix}:${root}` }
}

export function TradingViewPanel() {
  const { symbolId, timeframe, tvSymbol, select } = useWorkspace()

  // What the widget is actually showing. Seeded from the workspace selection
  // when that maps, and typeable regardless — the point of this panel is
  // reaching symbols Genesis does not hold, so a symbol box here is the
  // feature, where on `CH` it would be a lie.
  const [symbol, setSymbol] = useState('NASDAQ:AAPL')
  const [draft, setDraft] = useState('')
  const [failed, setFailed] = useState<string | null>(null)
  const host = useRef<HTMLDivElement>(null)

  // Follow the workspace selection when it maps, and only then. An unmappable
  // selection leaves the chart where it is rather than blanking it.
  //
  // `tvSymbol` wins: the watchlist sets it deliberately, in TradingView's own
  // spelling, precisely for symbols Genesis holds no bars for — so it is
  // passed straight through with no mapping.
  useEffect(() => {
    if (tvSymbol) {
      setSymbol(tvSymbol.trim().toUpperCase())
      return
    }
    if (!symbolId) return
    const resolved = toTradingViewSymbol(symbolId)
    if ('symbol' in resolved) setSymbol(resolved.symbol)
  }, [tvSymbol, symbolId])

  useEffect(() => {
    const container = host.current
    if (!container) return
    setFailed(null)
    container.innerHTML = ''

    const widget = document.createElement('div')
    widget.style.height = '100%'
    container.appendChild(widget)

    const script = document.createElement('script')
    script.src = SCRIPT_SRC
    script.async = true
    // The embed reads its configuration from the script tag's own text node.
    // Unusual, and theirs.
    script.text = JSON.stringify({
      symbol,
      interval: INTERVAL[timeframe] ?? 'D',
      autosize: true,
      timezone: 'Etc/UTC',
      // The shell writes the theme onto the root element; the widget is an
      // iframe and cannot see our tokens, so it gets told which one it is.
      theme: document.documentElement.dataset.theme === 'light' ? 'light' : 'dark',
      style: '1',
      allow_symbol_change: true,
      support_host: 'https://www.tradingview.com',
    })
    script.onerror = () => setFailed('the TradingView embed script did not load')
    widget.appendChild(script)

    // **Proprioception before ambition** — Biological Design §3. An actuator
    // needs a sense that verifies it acted. `onerror` does not fire when a
    // proxy returns a 200 with junk, or when the script loads and the iframe
    // is then blocked, so the check is for the iframe itself. Without this the
    // panel is a grey rectangle that claims nothing is wrong.
    const check = window.setTimeout(() => {
      if (!widget.querySelector('iframe')) {
        setFailed('the chart did not appear — no network, or the embed is blocked')
      }
    }, 8000)

    return () => {
      window.clearTimeout(check)
      container.innerHTML = ''
    }
  }, [symbol, timeframe])

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    const next = draft.trim().toUpperCase()
    if (!next) return
    // Publish, don't just show: the effect above follows `tvSymbol`, and so
    // does every other linked panel.
    select(symbolLink(next))
    setDraft('')
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      <div
        className="flex items-baseline gap-3 hairline-b"
        style={{ padding: '4px 8px', flexShrink: 0 }}
      >
        <span style={{ fontSize: 'var(--fs-base)', fontWeight: 600 }}>{symbol}</span>
        <form onSubmit={submit} style={{ display: 'flex' }}>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="NYSE:GME"
            spellCheck={false}
            style={{
              background: 'var(--bg-inset)', border: '1px solid var(--hairline)',
              borderRadius: 'var(--r-sm)', color: 'var(--ink)',
              fontSize: 'var(--fs-tiny)', padding: '1px var(--s-3)',
              width: 110, outline: 'none',
            }}
          />
        </form>
        <span style={{ flex: 1 }} />
        {/* Tier 3, stated on the chart itself. A person reading a price is not
            reading the file header, and this is the one panel on the surface
            showing numbers Genesis did not collect and cannot vouch for. */}
        <Chip
          tone="warn"
          title="Market Data Sources — a public third-party feed. Research and
                 closed-market work only; never a source for sizing, stops or
                 any number Genesis reports as its own."
        >
          tier 3 · TradingView's feed, not Genesis data
        </Chip>
      </div>

      <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        {failed && (
          <div
            style={{
              position: 'absolute', inset: 0, zIndex: 1,
              background: 'var(--bg-panel)',
            }}
          >
            <Empty hint="This panel is the one thing on the surface that needs the
                         public internet. Every other chart reads bars on disk.">
              {failed}
            </Empty>
          </div>
        )}
        <div ref={host} style={{ height: '100%' }} />
      </div>

      {symbolId && 'reason' in toTradingViewSymbol(symbolId) && (
        <div
          className="hairline-t label"
          style={{
            padding: '2px 8px', flexShrink: 0, color: 'var(--ink-ghost)',
            textTransform: 'none', letterSpacing: 0,
          }}
        >
          not following the workspace selection —{' '}
          {(toTradingViewSymbol(symbolId) as { reason: string }).reason}
        </div>
      )}
    </div>
  )
}

/**
 * The mapping is the part that can be silently wrong, so it is the part that
 * gets checked. Runs at load; a bad table fails on the next page open rather
 * than the next time somebody charts a future.
 */
if (import.meta.env.DEV) {
  const cases: [string, string | null][] = [
    ['EQ:XNAS:AAPL', 'NASDAQ:AAPL'],
    ['EQ:XNYS:GME', 'NYSE:GME'],
    ['EQ:XLON:VOD', null],          // unknown exchange -- surfaced, not guessed
    ['FUT:CME:ES:2025-12', null],   // dated contract is not ES1!
    ['IDX:CBOE:VIX', null],         // not an equity
  ]
  for (const [input, want] of cases) {
    const got = toTradingViewSymbol(input)
    const actual = 'symbol' in got ? got.symbol : null
    if (actual !== want) {
      throw new Error(`toTradingViewSymbol(${input}) = ${actual}, want ${want}`)
    }
  }
}
