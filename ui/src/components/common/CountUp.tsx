import { useEffect, useState } from 'react'

/** Counts from 0 to `value` once, on mount. Lands on the value even where animation frames are paused. */
export function CountUp({ value, ms = 1200, format = (n: number) => String(Math.round(n)) }: { value: number; ms?: number; format?: (n: number) => string }) {
  const [still] = useState(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)
  const [shown, setShown] = useState(still ? value : 0)
  useEffect(() => {
    if (still) return
    const t0 = performance.now()
    let frame = 0
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / ms)
      setShown(value * (1 - (1 - k) ** 3))
      if (k < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    const land = setTimeout(() => setShown(value), ms + 50)
    return () => {
      cancelAnimationFrame(frame)
      clearTimeout(land)
    }
  }, [value, ms, still])
  return <>{format(still ? value : shown)}</>
}
