import type {
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  PrimitiveHoveredItem,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from 'lightweight-charts'

/** One up/down call pinned on the price line. */
export interface TickMark {
  /** Reported as the hovered object id, so the chart can find the tick. */
  id: string
  time: Time
  /** The price on the line at that time. */
  value: number
  up: boolean
  color: string
  /** 0…1: how strong the call was; sets the dot's size. */
  strength: number
}

/** "Why did it move?": a price jump, shaded over the stretch of the chart where it happened. */
export interface MoveBand {
  /** Reported as the hovered object id, so the chart can find the move. */
  id: string
  from: Time
  to: Time
  color: string
}

interface PlacedBand {
  id: string
  x0: number
  x1: number
  color: string
}

/** A jump of a few seconds is still wide enough to see and to point at. */
const MIN_BAND = 8

interface Placed {
  id: string
  x: number
  y: number
  r: number
  color: string
  /** A strong call gets a soft outer ring. */
  strong: boolean
}

/** Clear space between dots that land on the same spot. */
const STACK_GAP = 3

/**
 * Dots on the price line, one per up/down call: green for up, red for down, sized by strength. The
 * library's own arrow markers are heavy blocks; a dot sits on the line where the call was made, with a
 * halo in the panel colour so it stays crisp against the line and the grid. Behind them, each price jump
 * is a shaded band with a "?" at its top.
 */
export class TickMarkers implements ISeriesPrimitive<Time> {
  private chart: IChartApiBase<Time> | null = null
  private series: ISeriesApi<SeriesType, Time> | null = null
  private requestUpdate: (() => void) | null = null
  private marks: TickMark[] = []
  private placed: Placed[] = []
  private bands: MoveBand[] = []
  private placedBands: PlacedBand[] = []
  private height = 0
  private scale = 1
  private halo = '#0d1117'

  private readonly view: IPrimitivePaneView = {
    zOrder: () => 'top',
    renderer: () => this.renderer,
  }

  private readonly bandView: IPrimitivePaneView = {
    zOrder: () => 'bottom',
    renderer: () => this.bandRenderer,
  }

  private readonly bandRenderer: IPrimitivePaneRenderer = {
    draw: (target) => {
      target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
        this.height = mediaSize.height
        ctx.save()
        const s = this.scale
        for (const b of this.placedBands) {
          const w = b.x1 - b.x0
          ctx.fillStyle = b.color
          ctx.globalAlpha = 0.1
          ctx.fillRect(b.x0, 0, w, mediaSize.height)
          ctx.globalAlpha = 0.45
          ctx.fillRect(b.x0, 0, w, 2 * s)
          // the "?" that says this stretch has an answer
          const cx = b.x0 + w / 2
          ctx.globalAlpha = 1
          ctx.beginPath()
          ctx.arc(cx, 11 * s, 7 * s, 0, Math.PI * 2)
          ctx.fillStyle = this.halo
          ctx.fill()
          ctx.strokeStyle = b.color
          ctx.lineWidth = 1
          ctx.stroke()
          ctx.fillStyle = b.color
          ctx.font = `600 ${10 * s}px ui-sans-serif, system-ui, sans-serif`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText('?', cx, 11.5 * s)
        }
        ctx.restore()
      })
    },
  }

  private readonly renderer: IPrimitivePaneRenderer = {
    draw: (target) => {
      target.useMediaCoordinateSpace(({ context: ctx }) => {
        ctx.save()
        for (const p of this.placed) {
          ctx.beginPath()
          ctx.arc(p.x, p.y, p.r + 2 * this.scale, 0, Math.PI * 2)
          ctx.fillStyle = this.halo
          ctx.fill()
          ctx.beginPath()
          ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
          ctx.fillStyle = p.color
          ctx.fill()
          if (p.strong) {
            ctx.beginPath()
            ctx.arc(p.x, p.y, p.r + 3.5 * this.scale, 0, Math.PI * 2)
            ctx.strokeStyle = p.color
            ctx.globalAlpha = 0.4
            ctx.lineWidth = 1
            ctx.stroke()
            ctx.globalAlpha = 1
          }
        }
        ctx.restore()
      })
    },
  }

  attached({ chart, series, requestUpdate }: SeriesAttachedParameter<Time>): void {
    this.chart = chart
    this.series = series
    this.requestUpdate = requestUpdate
  }

  detached(): void {
    this.chart = null
    this.series = null
    this.requestUpdate = null
  }

  /** `scale` enlarges the dots with the rest of the screen (presentation mode). */
  set(marks: TickMark[], bands: MoveBand[], scale: number, halo: string): void {
    this.marks = marks
    this.bands = bands
    this.scale = scale
    this.halo = halo
    this.requestUpdate?.()
  }

  updateAllViews(): void {
    const out: Placed[] = []
    const outBands: PlacedBand[] = []
    const chart = this.chart
    const series = this.series
    if (chart && series) {
      const ts = chart.timeScale()
      for (const b of this.bands) {
        const x0 = ts.timeToCoordinate(b.from)
        const x1 = ts.timeToCoordinate(b.to)
        if (x0 == null || x1 == null) continue
        const pad = Math.max(0, MIN_BAND * this.scale - (x1 - x0)) / 2
        outBands.push({ id: b.id, x0: x0 - pad, x1: x1 + pad, color: b.color })
      }
      // dots that land on the same spot stack away from the line (up calls below it, down calls above)
      const stacked = new Map<string, number>()
      for (const m of this.marks) {
        const x = ts.timeToCoordinate(m.time)
        const y = series.priceToCoordinate(m.value)
        if (x == null || y == null) continue
        const r = (2.5 + 2.5 * m.strength) * this.scale
        const key = `${Math.round(x / 4)}${m.up ? 'u' : 'd'}`
        const used = stacked.get(key)
        const offset = used == null ? 0 : used + r
        stacked.set(key, offset + r + STACK_GAP * this.scale)
        out.push({ id: m.id, x, y: y + (m.up ? offset : -offset), r, color: m.color, strong: m.strength >= 0.66 })
      }
    }
    this.placed = out
    this.placedBands = outBands
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.bandView, this.view]
  }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    for (let i = this.placed.length - 1; i >= 0; i--) {
      const p = this.placed[i]
      if (Math.hypot(x - p.x, y - p.y) <= p.r + 5) return { externalId: p.id, zOrder: 'top', cursorStyle: 'pointer' }
    }
    // a dot inside a band is still a dot: bands answer only where no dot does
    if (y >= 0 && y <= this.height) {
      for (let i = this.placedBands.length - 1; i >= 0; i--) {
        const b = this.placedBands[i]
        if (x >= b.x0 - 2 && x <= b.x1 + 2) return { externalId: b.id, zOrder: 'bottom', cursorStyle: 'pointer' }
      }
    }
    return null
  }
}
