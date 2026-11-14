import { useEffect, useState } from 'react'

/** The current time in unix seconds, refreshed every `everyMs` so time-based labels stay live. */
export function useNow(everyMs = 5000): number {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), everyMs)
    return () => clearInterval(timer)
  }, [everyMs])
  return now
}
