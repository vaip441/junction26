import {
  AreaSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNow } from '../../hooks/useNow'
import { pct, tickTime, timeAgo } from '../../lib/format'
import { tickLifecycle } from '../../lib/lifecycle'
import type { PricePoint, Tick } from '../../lib/types'
import { useStore } from '../../state/store'
import { EmptyState } from '../common/EmptyState'

const MAX_MARKERS = 300
/** Lead-time lines drawn at once: the newest ones, so the chart stays readable. */
const MAX_LEAD_LINES = 6
/** Of those, how many carry their "N min early" label (more overlap and become unreadable). */
const MAX_LEAD_LABELS = 3

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function withAlpha(hex: string, alpha: number): string {
  const a = Math.round(alpha * 255)
    .toString(16)
    .padStart(2, '0')
  return `${hex}${a}`
}

/** The chart wants strictly increasing whole seconds: keep the last price within each second. */
function toSeries(points: PricePoint[]): { time: UTCTimestamp; value: number }[] {
  const out: { time: UTCTimestamp; value: number }[] = []
  for (const p of points) {
    const time = Math.floor(p.ts) as UTCTimestamp
    if (out.length && out[out.length - 1].time === time) out[out.length - 1].value = p.price
    else if (!out.length || time > out[out.length - 1].time) out.push({ time, value: p.price })
  }
  return out
}

