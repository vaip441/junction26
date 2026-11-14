import { useEffect, useRef, useState } from 'react'
import { pct, pts } from '../../lib/format'

/**
 * A price. With `flash`, a change that shows (the rounded figure differs) tints it the colour of the
 * direction for a moment, so a list of markets says which one just moved.
 */
export function Price({ value, className = '', flash = false }: { value: number | null | undefined; className?: string; flash?: boolean }) {
  const before = useRef(value)
  const [tint, setTint] = useState<{ dir: 'up' | 'down'; n: number } | null>(null)

  useEffect(() => {
    const was = before.current
    before.current = value
    if (!flash || was == null || value == null || pct(was) === pct(value)) return
    setTint((t) => ({ dir: value > was ? 'up' : 'down', n: (t?.n ?? 0) + 1 }))
  }, [value, flash])

  return (
    <span key={tint?.n ?? 0} className={`num ${tint ? `tint-${tint.dir}` : ''} ${className}`}>
      {pct(value)}
    </span>
  )
}

/** A change in percentage points, coloured by direction. */
export function Points({ value, className = '' }: { value: number | null | undefined; className?: string }) {
  const tone = value == null || Math.abs(value) < 0.05 ? 'text-muted' : value > 0 ? 'text-up' : 'text-down'
  return <span className={`num ${tone} ${className}`}>{pts(value)}</span>
}
