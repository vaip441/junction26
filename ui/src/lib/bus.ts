import type { Tick } from './types'

type Listener = (t: Tick) => void

const listeners = new Set<Listener>()
const seen = new Set<number>()

/**
 * Every tick that is new *now* (from the stream or from our own POST), announced exactly once, so the edge
 * flash reacts to it once even when the stream and the POST response both deliver it. First-paint
 * history never goes through here.
 */
export function announceTick(t: Tick): void {
  if (seen.has(t.id)) return
  seen.add(t.id)
  if (seen.size > 5000) seen.clear()
  for (const fn of listeners) fn(t)
}

/** Let ticks be announced again: a replay shows the same ticks every time it is played. */
export function forgetTicks(ids: number[]): void {
  for (const id of ids) seen.delete(id)
}

export function onNewTick(fn: Listener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}
