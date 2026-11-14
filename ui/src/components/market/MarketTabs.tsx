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
  // Until a tab is picked by hand, the one shown is one with something in it: "why did it move?" where there
  // is a move to explain, else the sources, else the rules. A made-up market and a replay have no jumps of
  // their own, so they open on their sources unless "why did it move?" was asked for there.
  const [picked, setPicked] = useState(false)
  const hasSources = Boolean(detail?.sources.length)
  const tab: Tab =
    picked || wanted !== 'moves'
      ? wanted
      : madeUp
        ? hasSources || !detail ? 'sources' : 'rules'
        : moves === undefined || moves.length > 0 || !detail
          ? 'moves'
          : hasSources
            ? 'sources'
            : 'rules'
  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: 'moves', label: 'Why did it move?', count: moves?.length },
    { id: 'sources', label: 'Sources', count: detail?.sources.length },
    { id: 'related', label: 'Related', count: detail?.related.length },
    { id: 'rules', label: 'Rules' },
  ]
  return (
    <div className="flex h-[min(12rem,22vh)] shrink-0 flex-col border-t border-line bg-panel">
      <div role="tablist" className="flex shrink-0 gap-5 border-b border-line px-3">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => {
              setPicked(true)
              setTab(t.id)
            }}
            className={`-mb-px border-b-2 py-2 text-xs font-semibold transition-colors ${
              tab === t.id ? 'border-text text-text' : 'border-transparent text-muted hover:text-text'
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
          <SourcesPanel sources={detail.sources} pages={detail.pages} found={detail.found_by} />
        ) : tab === 'related' ? (
          <RelatedContracts related={detail.related} />
        ) : (
          <RulesPanel marketId={marketId} rules={detail.rules} queries={detail.queries} />
        )}
      </div>
    </div>
  )
}
