import type { PricePoint, Tick } from './types'

/**
 * What the price did after a tick we called up or down.
 *
 * Mirrors the backend's weekend record (terminal/record.py) so the tape and the record never
 * disagree: a tick is judged by the price WINDOW seconds after it was detected (`ts`) against
 * `price_at`, and a change under MIN_MOVE points counts as no move.
 */
export const WINDOW_SECONDS = 900
export const MIN_MOVE = 1

/** A call strong enough that the price not having moved yet is worth shouting about. */
const STRONG_STRENGTH = 0.5
const STRONG_CONFIDENCE = 0.6

export type LifecycleState =
  /** Inside the window, strong call, price has not moved yet: the edge. */
  | 'edge'
  /** Inside the window, price has not moved yet. */
  | 'watching'
  /** Inside the window, price already moving the way we called. */
  | 'following'
  /** Inside the window, price moving the other way. */
  | 'against'
  /** Window over: price moved the way we called. */
  | 'priced_in'
  /** Window over: price moved the other way. */
  | 'faded'
  /** Window over: price did not move. */
  | 'flat'

export interface Lifecycle {
  state: LifecycleState
  /** Price change since the tick in points, signed (positive = price went up). */
  change: number
  /** Seconds left in the window, 0 once it is over. */
  remaining: number
  /** Seconds from the tick until the price first moved MIN_MOVE the way we called, if it did. */
  leadSeconds: number | null
}

/** Last known price at or before `ts`. `points` is in time order. */
function priceAt(points: PricePoint[], ts: number): number | null {
  let lo = 0
  let hi = points.length - 1
  let found: number | null = null
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (points[mid].ts <= ts) {
      found = points[mid].price
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return found
}

/**
 * The lifecycle of one tick, or null when it has none: no-effect verdicts, spoken/typed ticks,
 * backfill, made-up markets (their price is moved by the ticks themselves), or no starting price.
 */
export function tickLifecycle(tick: Tick, points: PricePoint[] | undefined, madeUp: boolean, now: number): Lifecycle | null {
  if (tick.verdict === 'none' || tick.test || tick.backfill || madeUp) return null
  if (tick.price_at == null || !points || points.length === 0) return null

  const start = tick.price_at
  const end = tick.ts + WINDOW_SECONDS
  const over = now >= end
  const latest = priceAt(points, over ? end : now) ?? start
  const change = latest - start
  const sign = tick.verdict === 'up' ? 1 : -1
  const aligned = change * sign

  let leadSeconds: number | null = null
  for (const p of points) {
    if (p.ts <= tick.ts) continue
    if (p.ts > end) break
    if ((p.price - start) * sign >= MIN_MOVE) {
      leadSeconds = p.ts - tick.ts
      break
    }
  }

  let state: LifecycleState
  if (over) {
    state = Math.abs(change) < MIN_MOVE ? 'flat' : aligned > 0 ? 'priced_in' : 'faded'
  } else if (Math.abs(change) < MIN_MOVE) {
    const strong = Math.abs(tick.strength) >= STRONG_STRENGTH && tick.confidence >= STRONG_CONFIDENCE
    state = strong ? 'edge' : 'watching'
  } else {
    state = aligned > 0 ? 'following' : 'against'
  }

  return { state, change, remaining: Math.max(0, end - now), leadSeconds }
}
