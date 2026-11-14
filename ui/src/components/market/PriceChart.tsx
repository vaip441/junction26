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
import { focusTick } from '../../lib/focus'
import { tickLifecycle } from '../../lib/lifecycle'
import { causeLabel } from '../../lib/moves'
import { shortSource } from '../../lib/sources'
import type { Move, PricePoint, Tick } from '../../lib/types'
import { useStore } from '../../state/store'
import { EmptyState } from '../common/EmptyState'
import { MoveSpan } from './MovesPanel'
import { TickMarkers, type MoveBand, type TickMark } from './tickMarkers'

const MAX_MARKERS = 300
/** Lead-time lines drawn at once: the newest ones, so the chart stays readable. */
const MAX_LEAD_LINES = 6
/** Of those, how many carry their "N min early" label (more overlap and become unreadable). */
const MAX_LEAD_LABELS = 3
/** The price axis never spans less than this many points, so a flat price is a flat line with distinct labels. */
const MIN_SPAN = 6

/** How much of the history the chart shows, counted back from the newest price. */
const RANGES = [
  { id: '1h', label: '1H', seconds: 3600 },
  { id: '6h', label: '6H', seconds: 6 * 3600 },
  { id: '1d', label: '1D', seconds: 24 * 3600 },
  { id: '1w', label: '1W', seconds: 7 * 24 * 3600 },
  { id: 'all', label: 'All', seconds: Infinity },
] as const
type RangeId = (typeof RANGES)[number]['id']
/** Empty bars kept to the right of the newest price, as in the chart's own `rightOffset`. */
const RIGHT_OFFSET = 4

/** Seconds of price history on the chart. */
function historySpan(data: { time: UTCTimestamp }[]): number {
  return data.length > 1 ? data[data.length - 1].time - data[0].time : 0
}

/** Show the last `id` of the history; a range longer than the history, like "All", shows everything. */
function showRange(c: IChartApi, data: { time: UTCTimestamp }[], id: RangeId): void {
  const seconds = RANGES.find((r) => r.id === id)?.seconds ?? Infinity
  if (data.length < 2 || seconds >= historySpan(data)) {
    c.timeScale().fitContent()
    return
  }
  const start = data[data.length - 1].time - seconds
  let from = data.findIndex((d) => d.time >= start)
  // the bar just before the range starts, so the line enters from the left edge; never fewer than two bars
  from = Math.max(0, Math.min(from - 1, data.length - 2))
  c.timeScale().setVisibleLogicalRange({ from, to: data.length - 1 + RIGHT_OFFSET })
}

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

interface Hover {
  /** A dot (a call) or a band (a price jump) under the pointer. */
  tick?: Tick
  move?: Move
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
  const carets = useRef<TickMarkers | null>(null)
  const leads = useRef(new Map<number, ISeriesApi<'Line'>>())
  const byMarker = useRef(new Map<string, Tick>())
  const byBand = useRef(new Map<string, Move>())
  const fitted = useRef<string | null>(null)
  const [hover, setHover] = useState<Hover | null>(null)
  const [range, setRange] = useState<RangeId>('all')
  // the latest range and data, for the resize observer made once below
  const view = useRef<{ range: RangeId; data: { time: UTCTimestamp }[] }>({ range: 'all', data: [] })

