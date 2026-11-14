import { useShallow } from 'zustand/react/shallow'
import { selectMarketList, useStore } from '../../state/store'
import { VenueBadge } from '../common/Badge'
import { EmptyState } from '../common/EmptyState'
import { Points, Price } from '../common/Price'

export function MarketList() {
  const markets = useStore(useShallow(selectMarketList))
  const selectedId = useStore((s) => s.selectedId)
  const select = useStore((s) => s.select)

  if (markets.length === 0) {
    return <EmptyState title="No markets yet">Waiting for the backend to list what it tracks.</EmptyState>
  }

  return (
    <ul className="divide-y divide-line">
      {markets.map((m) => (
        <li key={m.id}>
          <button
            onClick={() => select(m.id)}
            className={`flex w-full flex-col gap-1 px-3 py-2.5 text-left transition-colors hover:bg-panel-2 ${
              m.id === selectedId ? 'bg-panel-2 shadow-[inset_2px_0_0_var(--color-accent)]' : ''
            }`}
          >
            <span className="line-clamp-2 text-xs leading-snug text-text">{m.title}</span>
            <span className="flex items-center gap-2">
              <VenueBadge venue={m.venue} />
              <Price value={m.price} flash className="text-sm font-semibold" />
              {m.change_24h != null && <Points value={m.change_24h} className="text-xs" />}
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
