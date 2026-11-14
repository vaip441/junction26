import type { Tick } from './types'

/** 82 -> "82%". Prices are always whole-ish percentages. */
export function pct(value: number | null | undefined): string {
  if (value == null) return '—'
  return `${value < 10 && value % 1 !== 0 ? value.toFixed(1) : Math.round(value)}%`
}

/** A change in percentage points: +18 -> "+18 pts". Never "+18%". */
export function pts(value: number | null | undefined): string {
  if (value == null) return '—'
  const rounded = Math.abs(value) < 10 ? Math.round(value * 10) / 10 : Math.round(value)
  if (rounded === 0) return '0 pts'
  return `${rounded > 0 ? '+' : '−'}${Math.abs(rounded)} pts`
}

/** The time to show for a tick: when it was published if known, otherwise when we found it. */
export function tickTime(t: Tick): number {
  return t.published_ts ?? t.ts
}

export function timeAgo(seconds: number, now = Date.now() / 1000): string {
  const d = Math.max(0, now - seconds)
  if (d < 45) return 'just now'
  if (d < 3600) return `${Math.round(d / 60)}m ago`
  if (d < 86400) return `${Math.round(d / 3600)}h ago`
  return `${Math.round(d / 86400)}d ago`
}

export function absoluteTime(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString()
}
