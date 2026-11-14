import { useEffect, useState } from 'react'
import { useStore } from '../state/store'

/**
 * The current time in unix seconds, refreshed every `everyMs` so time-based labels stay live.
 * While a replay is on screen it is the replay's time: its clock while it plays, its last minute otherwise,
 * so every "3 min ago" and every call's fate is told as of then.
 */
export function useNow(everyMs = 5000): number {
  const then = useStore((s) => {
    const m = s.selectedId ? s.markets[s.selectedId] : undefined
    return m?.replay ? (s.replay?.id === m.id ? s.replay.clock : m.replay.end) : null
  })
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), everyMs)
    return () => clearInterval(timer)
  }, [everyMs])
  return then ?? now
}
