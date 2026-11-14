import type { WeekendRecord } from './types'

/** The record's counts, as the screen words them. Every figure is the backend's; nothing is worked out here but the shares for the bar. */
export interface RecordFigures {
  /** Up or down calls on real markets whose window is over. */
  calls: number
  /** Of those, followed by a qualifying price move. */
  evaluable: number
  same: number
  opposite: number
  noMove: number
  markets: number
  windowMinutes: number
  minMove: number
  since: string
}

export function recordFigures(r: WeekendRecord): RecordFigures {
  return {
    calls: r.calls,
    evaluable: r.evaluable,
    same: r.same_direction,
    opposite: r.opposite_direction,
    noMove: r.no_qualifying_move,
    markets: r.markets,
    windowMinutes: Math.round(r.window_seconds / 60),
    minMove: r.min_move_points,
    since: r.since ? new Date(r.since * 1000).toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' }) : '—',
  }
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)

/** "Of 97 calls followed by a qualifying price move, 71 moved in the predicted direction." Always with its denominator. */
export function followThrough(f: Pick<RecordFigures, 'evaluable' | 'same'>): string {
  if (f.evaluable === 0) return 'No call has been followed by a qualifying price move yet.'
  return `Of ${f.evaluable} ${plural(f.evaluable, 'call', 'calls')} followed by a qualifying price move, ${f.same} moved in the predicted direction.`
}

/** What is and is not being claimed, in the words the screen shows beside the counts. */
export function methodology(f: Pick<RecordFigures, 'windowMinutes' | 'minMove'>): string {
  return (
    `Directional follow-through: each up or down call on a real market is compared with the price ${f.windowMinutes} minutes later. ` +
    `A move of at least ${f.minMove} ${plural(f.minMove, 'point', 'points')} qualifies; less counts as no qualifying move. ` +
    'Made-up markets, replays, spoken and typed lines, backfill and calls with no price to stand on are left out. ' +
    'This shows association with later price movement, not that an item caused it, and it is not accuracy or a trading result.'
  )
}
