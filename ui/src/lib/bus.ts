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

export function onNewTick(fn: Listener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}
