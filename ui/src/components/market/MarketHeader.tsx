import type { MarketSummary } from '../../lib/types'
import { VenueBadge } from '../common/Badge'
import { AnimatedPrice } from '../common/AnimatedPrice'
import { Points } from '../common/Price'

export function MarketHeader({ market }: { market: MarketSummary }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line p-4">
      <div className="min-w-0 flex-1">
        <div className="mb-1.5 flex items-center gap-2">
          <VenueBadge venue={market.venue} />
          {market.url && (
            <a href={market.url} target="_blank" rel="noreferrer" className="text-xs text-accent hover:underline">
              open on venue ↗
            </a>
          )}
        </div>
        <h1 className="text-lg font-semibold leading-tight text-text">{market.title}</h1>
      </div>
      <div className="text-right">
        {market.price == null ? (
          <p className="text-sm text-muted">setting starting odds from coverage…</p>
        ) : (
          <AnimatedPrice key={market.id} value={market.price} className="text-6xl font-bold leading-none" />
        )}
        <p className="mt-1 text-xs text-muted">
          <Points value={market.change_24h} /> 24h · <span className="num">{market.ticks_today}</span> ticks today
        </p>
      </div>
    </div>
  )
}
