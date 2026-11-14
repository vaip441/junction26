import type { ReactNode } from 'react'

const TONES = {
  neutral: 'border-line text-muted',
  madeup: 'border-madeup/50 text-madeup',
  up: 'border-up/50 text-up',
  down: 'border-down/50 text-down',
  none: 'border-none/50 text-none',
  accent: 'border-accent/50 text-accent',
} as const

export function Badge({ tone = 'neutral', children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider ${TONES[tone]}`}
    >
      {children}
    </span>
  )
}

export function VenueBadge({ venue }: { venue: 'kalshi' | 'polymarket' | 'made_up' }) {
  if (venue === 'made_up') return <Badge tone="madeup">Made up</Badge>
  return <Badge>{venue === 'kalshi' ? 'Kalshi' : 'Polymarket'}</Badge>
}
