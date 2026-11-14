import { EmptyState } from '../common/EmptyState'

/**
 * Price line with scored ticks pinned on it (lightweight-charts). Build step 4.
 * Markers sit at `published_ts ?? ts`: ▲ green above for up, ▼ red below for down, sized by strength.
 */
export function PriceChart({ marketId: _marketId }: { marketId: string }) {
  return (
    <div className="h-full rounded border border-dashed border-line">
      <EmptyState title="Price chart">Arrives in build step 4: the price line with every up/down tick pinned on it.</EmptyState>
    </div>
  )
}
