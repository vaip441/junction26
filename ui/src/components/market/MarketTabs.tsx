import { useState, type ReactNode } from 'react'
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
 *
 * `flow`: on a narrow screen the panel is a view of its own. It takes the height of what it holds and
 * scrolls with the page, under tabs that stay at the top, instead of being a short box that scrolls inside.
 * Side by side it is a box under the chart whose height follows the screen's: at a fixed 11rem a tall screen
 * showed one and a half answers under 600px of chart. A short screen keeps it at 10rem, so the chart keeps
 * its room there.
 *
 * `trailing`: something for the far end of the row of tabs. In a column too narrow for both it takes a line
 * of its own under the tabs.
 */
export function MarketTabs({
  marketId,
  madeUp,
  detail,
  flow = false,
  trailing,
}: {
  marketId: string
  madeUp: boolean
  detail: MarketDetail | undefined
  flow?: boolean
  trailing?: ReactNode
}) {
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
    <div className={flow ? 'flex flex-col' : 'flex h-[clamp(10rem,calc(45vh-12rem),20rem)] shrink-0 flex-col border-t border-line'}>
      <div className={flow ? 'contents' : 'flex shrink-0 flex-wrap'}>
      <div
        role="tablist"
        className={`flex shrink-0 border-b border-line px-3 ${flow ? 'sticky top-0 z-10 gap-4 overflow-x-auto bg-panel [scrollbar-width:none]' : 'min-w-max flex-1 gap-5'}`}
      >
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => {
              setPicked(true)
              setTab(t.id)
            }}
            className={`-mb-px shrink-0 whitespace-nowrap border-b-2 text-xs font-semibold transition-colors ${flow ? 'py-3' : 'py-2'} ${
              tab === t.id ? 'border-text text-text' : 'border-transparent text-muted hover:text-text'
            }`}
          >
            {t.label}
            {t.count != null && t.count > 0 && <span className="num ml-1 font-normal text-faint">{t.count}</span>}
          </button>
        ))}
      </div>
      {trailing && <span className="flex flex-1 items-center justify-end border-b border-line px-3 py-1">{trailing}</span>}
      </div>
      <div className={flow ? '' : 'min-h-0 flex-1 overflow-y-auto'}>
        {tab === 'moves' ? (
          <MovesPanel marketId={marketId} moves={moves} />
        ) : !detail ? (
          <p className="p-3 text-xs text-faint">Loading…</p>
        ) : tab === 'sources' ? (
          <SourcesPanel sources={detail.sources} pages={detail.pages} searched={detail.poll_seconds > 0} />
        ) : tab === 'related' ? (
          <RelatedContracts related={detail.related} />
        ) : (
          <RulesPanel marketId={marketId} rules={detail.rules} queries={detail.queries} />
        )}
      </div>
    </div>
  )
}
