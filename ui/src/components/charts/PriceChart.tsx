// Spec: Genesis Markdown/60-UI/UI Stack.md §5 Data surfaces · 10-Architecture/Market Data Sources.md
//
// The price chart. Lightweight Charts, because the note names it for price
// series and rules out Recharts and Chart.js explicitly.
//
// Three decisions worth stating, because each one is a place a trading chart
// usually lies:
//
// **The last bar is not extrapolated.** There is no streaming adapter wired
// (`capabilities: marketdata.realtime → false`), so the right edge of this
// chart is the last *closed* bar Genesis holds and the header says when that
// was. A chart that animates a last price it does not have is the single most
// misleading thing this surface could draw, and the temptation to add a
// pulsing dot at the right edge should be resisted permanently.
//
// **Provenance is drawn, not footnoted.** Every bar carries a `tier` from
// `Market Data Sources`, and tier 3 is vendor data that the risk engine may
// never read. A chart built from it renders with the stale hatch behind it, so
// a tier-3 series never *looks* like a tier-1 one.
//
// **Money arrives as strings and is parsed here, once, deliberately.**
// `UI Stack §8` keeps Decimal out of IEEE doubles all the way to the pixel.
// Lightweight Charts needs numbers, so this is the boundary where that
// conversion is allowed — and it is confined to the four lines that build the
// series, rather than smeared across the app.

import { useEffect, useRef } from 'react'
import {
  CandlestickSeries, HistogramSeries, LineSeries, createChart,
  type IChartApi, type ISeriesApi, type Time, type UTCTimestamp,
} from 'lightweight-charts'
import type { BarRow } from '@/api/client'
import { withAlpha } from '@/lib/format'

export interface PriceMarker {
  time: number
  position: 'aboveBar' | 'belowBar'
  color: string
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square'
  text?: string
}

export interface PriceOverlay {
  id: string
  label: string
  color: string
  /** `[time, value]`, chronological. */
  points: [number, number][]
}

interface Props {
  bars: BarRow[]
  /** Trade markers — backtest fills, level touches. */
  markers?: PriceMarker[]
  overlays?: PriceOverlay[]
  showVolume?: boolean
  /** Drawn with the stale hatch when any bar is tier 3 or worse. */
  tier?: number
  onCrosshair?: (bar: BarRow | null) => void
}

/** Genesis tokens, read once so the chart matches the surface it sits in. */
function tokens() {
  const style = getComputedStyle(document.documentElement)
  const read = (name: string, fallback: string) =>
    style.getPropertyValue(name).trim() || fallback
  return {
    ink: read('--ink', '#d6e2f0'),
    inkFaint: read('--ink-faint', '#4d6076'),
    grid: read('--hairline', '#16202e'),
    bg: read('--bg-panel', '#0a1019'),
    up: read('--verdict-pass', '#35c48a'),
    down: read('--verdict-blocked', '#ff4d5e'),
    core: read('--core', '#3d8bff'),
  }
}

