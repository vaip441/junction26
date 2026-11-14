import { useState } from 'react'
import type { MarketDetail } from '../../lib/types'
import { useStore, type Tab } from '../../state/store'
import { MovesPanel } from './MovesPanel'
import { RelatedContracts } from './RelatedContracts'
import { RulesPanel } from './RulesPanel'
import { SourcesPanel } from './SourcesPanel'

/**
 * Under the chart: why the price moved, where the ticks came from, the related contracts, and the rules.
 * A made-up market has no jumps of its own, but why it moved over the last day can still be asked, so
 * it has the tab too; it opens on its sources.
 */
export function MarketTabs({ marketId, madeUp, detail }: { marketId: string; madeUp: boolean; detail: MarketDetail | undefined }) {
  const wanted = useStore((s) => s.tab)
  const setTab = useStore((s) => s.setTab)
  const moves = useStore((s) => s.moves[marketId])
  // the made-up market's first tab is its sources unless "why did it move?" was asked for there
  const [picked, setPicked] = useState(false)
  const tab: Tab = madeUp && wanted === 'moves' && !picked ? 'sources' : wanted
  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: 'moves', label: 'Why did it move?', count: moves?.length },
    { id: 'sources', label: 'Sources', count: detail?.sources.length },
    { id: 'related', label: 'Related', count: detail?.related.length },
    { id: 'rules', label: 'Rules' },
  ]
  return (
    <div className="flex h-44 shrink-0 flex-col border-t border-line">
      <div role="tablist" className="flex shrink-0 gap-4 border-b border-line px-3">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => {
              setPicked(true)
              setTab(t.id)
            }}
            className={`-mb-px border-b-2 py-1.5 text-[11px] font-semibold uppercase tracking-wider ${
              tab === t.id ? 'border-accent text-text' : 'border-transparent text-muted hover:text-text'
            }`}
          >
            {t.label}
            {t.count != null && t.count > 0 && <span className="num ml-1 font-normal text-faint">{t.count}</span>}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === 'moves' ? (
          <MovesPanel marketId={marketId} moves={moves} />
        ) : !detail ? (
          <p className="p-3 text-xs text-faint">Loading…</p>
        ) : tab === 'sources' ? (
          <SourcesPanel sources={detail.sources} pages={detail.pages} />
        ) : tab === 'related' ? (
          <RelatedContracts related={detail.related} />
        ) : (
          <RulesPanel marketId={marketId} rules={detail.rules} queries={detail.queries} />
        )}
      </div>
    </div>
  )
}