  const prices = useStore((s) => s.prices[marketId])
  const ticks = useStore((s) => s.ticks[marketId])
  // a market asked for just now: once the question leaves the centre of the screen, its history is wiped in
  const wiping = useStore((s) => s.ask?.marketId === marketId && s.ask.opened)
  const moves = useStore((s) => s.moves[marketId])
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
      timeScale: { borderColor: line, timeVisible: true, secondsVisible: false, rightOffset: RIGHT_OFFSET },
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
      // a price that has barely moved would otherwise be stretched until every axis label rounds to the same %
      autoscaleInfoProvider: (original: () => { priceRange: { minValue: number; maxValue: number } | null } | null) => {
        const info = original()
        const r = info?.priceRange
        if (!info || !r || r.maxValue - r.minValue >= MIN_SPAN) return info
        const mid = (r.minValue + r.maxValue) / 2
        const min = Math.max(0, Math.min(100 - MIN_SPAN, mid - MIN_SPAN / 2))
        return { ...info, priceRange: { minValue: min, maxValue: min + MIN_SPAN } }
      },
    })
    chart.current = c
    area.current = s
    markers.current = createSeriesMarkers(s, [], { zOrder: 'top' })
    const tm = new TickMarkers()
    s.attachPrimitive(tm)
    carets.current = tm

    const under = (p: MouseEventParams<Time>) => {
      const id = p.hoveredInfo?.objectId ?? p.hoveredObjectId
      if (typeof id !== 'string') return {}
      return { tick: byMarker.current.get(id), move: byBand.current.get(id) }
    }
    c.subscribeCrosshairMove((p) => {
      const { tick, move } = under(p)
      setHover((tick || move) && p.point ? { tick, move, x: p.point.x, y: p.point.y, width: box.current?.clientWidth ?? 0 } : null)
    })
    c.subscribeClick((p) => {
      const { tick, move } = under(p)
      if (tick) focusTick(tick.id)
      else if (move) {
        // the answer is in the tab under the chart, and its cause is on the tape
        useStore.getState().setTab('moves')
        requestAnimationFrame(() => document.getElementById(`move-${move.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }))
        const item = move.cause ?? move.closest
        if (item) focusTick(item.id)
      }
    })

    // The chart has no width until its box is laid out, and a fit made then squeezes a short history into a
    // sliver. Show the range again whenever the box changes width (first layout, window resize, presentation mode).
    let width = 0
    const resized = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width)
      if (w === width) return
      width = w
      if (w > 0 && fitted.current) showRange(c, view.current.data, view.current.range)
    })
    resized.observe(box.current)

    const leadMap = leads.current
    return () => {
      resized.disconnect()
      leadMap.clear()
      c.remove()
      chart.current = null
      area.current = null
      markers.current = null
      carets.current = null
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
    view.current.data = data
    if (data.length > 1 && fitted.current !== marketId) {
      showRange(chart.current, data, view.current.range)
      fitted.current = marketId
    }
  }, [data, marketId])

  const pickRange = (id: RangeId) => {
    setRange(id)
    view.current.range = id
    if (chart.current) showRange(chart.current, data, id)
  }
  // a range longer than this market's history would show the same as "All": it cannot be picked, and when
  // it was picked on another market, "All" is what is shown
  const span = historySpan(data)
  const shown: RangeId = RANGES.some((r) => r.id === range && r.seconds < span) ? range : 'all'

  // markers and lead-time lines
  useEffect(() => {
    const c = chart.current
    if (!c || !markers.current) return
    const up = cssVar('--color-up') || '#22c55e'
    const down = cssVar('--color-down') || '#ef4444'
    const times = data.map((d) => d.time)
    const out: SeriesMarker<Time>[] = []
    const marks: TickMark[] = []
    const valueAt = new Map(data.map((d) => [d.time, d.value]))
    const index = new Map<string, Tick>()
    const wantLeads: { tick: Tick; from: UTCTimestamp; to: UTCTimestamp; start: number; end: number }[] = []
    const madeUp = Boolean(market?.made_up)

    for (const t of (ticks ?? []).slice(0, MAX_MARKERS)) {
      if (t.verdict === 'none') continue
      // earlier coverage whose date is not known yet has no place on a time axis: "when we found it" is now
      if (t.backfill && t.published_ts == null) continue
      const at = snap(times, tickTime(t))
      if (at == null) continue // before the price history starts
      const colour = t.verdict === 'up' ? up : down
      const id = `t${t.id}`
      index.set(id, t)
      marks.push({
        id,
        time: at,
        value: valueAt.get(at) ?? 0,
        up: t.verdict === 'up',
        color: t.backfill ? withAlpha(colour, 0.4) : colour,
        strength: Math.min(1, Math.abs(t.strength)),
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
    marks.reverse() // oldest first, so the newest call sits on the line and draws on top

    // price jumps: a band over the stretch where each happened, grey when nothing explains it
    const none = cssVar('--color-none') || '#6b7280'
    const bands: MoveBand[] = []
    const bandIndex = new Map<string, Move>()
    for (const m of moves ?? []) {
      if (m.asked) continue // the last day, explained on request: a band a day wide would shade the whole chart
      const from = snap(times, m.since)
      const to = snap(times, m.ts)
      if (from == null || to == null) continue // before the price history starts
      const bid = `m${m.id}`
      bands.push({ id: bid, from, to, color: !m.explained ? none : m.to >= m.from ? up : down })
      bandIndex.set(bid, m)
    }
    byBand.current = bandIndex
    carets.current?.set(marks, bands, presentation ? 1.4 : 1, cssVar('--color-panel') || '#0d1117')
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
  }, [ticks, moves, data, prices, market?.made_up, now, presentation])

  const tick = hover?.tick
  // calls made before the first price we have: real, on the tape, but with no price to pin them to
  const first = data[0]?.time
  const before = first == null ? 0 : (ticks ?? []).filter((t) => t.verdict !== 'none' && t.published_ts != null && t.published_ts < first).length
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
      {wiping && !empty && (
        // the price history sweeps in from the left: a cover over the plot slides away (pure CSS, so it is
        // smooth however busy or throttled the page is); the price axis on the right stays put
        <div className="pointer-events-none absolute inset-y-0 left-0 right-14 overflow-hidden">
          <div className="chart-wipe absolute inset-0" />
        </div>
      )}
      {!empty && data.length > 1 && (
        <div role="group" aria-label="Chart range" className="absolute left-2 top-2 z-10 flex gap-0.5 rounded border border-line bg-panel/90 p-0.5">
          {RANGES.map((r) => {
            const available = r.id === 'all' || r.seconds < span
            return (
              <button
                key={r.id}
                type="button"
                aria-pressed={shown === r.id}
                disabled={!available}
                title={available ? undefined : 'The price history is shorter than this'}
                onClick={() => pickRange(r.id)}
                className={`num rounded px-1.5 py-0.5 font-semibold uppercase tracking-wider transition-colors ${
                  presentation ? 'text-sm' : 'text-[11px]'
                } ${
                  shown === r.id
                    ? 'bg-panel-2 text-text'
                    : available
                      ? 'text-muted hover:text-text'
                      : 'cursor-not-allowed text-faint opacity-50'
                }`}
              >
                {r.label}
              </button>
            )
          })}
        </div>
      )}
      {empty && (
        <div className="absolute inset-0">
          <EmptyState title={empty} />
        </div>
      )}
      {!empty && before > 0 && first != null && (
        <p className="pointer-events-none absolute bottom-8 left-2 z-10 max-w-[70%] rounded bg-panel/90 px-2 py-1 text-[11px] leading-snug text-muted">
          Price history starts {new Date(first * 1000).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })}.{' '}
          <span className="num text-text">{before}</span> earlier {before === 1 ? 'call is' : 'calls are'} on the tape, from before this chart starts.
        </p>
      )}
      {hover?.move && !hover.tick && hover.move.market_id === marketId && (
        <div
          className="pointer-events-none absolute z-10 max-w-72 rounded border border-line bg-panel-2/95 p-2 shadow-lg"
          style={{ left: Math.max(4, Math.min(hover.x + 12, hover.width - 290)), top: Math.max(4, hover.y - 70) }}
        >
          <p className="text-[11px]">
            <span className="mr-2 font-semibold uppercase tracking-wider text-muted">Why did it move?</span>
            <MoveSpan move={hover.move} />
          </p>
          {hover.move.explained && hover.move.cause ? (
            <p className="line-clamp-3 text-xs leading-snug text-text">
              <span className="text-muted">
                {causeLabel(hover.move).label.toLowerCase()}
                {causeLabel(hover.move).percent != null && ` (${causeLabel(hover.move).percent}%)`}: {shortSource(hover.move.cause.source)}:{' '}
              </span>
              {hover.move.cause.headline}
            </p>
          ) : (
            <p className="line-clamp-3 text-xs leading-snug text-muted">
              No news explains it
              {hover.move.related[0] && (
                <>
                  : <span className="text-text">{hover.move.related[0].title}</span> moved at the same time
                </>
              )}
            </p>
          )}
          <p className="mt-0.5 text-[10px] text-faint">click for the answer under the chart</p>
        </div>
      )}
      {hover && tick && tick.market_id === marketId && (
        <div
          className="pointer-events-none absolute z-10 max-w-72 rounded border border-line bg-panel-2/95 p-2 shadow-lg"
          style={{
            left: Math.max(4, Math.min(hover.x + 12, hover.width - 290)),
            top: Math.max(4, hover.y - 70),
          }}
        >
          <p className={`num text-[11px] font-bold ${tick.verdict === 'up' ? 'text-up' : 'text-down'}`}>
            {tick.verdict === 'up' ? '▲ UP' : '▼ DOWN'} {Math.round(tick.confidence * 100)}%
            <span className="ml-2 font-normal text-faint">{timeAgo(tickTime(tick))}</span>
          </p>
          <p className="line-clamp-3 text-xs leading-snug text-text">{tick.headline}</p>
          <p className="mt-0.5 text-[10px] text-faint">click to find it on the tape</p>
        </div>
      )}
    </div>
  )
}
