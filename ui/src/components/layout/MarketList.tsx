import { useShallow } from 'zustand/react/shallow'
import { selectMarketList, useStore } from '../../state/store'
import { VenueBadges } from '../common/Badge'
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
            aria-current={m.id === selectedId}
            className={`grid w-full grid-cols-[1fr_auto] gap-x-3 gap-y-1 px-3 py-2.5 text-left transition-colors hover:bg-panel-2 ${
              m.id === selectedId ? 'bg-panel-2 shadow-[inset_3px_0_0_var(--color-text)]' : ''
            }`}
          >
            <span className={`line-clamp-2 text-[0.8125rem] leading-snug ${m.id === selectedId ? 'font-medium text-text' : 'text-text/85'}`}>{m.title}</span>
            <Price value={m.price} flash className="board text-right text-2xl text-text" />
            <VenueBadges market={m} />
            {m.change_24h != null ? <Points value={m.change_24h} className="text-right text-xs" /> : <span />}
          </button>
        </li>
      ))}
    </ul>
  )
}
