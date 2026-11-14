import { pct, pts } from '../../lib/format'

export function Price({ value, className = '' }: { value: number | null | undefined; className?: string }) {
  return <span className={`num ${className}`}>{pct(value)}</span>
}

/** A change in percentage points, coloured by direction. */
export function Points({ value, className = '' }: { value: number | null | undefined; className?: string }) {
  const tone = value == null || Math.abs(value) < 0.05 ? 'text-muted' : value > 0 ? 'text-up' : 'text-down'
  return <span className={`num ${tone} ${className}`}>{pts(value)}</span>
}
