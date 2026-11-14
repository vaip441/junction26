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
 * halo in the panel colour so it stays crisp against the line and the grid.
 */
export class TickMarkers implements ISeriesPrimitive<Time> {
  private chart: IChartApiBase<Time> | null = null
  private series: ISeriesApi<SeriesType, Time> | null = null
  private requestUpdate: (() => void) | null = null
  private marks: TickMark[] = []
  private placed: Placed[] = []
  private scale = 1
  private halo = '#0d1117'

  private readonly view: IPrimitivePaneView = {
    zOrder: () => 'top',
    renderer: () => this.renderer,
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
  set(marks: TickMark[], scale: number, halo: string): void {
    this.marks = marks
    this.scale = scale
    this.halo = halo
    this.requestUpdate?.()
  }

  updateAllViews(): void {
    const out: Placed[] = []
    const chart = this.chart
    const series = this.series
    if (chart && series) {
      const ts = chart.timeScale()
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
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view]
  }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    for (let i = this.placed.length - 1; i >= 0; i--) {
      const p = this.placed[i]
      if (Math.hypot(x - p.x, y - p.y) <= p.r + 5) return { externalId: p.id, zOrder: 'top', cursorStyle: 'pointer' }
    }
    return null
  }
}
