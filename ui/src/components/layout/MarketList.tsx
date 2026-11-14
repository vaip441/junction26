import { useShallow } from 'zustand/react/shallow'
import { selectMarketList, useStore } from '../../state/store'
import { Badge, VenueBadges } from '../common/Badge'
import { EmptyState } from '../common/EmptyState'
import { Points, Price } from '../common/Price'

export function MarketList() {
  const markets = useStore(useShallow(selectMarketList))
  const selectedId = useStore((s) => s.selectedId)
  const select = useStore((s) => s.select)
  const unseen = useStore((s) => s.unseen)

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
            <span className="flex items-center gap-2">
              <VenueBadges market={m} />
              {m.replay && <Badge>Replay</Badge>}
              {/* news that landed here while another market was open; gone once this one is opened */}
              {unseen[m.id] > 0 && (
                <span className="num flex items-center gap-1 text-xs font-semibold text-text" title="Landed on its tape since you last opened it">
                  <i className="h-1.5 w-1.5 rounded-full bg-text" />
                  {unseen[m.id]} new
                </span>
              )}
            </span>
            {m.change_24h != null ? <Points value={m.change_24h} className="text-right text-xs" /> : <span />}
          </button>
        </li>
      ))}
    </ul>
  )
}
