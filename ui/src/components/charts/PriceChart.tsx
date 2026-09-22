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

import { useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries, HistogramSeries, LineSeries, LineStyle, PriceScaleMode, createChart,
  type IChartApi, type IPriceLine, type ISeriesApi, type Time, type UTCTimestamp,
} from 'lightweight-charts'
import type { BarRow } from '@/api/client'
import { withAlpha } from '@/lib/format'
import { DrawingLayer } from './DrawingLayer'
import {
  DEFAULT_SETTINGS,
  type ChartSettings, type Drawing, type NewDrawing, type ToolId,
} from './drawings'

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

/** A horizontal line at a price — working orders and the position's entry. */
export interface PriceLine {
  id: string
  /** A string, like every price: parsed here, at the chart boundary. */
  price: string
  color: string
  title: string
  style?: 'solid' | 'dashed' | 'dotted'
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
  /** Appearance. Omitted, the chart looks the way it always did. */
  settings?: ChartSettings
  /** The trader's own marks. Omitted, there is no drawing surface at all. */
  drawings?: Drawing[]
  tool?: ToolId
  selectedId?: string | null
  /** Decimal places for the labels a drawing prints. */
  places?: number
  onSelect?: (id: string | null) => void
  onDelete?: (id: string) => void
  onCommit?: (drawing: NewDrawing) => void
  /** A drawing whose handle was dragged — same id, new geometry. */
  onUpdate?: (drawing: Drawing) => void
  onToolDone?: () => void
  /**
   * The newest bar from the live feed — forming or just closed. Applied with
   * `update()`, not `setData()`, so a tick never resets the trader's zoom.
   */
  live?: BarRow | null
  /** Orders and positions from the order path. Omitted, none are drawn. */
  priceLines?: PriceLine[]
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
  settings = DEFAULT_SETTINGS, drawings, tool = 'none', selectedId = null,
  places = 2, onSelect, onDelete, onCommit, onUpdate, onToolDone, live, priceLines,
}: Props) {
  const host = useRef<HTMLDivElement>(null)
  // Bumped once the chart exists, so the drawing layer mounts with real APIs
  // rather than nulls it has to guard on every render.
  const [ready, setReady] = useState(0)
  const chartRef = useRef<IChartApi | null>(null)
  const candlesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const overlayRefs = useRef<Map<string, ISeriesApi<'Line'>>>(new Map())
  const lineRefs = useRef<IPriceLine[]>([])

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
      // Both axes drag-scale. The price axis used to be pinned, which left
      // autoscale as the only way to frame a move -- and a range you are
      // studying is exactly when you want to stretch price and leave time
      // alone.
      handleScale: { axisPressedMouseMove: { time: true, price: true } },
      autoSize: true,
    })
    chartRef.current = chart
    setReady((n) => n + 1)

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

  // -- settings ---------------------------------------------------------
  //
  // Applied rather than baked into creation: a colour change must not rebuild
  // the chart, because rebuilding resets the pan, the zoom and the drawings'
  // coordinates with it.
  useEffect(() => {
    const chart = chartRef.current
    const candles = candlesRef.current
    if (!chart || !candles) return
    const t = tokens()
    const up = settings.up || t.up
    const down = settings.down || t.down

    chart.applyOptions({
      grid: {
        vertLines: { visible: settings.grid, color: t.grid },
        horzLines: { visible: settings.grid, color: t.grid },
      },
      crosshair: { mode: settings.crosshair ? 1 : 2 },
      timeScale: { timeVisible: settings.timeVisible },
    })
    chart.priceScale('right').applyOptions({
      mode: settings.scale === 'logarithmic'
        ? PriceScaleMode.Logarithmic
        : settings.scale === 'percentage'
          ? PriceScaleMode.Percentage
          : PriceScaleMode.Normal,
    })
    candles.applyOptions({
      // Hollow means *bullish* hollow, the way every terminal draws it: an
      // up bar is an outline, a down bar is filled. Both hollow would say
      // nothing that the wick colour does not already say.
      upColor: settings.hollow ? 'rgba(0,0,0,0)' : up,
      downColor: down,
      borderVisible: settings.hollow,
      borderUpColor: up,
      borderDownColor: down,
      wickVisible: settings.wicks,
      wickUpColor: up,
      wickDownColor: down,
    })
    volumeRef.current?.applyOptions({ visible: settings.volume })
  }, [settings, ready])

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
            ? withAlpha(settings.up || t.up, 0.26)
            : withAlpha(settings.down || t.down, 0.26),
        })),
      )
    }
    chartRef.current?.timeScale().fitContent()
  }, [bars, settings.up, settings.down])

  // -- live edge --------------------------------------------------------
  useEffect(() => {
    const candles = candlesRef.current
    if (!candles || !live) return
    const t = tokens()
    try {
      candles.update({
        time: live.time as UTCTimestamp,
        open: Number(live.open), high: Number(live.high),
        low: Number(live.low), close: Number(live.close),
      })
      volumeRef.current?.update({
        time: live.time as UTCTimestamp,
        value: Number(live.volume),
        color: Number(live.close) >= Number(live.open)
          ? withAlpha(settings.up || t.up, 0.26)
          : withAlpha(settings.down || t.down, 0.26),
      })
    } catch {
      // Older than the last bar drawn (a late event after a reload). The
      // store-backed bars are already right; nothing to do.
    }
  }, [live, settings.up, settings.down])

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

  // -- order lines -------------------------------------------------------
  //
  // Rebuilt whole on each change: a handful of lines, and removing a price
  // line does not touch the series data, so the trader's zoom survives.
  useEffect(() => {
    const candles = candlesRef.current
    if (!candles) return
    for (const line of lineRefs.current) candles.removePriceLine(line)
    lineRefs.current = (priceLines ?? [])
      .filter((l) => Number.isFinite(Number(l.price)))
      .map((l) => candles.createPriceLine({
        price: Number(l.price),
        color: l.color,
        lineWidth: 1,
        lineStyle: l.style === 'dotted' ? LineStyle.Dotted : l.style === 'dashed' ? LineStyle.Dashed : LineStyle.Solid,
        axisLabelVisible: true,
        title: l.title,
      }))
  }, [priceLines, ready])

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
      className={tier >= 3 ? 'stale-box' : undefined}
      style={{ position: 'relative', width: '100%', height: '100%' }}
    >
      <div ref={host} style={{ width: '100%', height: '100%' }} />
      {/* `ready` is read so the layer remounts once the APIs exist. */}
      {drawings && chartRef.current && candlesRef.current && ready > 0 && (
        <DrawingLayer
          chart={chartRef.current}
          series={candlesRef.current}
          bars={bars}
          drawings={drawings}
          tool={tool}
          selectedId={selectedId}
          places={places}
          onSelect={onSelect ?? (() => {})}
          onDelete={onDelete ?? (() => {})}
          onCommit={onCommit ?? (() => {})}
          onUpdate={onUpdate ?? (() => {})}
          onDone={onToolDone ?? (() => {})}
        />
      )}
    </div>
  )
}
