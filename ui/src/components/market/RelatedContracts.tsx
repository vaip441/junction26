import { askFor } from '../../lib/actions'
import type { MarketSummary } from '../../lib/types'
import { useStore } from '../../state/store'
import { VenueBadge } from '../common/Badge'
import { EmptyState } from '../common/EmptyState'
import { Points, Price } from '../common/Price'

/** Other deadlines and the same question on the other venue, with live prices. "Track" gives one its own tape. */
export function RelatedContracts({ related }: { related: MarketSummary[] }) {
  const live = useStore((s) => s.otherPrices)
  const busy = useStore((s) => Boolean(s.ask && !s.ask.marketId && !s.ask.error))
  if (related.length === 0) return <EmptyState title="No related contracts">No other deadline or venue asks this question.</EmptyState>
  return (
    <ul className="divide-y divide-line">
      {related.map((r) => (
        <li key={r.id} className="flex items-center gap-3 px-3 py-2">
          <VenueBadge venue={r.venue} />
          <span className="min-w-0 flex-1 truncate text-xs text-text" title={r.title}>
            {r.title}
          </span>
          <Price value={live[r.id] ?? r.price} className="text-sm font-semibold" />
          <Points value={r.change_24h} className="hidden text-xs sm:inline" />
          <button
            disabled={!r.url || busy}
            onClick={() => r.url && void askFor(r.url)}
            title={r.url ? 'Give it its own tape' : 'No link to track it by'}
            className="rounded border border-line px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted hover:border-accent hover:text-text disabled:opacity-40"
          >
            Track
          </button>
        </li>
      ))}
    </ul>
  )
}
