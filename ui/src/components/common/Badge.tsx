import type { ReactNode } from 'react'
import type { MarketSummary } from '../../lib/types'

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

/** Where a market's price comes from: its own venue, and the other one too when the same question trades there. */
export function VenueBadges({ market }: { market: Pick<MarketSummary, 'venue' | 'consensus'> }) {
  const twin = market.consensus?.venues[1]
  return (
    <span className="inline-flex items-center gap-1" title={twin ? 'Priced on both venues' : undefined}>
      <VenueBadge venue={market.venue} />
      {twin && (
        <>
          <span className="text-[10px] text-faint">+</span>
          <VenueBadge venue={twin.venue} />
        </>
      )}
    </span>
  )
}
