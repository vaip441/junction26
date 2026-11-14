import { useState } from 'react'
import { removeMarket } from '../../lib/actions'
import { pct } from '../../lib/format'
import type { Consensus, MarketSummary } from '../../lib/types'
import { useStore } from '../../state/store'
import { VenueBadges } from '../common/Badge'
import { AnimatedPrice } from '../common/AnimatedPrice'
import { ConfirmButton } from '../common/ConfirmButton'
import { Points } from '../common/Price'

/** A link out, marked by its underline. */
const LINK = 'underline decoration-faint underline-offset-[3px] transition-colors hover:text-text hover:decoration-text'

/** The same question on both venues: each venue's live price, the middle of the two and how far apart they are. */
function BothVenues({ consensus }: { consensus: Consensus }) {
  const markets = useStore((s) => s.markets)
  const others = useStore((s) => s.otherPrices)
  // the stream carries each contract's newest price: a market's in the list, a related contract's beside it
  const venues = consensus.venues.map((v) => ({ ...v, price: markets[v.id]?.price ?? others[v.id] ?? v.price }))
  const [a, b] = venues
  const gap = Math.abs(a.price - b.price)
  return (
    <p className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5 text-xs text-muted" title="The same question on both venues">
      {venues.map((v) => (
        <span key={v.id}>
          {v.url ? (
            <a href={v.url} target="_blank" rel="noreferrer" className={LINK}>
              {v.venue === 'kalshi' ? 'Kalshi' : 'Polymarket'}
            </a>
          ) : v.venue === 'kalshi' ? 'Kalshi' : 'Polymarket'}{' '}
          <span className="num font-semibold text-text">{pct(v.price)}</span>
        </span>
      ))}
      <span>
        middle <span className="num font-semibold text-text">{pct((a.price + b.price) / 2)}</span>
      </span>
      {/* a wide gap between two venues asking the same thing is worth a second look */}
      <span className={gap >= 3 ? 'inv' : ''}>
        <span className="num">{gap.toFixed(1)}</span> pts apart
      </span>
    </p>
  )
}

/** The demo market is the one the backend never lets go of. */
const DEMO_ID = 'mu-demo'

/** Stop tracking this market. Two clicks, so a stray one on stage does nothing. */
function Remove({ marketId }: { marketId: string }) {
  const [note, setNote] = useState<string | null>(null)
  if (marketId === DEMO_ID) return null
  return (
    <span className="flex shrink-0 items-center gap-2">
      {note && <span className="text-xs text-down">{note}</span>}
      <ConfirmButton
        label="Stop tracking"
        question="Stop tracking it?"
        title="Stop tracking this market: it leaves the list with its tape and prices"
        onConfirm={async () => setNote(await removeMarket(marketId))}
      />
    </span>
  )
}

/** Where the price comes from: the venue, as the link to the market there; a made-up market says so. */
function Venue({ market }: { market: MarketSummary }) {
  if (market.consensus) return <BothVenues consensus={market.consensus} />
  if (market.made_up) return <VenueBadges market={market} />
  const name = market.venue === 'kalshi' ? 'Kalshi' : 'Polymarket'
  return (
    <p className="text-xs text-muted">
      {market.url ? (
        <a href={market.url} target="_blank" rel="noreferrer" className={LINK} title={`Open the market on ${name}`}>
          {name}
        </a>
      ) : (
        name
      )}
    </p>
  )
}

/**
 * The question on the left, its price on the right in board figures: the largest thing on the screen.
 * Under the price, what it did today.
 */
export function MarketHeader({ market }: { market: MarketSummary }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-x-6 gap-y-2 border-b border-line px-5 py-4">
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex min-h-7 items-center gap-3">
          <Venue market={market} />
          <Remove key={market.id} marketId={market.id} />
        </div>
        <h1 className="text-balance text-[1.6rem] font-semibold leading-[1.15] tracking-[-0.015em] text-text">{market.title}</h1>
      </div>
      <div className="text-right">
        {market.price == null ? (
          <p className="max-w-40 text-sm text-muted">Setting the starting odds from the coverage…</p>
        ) : (
          <AnimatedPrice key={market.id} value={market.price} className="board text-[5.5rem]" />
        )}
        <p className="mt-2 flex justify-end gap-4 text-xs text-muted">
          {market.change_24h != null && (
            <span>
              <Points value={market.change_24h} className="font-semibold" /> in 24 h
            </span>
          )}
          <span>
            <span className="num font-semibold text-text">{market.ticks_today}</span> {market.ticks_today === 1 ? 'tick' : 'ticks'} today
          </span>
        </p>
      </div>
    </div>
  )
}
