import { useState } from 'react'
import { removeMarket } from '../../lib/actions'
import { pct } from '../../lib/format'
import type { Consensus, MarketSummary } from '../../lib/types'
import { useStore } from '../../state/store'
import { VenueBadges } from '../common/Badge'
import { AnimatedPrice } from '../common/AnimatedPrice'
import { ConfirmButton } from '../common/ConfirmButton'
import { Points } from '../common/Price'

/** The same question on both venues: each venue's live price, the middle of the two and how far apart they are. */
function BothVenues({ consensus }: { consensus: Consensus }) {
  const markets = useStore((s) => s.markets)
  const others = useStore((s) => s.otherPrices)
  // the stream carries each contract's newest price: a market's in the list, a related contract's beside it
  const venues = consensus.venues.map((v) => ({ ...v, price: markets[v.id]?.price ?? others[v.id] ?? v.price }))
  const [a, b] = venues
  const gap = Math.abs(a.price - b.price)
  return (
    <p className="mt-2 flex flex-wrap items-center gap-x-2 text-xs text-muted" title="The same question on both venues">
      {venues.map((v) => (
        <span key={v.id} className="after:ml-2 after:text-faint after:content-['·']">
          {v.url ? (
            <a href={v.url} target="_blank" rel="noreferrer" className="hover:underline">
              {v.venue === 'kalshi' ? 'Kalshi' : 'Polymarket'}
            </a>
          ) : v.venue === 'kalshi' ? 'Kalshi' : 'Polymarket'}{' '}
          <span className="num text-text">{pct(v.price)}</span>
        </span>
      ))}
      <span className="after:ml-2 after:text-faint after:content-['·']">
        consensus <span className="num font-semibold text-text">{pct((a.price + b.price) / 2)}</span>
      </span>
      <span className={gap >= 3 ? 'font-semibold text-accent' : ''}>
        <span className="num">{gap.toFixed(1)}</span> pts apart
      </span>
    </p>
  )
}

/** The demo market is the one the backend never lets go of. */
const DEMO_ID = 'mu-demo'

/** Stop tracking this market. Not on stage: in presentation mode there is nothing to click by mistake. */
function Remove({ marketId }: { marketId: string }) {
  const presentation = useStore((s) => s.presentation)
  const [note, setNote] = useState<string | null>(null)
  if (presentation || marketId === DEMO_ID) return null
  return (
    <span className="ml-auto flex shrink-0 items-center gap-2">
      {note && <span className="text-xs text-down">{note}</span>}
      <ConfirmButton
        label="Remove"
        question="Stop tracking it?"
        title="Stop tracking this market: it leaves the list with its tape and prices"
        onConfirm={async () => setNote(await removeMarket(marketId))}
      />
    </span>
  )
}

export function MarketHeader({ market }: { market: MarketSummary }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line p-4">
      <div className="min-w-0 flex-1">
        <div className="mb-1.5 flex items-center gap-2">
          <VenueBadges market={market} />
          {market.url && (
            <a href={market.url} target="_blank" rel="noreferrer" className="text-xs text-accent hover:underline">
              open on venue ↗
            </a>
          )}
          <Remove key={market.id} marketId={market.id} />
        </div>
        <h1 className="text-balance text-lg font-semibold leading-tight text-text">{market.title}</h1>
        {market.consensus && <BothVenues consensus={market.consensus} />}
      </div>
      <div className="text-right">
        {market.price == null ? (
          <p className="text-sm text-muted">setting starting odds from coverage…</p>
        ) : (
          <AnimatedPrice key={market.id} value={market.price} className="text-6xl font-bold leading-none" />
        )}
        <p className="mt-1 text-xs text-muted">
          {market.change_24h != null && (
            <>
              <Points value={market.change_24h} /> 24h ·{' '}
            </>
          )}
          <span className="num">{market.ticks_today}</span> {market.ticks_today === 1 ? 'tick' : 'ticks'} today
        </p>
      </div>
    </div>
  )
}
