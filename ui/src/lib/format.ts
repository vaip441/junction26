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

/**
 * How long after it was published an item reached the tape, when that was quick enough to be worth saying:
 * within ten minutes. `fast` is under a minute and a half, the kind of speed that deserves to stand out.
 */
export function caught(t: Tick): { text: string; fast: boolean } | null {
  // a watched page's time is when the check saw the change, which can be minutes after the page changed
  if (t.published_ts == null || t.backfill || t.kind === 'page') return null
  const gap = t.ts - t.published_ts
  // exactly 0 is a replay's post, stamped with its own time; a few seconds under 0 is two clocks disagreeing
  if (gap === 0 || gap < -5 || gap >= 600) return null
  const s = Math.max(1, Math.round(gap))
  return s < 90 ? { text: `${s} s`, fast: true } : { text: `${Math.round(s / 60)} min`, fast: false }
}

export function absoluteTime(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString()
}