export function PriceChart({
  bars, markers, overlays, showVolume = true, tier = 9, onCrosshair,
}: Props) {
  const host = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candlesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const overlayRefs = useRef<Map<string, ISeriesApi<'Line'>>>(new Map())

  // -- create once ------------------------------------------------------
  useEffect(() => {
    if (!host.current) return
    const t = tokens()
    const chart = createChart(host.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: t.inkFaint,
        fontSize: 10,
        fontFamily: getComputedStyle(document.documentElement)
          .getPropertyValue('--font-mono').trim() || 'monospace',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: t.grid },
        horzLines: { color: t.grid },
      },
      rightPriceScale: { borderColor: t.grid, scaleMargins: { top: 0.08, bottom: 0.26 } },
      timeScale: {
        borderColor: t.grid,
        // Bars are daily here; seconds would imply a precision the data does
        // not have.
        timeVisible: false,
        rightOffset: 4,
      },
      crosshair: {
        mode: 1,
        vertLine: { color: t.core, width: 1, style: 3, labelBackgroundColor: t.core },
        horzLine: { color: t.core, width: 1, style: 3, labelBackgroundColor: t.core },
      },
      handleScale: { axisPressedMouseMove: { time: true, price: false } },
      autoSize: true,
    })
    chartRef.current = chart

    candlesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: t.up, downColor: t.down,
      wickUpColor: t.up, wickDownColor: t.down,
      borderVisible: false,
      priceLineVisible: false,
    })

    if (showVolume) {
      volumeRef.current = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      })
      chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.82, bottom: 0 },
        visible: false,
      })
    }

    // Captured here so the cleanup clears the map this effect created rather
    // than whichever one happens to be current when it runs.
    const overlays = overlayRefs.current
    return () => {
      chart.remove()
      chartRef.current = null
      candlesRef.current = null
      volumeRef.current = null
      overlays.clear()
    }
  }, [showVolume])

  // -- data -------------------------------------------------------------
  useEffect(() => {
    const candles = candlesRef.current
    if (!candles) return
    const t = tokens()

    // The one place strings become numbers. See the module docstring.
    candles.setData(
      bars.map((bar) => ({
        time: bar.time as UTCTimestamp,
        open: Number(bar.open), high: Number(bar.high),
        low: Number(bar.low), close: Number(bar.close),
      })),
    )

    if (volumeRef.current) {
      volumeRef.current.setData(
        bars.map((bar) => ({
          time: bar.time as UTCTimestamp,
          value: Number(bar.volume),
          // rgba, not color-mix: Lightweight Charts parses colours itself and
          // throws on `color-mix(...)`, which silently produced an empty chart.
          color: Number(bar.close) >= Number(bar.open)
            ? withAlpha(t.up, 0.26)
            : withAlpha(t.down, 0.26),
        })),
      )
    }
    chartRef.current?.timeScale().fitContent()
  }, [bars])

  // -- markers ----------------------------------------------------------
  useEffect(() => {
    const candles = candlesRef.current
    if (!candles) return
    // v5 moved markers to a plugin; the import is dynamic so a version without
    // it degrades to a chart with no markers rather than a blank panel.
    let cancelled = false
    import('lightweight-charts')
      .then((mod) => {
        if (cancelled || !markers?.length) return
        const createSeriesMarkers = (mod as { createSeriesMarkers?: unknown })
          .createSeriesMarkers as
          | ((series: unknown, markers: unknown[]) => unknown)
          | undefined
        if (typeof createSeriesMarkers === 'function') {
          createSeriesMarkers(
            candles,
            markers.map((m) => ({ ...m, time: m.time as Time })),
          )
        }
      })
      .catch(() => {
        /* markers are an enhancement, not a requirement */
      })
    return () => { cancelled = true }
  }, [markers])

  // -- overlays ---------------------------------------------------------
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const live = overlayRefs.current

    // Remove overlays that are gone, rather than clearing and rebuilding all
    // of them -- rebuilding resets the price scale on every render.
    for (const [id, series] of live) {
      if (!overlays?.some((o) => o.id === id)) {
        chart.removeSeries(series)
        live.delete(id)
      }
    }
    for (const overlay of overlays ?? []) {
      let series = live.get(overlay.id)
      if (!series) {
        series = chart.addSeries(LineSeries, {
          color: overlay.color, lineWidth: 1,
          priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
        live.set(overlay.id, series)
      }
      series.setData(
        overlay.points.map(([time, value]) => ({ time: time as UTCTimestamp, value })),
      )
    }
  }, [overlays])

  // -- crosshair readout ------------------------------------------------
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !onCrosshair) return
    const byTime = new Map(bars.map((bar) => [bar.time, bar]))
    const handler = (param: { time?: Time }) => {
      onCrosshair(param.time ? byTime.get(param.time as number) ?? null : null)
    }
    chart.subscribeCrosshairMove(handler)
    return () => chart.unsubscribeCrosshairMove(handler)
  }, [bars, onCrosshair])

  return (
    <div
      ref={host}
      className={tier >= 3 ? 'stale-box' : undefined}
      style={{ width: '100%', height: '100%' }}
    />
  )
}
