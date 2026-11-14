import type { ReactNode } from 'react'
import type { MarketSummary } from '../../lib/types'

const TONES = {
  neutral: 'text-muted',
  // made-up data is never passed off as real: its tag is the one that is filled in
  madeup: 'rounded-xs bg-madeup/15 px-1.5 text-madeup',
} as const

/** A word that says what kind of thing this is. Plain text; only the made-up tag is filled. */
export function Badge({ tone = 'neutral', children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return <span className={`inline-flex shrink-0 items-center whitespace-nowrap text-xs font-medium ${TONES[tone]}`}>{children}</span>
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
          <span className="text-xs text-faint">+</span>
          <VenueBadge venue={twin.venue} />
        </>
      )}
    </span>
  )
}
