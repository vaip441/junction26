import { useEffect, useRef, useState } from 'react'
import { pct } from '../../lib/format'

const reduceMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

/**
 * The big price. On a change it counts to the new value (~400 ms) and flashes the colour of the move:
 * green up, red down. A change of 3 pts or more flashes bigger.
 */
export function AnimatedPrice({ value, className = '' }: { value: number; className?: string }) {
  const [shown, setShown] = useState(value)
  const [flash, setFlash] = useState<{ dir: 'up' | 'down'; big: boolean; n: number } | null>(null)
  const from = useRef(value)
  const frame = useRef(0)
  const n = useRef(0)

  useEffect(() => {
    const start = from.current
    from.current = value
    if (start === value) return
    setFlash({ dir: value > start ? 'up' : 'down', big: Math.abs(value - start) >= 3, n: ++n.current })
    const clear = setTimeout(() => setFlash(null), 1100)
    if (reduceMotion() || document.hidden) {
      setShown(value)
      return () => clearTimeout(clear)
    }
    const t0 = performance.now()
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / 400)
      const eased = 1 - (1 - k) ** 3
      setShown(start + (value - start) * eased)
      if (k < 1) frame.current = requestAnimationFrame(step)
    }
    cancelAnimationFrame(frame.current)
    frame.current = requestAnimationFrame(step)
    // animation frames pause on a hidden or background page: never leave the price stuck mid-count
    const land = setTimeout(() => setShown(value), 450)
    return () => {
      clearTimeout(clear)
      clearTimeout(land)
      cancelAnimationFrame(frame.current)
      setShown(value)
    }
  }, [value])

  const tone = flash ? (flash.dir === 'up' ? 'text-up' : 'text-down') : 'text-text'
  return (
    <span
      key={flash?.n ?? 0}
      className={`num inline-block transition-colors duration-700 ${tone} ${flash ? (flash.big ? 'price-pop-big' : 'price-pop') : ''} ${className}`}
    >
      {pct(shown)}
    </span>
  )
}
