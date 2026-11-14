import type { WeekendRecord } from './types'

export interface RecordFigures {
  called: number
  moved: number
  sameWay: number
  wrongWay: number
  noMove: number
  /** same way / moved, 0-100, or null before any call has moved the price. */
  hitRate: number | null
  windowMinutes: number
  since: string
}

export function recordFigures(r: WeekendRecord): RecordFigures {
  return {
    called: r.called,
    moved: r.moved,
    sameWay: r.same_way,
    wrongWay: r.moved - r.same_way,
    noMove: r.called - r.moved,
    hitRate: r.moved > 0 ? (r.same_way / r.moved) * 100 : null,
    windowMinutes: Math.round(r.window_seconds / 60),
    since: r.since ? new Date(r.since * 1000).toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' }) : '—',
  }
}