/** Markers only show on a bar of the series: snap a time to the last bar at or before it. */
function snap(times: UTCTimestamp[], ts: number): UTCTimestamp | null {
  let lo = 0
  let hi = times.length - 1
  let found: UTCTimestamp | null = null
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (times[mid] <= ts) {
      found = times[mid]
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return found
}

function minutes(seconds: number): string {
  return `${Math.max(1, Math.round(seconds / 60))} min`
}

/** Scroll the tape to a tick and flash it. */
function focusTick(id: number) {
  const row = document.getElementById(`tick-${id}`)
  if (!row) return
  row.scrollIntoView({ behavior: 'smooth', block: 'center' })
  row.classList.remove('tape-focus')
  void row.offsetWidth // restart the animation
  row.classList.add('tape-focus')
}

interface Hover {
  tick: Tick
  x: number
  y: number
  /** Chart width when hovered, to keep the tooltip inside it. */
  width: number
}

/**
 * The price line with every up/down call pinned on it: ▲ green above, ▼ red below, sized by strength,
 * dimmed for earlier coverage (backfill). A call the price followed gets a dashed lead-time line to where
 * the price got there. Hover a marker for its headline; click it to find it on the tape.
 */
export function PriceChart({ marketId }: { marketId: string }) {
  const box = useRef<HTMLDivElement>(null)
  const chart = useRef<IChartApi | null>(null)
  const area = useRef<ISeriesApi<'Area'> | null>(null)
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const leads = useRef(new Map<number, ISeriesApi<'Line'>>())
  const byMarker = useRef(new Map<string, Tick>())
  const fitted = useRef<string | null>(null)
  const [hover, setHover] = useState<Hover | null>(null)

  const prices = useStore((s) => s.prices[marketId])
  const ticks = useStore((s) => s.ticks[marketId])
  const market = useStore((s) => s.markets[marketId])
  const presentation = useStore((s) => s.presentation)
  const now = useNow(5000)

  // create once
  useEffect(() => {
    if (!box.current) return
    const text = cssVar('--color-muted') || '#8b96a5'
    const line = cssVar('--color-line') || '#1f2733'
    const fg = cssVar('--color-text') || '#e6edf3'
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: text, fontFamily: cssVar('--font-mono'), attributionLogo: false },
      grid: { vertLines: { color: withAlpha(line, 0.5) }, horzLines: { color: withAlpha(line, 0.5) } },
      rightPriceScale: { borderColor: line, scaleMargins: { top: 0.2, bottom: 0.15 } },
      timeScale: { borderColor: line, timeVisible: true, secondsVisible: false, rightOffset: 4 },
      crosshair: { vertLine: { color: text, labelBackgroundColor: line }, horzLine: { color: text, labelBackgroundColor: line } },
      localization: { priceFormatter: (p: number) => pct(p) },
    })
    const s = c.addSeries(AreaSeries, {
      lineColor: fg,
      lineWidth: 2,
      topColor: withAlpha(fg, 0.14),
      bottomColor: withAlpha(fg, 0),
      priceLineColor: text,
      priceLineStyle: LineStyle.Dotted,
      lastValueVisible: true,
    })
    chart.current = c
    area.current = s
    markers.current = createSeriesMarkers(s, [], { zOrder: 'top' })

    const markerTick = (p: MouseEventParams<Time>) => {
      const id = p.hoveredInfo?.objectId ?? p.hoveredObjectId
      return typeof id === 'string' ? byMarker.current.get(id) : undefined
    }
    c.subscribeCrosshairMove((p) => {
      const t = markerTick(p)
      setHover(t && p.point ? { tick: t, x: p.point.x, y: p.point.y, width: box.current?.clientWidth ?? 0 } : null)
    })
    c.subscribeClick((p) => {
      const t = markerTick(p)
      if (t) focusTick(t.id)
    })

    const leadMap = leads.current
    return () => {
      leadMap.clear()
      c.remove()
      chart.current = null
      area.current = null
      markers.current = null
    }
  }, [])

  // a different market fits the view again
  useEffect(() => {
    fitted.current = null
  }, [marketId])

  useEffect(() => {
    chart.current?.applyOptions({ layout: { fontSize: presentation ? 16 : 11 } })
  }, [presentation])

  const data = useMemo(() => toSeries(prices ?? []), [prices])

  // price line
  useEffect(() => {
    if (!area.current || !chart.current) return
    area.current.setData(data)
    if (data.length > 1 && fitted.current !== marketId) {
      chart.current.timeScale().fitContent()
      fitted.current = marketId
    }
  }, [data, marketId])

  // markers and lead-time lines
  useEffect(() => {
    const c = chart.current
    if (!c || !markers.current) return
    const up = cssVar('--color-up') || '#22c55e'
    const down = cssVar('--color-down') || '#ef4444'
    const times = data.map((d) => d.time)
    const out: SeriesMarker<Time>[] = []
    const index = new Map<string, Tick>()
    const wantLeads: { tick: Tick; from: UTCTimestamp; to: UTCTimestamp; start: number; end: number }[] = []
    const madeUp = Boolean(market?.made_up)

    for (const t of (ticks ?? []).slice(0, MAX_MARKERS)) {
      if (t.verdict === 'none') continue
      const at = snap(times, tickTime(t))
      if (at == null) continue // before the price history starts
      const colour = t.verdict === 'up' ? up : down
      const id = `t${t.id}`
      index.set(id, t)
      out.push({
        id,
        time: at,
        position: t.verdict === 'up' ? 'belowBar' : 'aboveBar',
        shape: t.verdict === 'up' ? 'arrowUp' : 'arrowDown',
        color: t.backfill ? withAlpha(colour, 0.4) : colour,
        size: 0.6 + 1.4 * Math.min(1, Math.abs(t.strength)),
      })

      const life = tickLifecycle(t, prices, madeUp, now)
      if (life?.leadSeconds != null && t.price_at != null && wantLeads.length < MAX_LEAD_LINES) {
        const reach = t.ts + life.leadSeconds
        const from = Math.floor(t.ts) as UTCTimestamp
        const to = snap(times, reach)
        if (to != null && to > from) {
          const end = data.find((d) => d.time === to)?.value ?? t.price_at
          wantLeads.push({ tick: t, from, to, start: t.price_at, end })
          out.push({
            id: `${id}-lead`,
            time: to,
            position: 'atPriceMiddle',
            price: end,
            shape: 'circle',
            color: colour,
            size: 0.5,
            text: wantLeads.length <= MAX_LEAD_LABELS ? `${minutes(life.leadSeconds)} early` : undefined,
          })
          index.set(`${id}-lead`, t)
        }
      }
    }
    out.sort((a, b) => (a.time as number) - (b.time as number))
    markers.current.setMarkers(out)
    byMarker.current = index

    // keep one dashed line series per lead; drop the ones no longer wanted
    const keep = new Set(wantLeads.map((l) => l.tick.id))
    for (const [id, series] of leads.current) {
      if (!keep.has(id)) {
        c.removeSeries(series)
        leads.current.delete(id)
      }
    }
    for (const l of wantLeads) {
      let series = leads.current.get(l.tick.id)
      if (!series) {
        series = c.addSeries(LineSeries, {
          color: l.tick.verdict === 'up' ? up : down,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
        })
        leads.current.set(l.tick.id, series)
      }
      series.setData([
        { time: l.from, value: l.start },
        { time: l.to, value: l.end },
      ])
    }
  }, [ticks, data, prices, market?.made_up, now])

  const empty =
    prices === undefined
      ? 'Loading prices…'
      : data.length === 0
        ? market?.made_up
          ? 'Setting starting odds from coverage…'
          : 'No price yet: the venue has not answered'
        : null

  return (
    <div className="relative h-full min-h-56">
      <div ref={box} className="absolute inset-0" />
      {empty && (
        <div className="absolute inset-0">
          <EmptyState title={empty} />
        </div>
      )}
      {hover && hover.tick.market_id === marketId && (
        <div
          className="pointer-events-none absolute z-10 max-w-72 rounded border border-line bg-panel-2/95 p-2 shadow-lg"
          style={{
            left: Math.max(4, Math.min(hover.x + 12, hover.width - 290)),
            top: Math.max(4, hover.y - 70),
          }}
        >
          <p className={`num text-[11px] font-bold ${hover.tick.verdict === 'up' ? 'text-up' : 'text-down'}`}>
            {hover.tick.verdict === 'up' ? '▲ UP' : '▼ DOWN'} {Math.round(hover.tick.confidence * 100)}%
            <span className="ml-2 font-normal text-faint">{timeAgo(tickTime(hover.tick))}</span>
          </p>
          <p className="line-clamp-3 text-xs leading-snug text-text">{hover.tick.headline}</p>
          <p className="mt-0.5 text-[10px] text-faint">click to find it on the tape</p>
        </div>
      )}
    </div>
  )
}
