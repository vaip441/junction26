import { useState } from 'react'
import type { MarketDetail } from '../../lib/types'
import { RelatedContracts } from './RelatedContracts'
import { RulesPanel } from './RulesPanel'
import { SourcesPanel } from './SourcesPanel'

type Tab = 'sources' | 'related' | 'rules'

/** Under the chart: where the ticks came from, the related contracts, and the rules. */
export function MarketTabs({ detail }: { detail: MarketDetail | undefined }) {
  const [tab, setTab] = useState<Tab>('sources')
  const tabs: { id: Tab; label: string; count?: number }[] = [
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
            onClick={() => setTab(t.id)}
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
        {!detail ? (
          <p className="p-3 text-xs text-faint">Loading…</p>
        ) : tab === 'sources' ? (
          <SourcesPanel sources={detail.sources} />
        ) : tab === 'related' ? (
          <RelatedContracts related={detail.related} />
        ) : (
          <RulesPanel rules={detail.rules} queries={detail.queries} />
        )}
      </div>
    </div>
  )
}
