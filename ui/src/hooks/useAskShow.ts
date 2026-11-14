import { useEffect } from 'react'
import { api } from '../lib/api'
import { useStore } from '../state/store'

/** How long the question stays on the centre of the screen after its market is known: time to see which was picked. */
const LINGER_MS = 1100
const LINGER_PLAIN_MS = 300
/** The question's fade, matching `.soft-out`. */
const FADE_MS = 380
/** A search that never reports "ready" is taken as over after this long. */
const GIVE_UP_MS = 120_000
/** The closing line stays up this long, then the ask is over. */
const CLOSING_MS = 16_000

/**
 * Times the show around a question being asked: uncovers the new market a beat after it is picked, meters
 * Context.dev while the search runs, and takes the closing line down after a while.
 */
export function useAskShow(): void {
  const tracked = useStore((s) => s.ask != null && s.ask.marketId != null && !s.ask.opened)
  const picked = useStore((s) => Boolean(s.ask?.steps.some((ev) => ev.status === 'picked')))
  const fading = useStore((s) => s.ask != null && s.ask.opened && !s.ask.uncovered)
  const working = useStore((s) => s.ask != null && s.ask.finished == null && !s.ask.error)
  const finished = useStore((s) => s.ask != null && s.ask.finished != null)

  useEffect(() => {
    if (!tracked) return
    const timer = setTimeout(() => useStore.getState().openAsk(), picked ? LINGER_MS : LINGER_PLAIN_MS)
    return () => clearTimeout(timer)
  }, [tracked, picked])

  useEffect(() => {
    if (!fading) return
    const timer = setTimeout(() => useStore.getState().uncoverAsk(), FADE_MS)
    return () => clearTimeout(timer)
  }, [fading])

  // Context.dev credits spent since the question was asked: the judges' own product, seen doing the work
  useEffect(() => {
    if (!working) return
    let base: number | null = null
    let stopped = false
    const read = async () => {
      try {
        const { context_dev: c } = await api.status()
        if (stopped) return
        const left = c.keys.length > 0 && c.keys.every((k) => k.credits_remaining != null)
          ? c.keys.reduce((sum, k) => sum + (k.credits_remaining ?? 0), 0)
          : null
        if (base == null) base = left
        useStore.getState().setMeter({ credits: left == null || base == null ? null : Math.max(0, base - left), perMinute: c.used_last_minute })
      } catch {
        // the meter is decoration: without it the show goes on
      }
    }
    void read()
    const timer = setInterval(read, 1500)
    const giveUp = setTimeout(() => useStore.getState().finishAsk(), GIVE_UP_MS)
    return () => {
      stopped = true
      clearInterval(timer)
      clearTimeout(giveUp)
    }
  }, [working])

  useEffect(() => {
    if (!finished) return
    const timer = setTimeout(() => useStore.getState().clearAsk(), CLOSING_MS)
    return () => clearTimeout(timer)
  }, [finished])
}
