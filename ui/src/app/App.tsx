import type { ReactNode } from 'react'
import { EmptyState } from '../components/common/EmptyState'
import { MarketList } from '../components/layout/MarketList'
import { TopBar } from '../components/layout/TopBar'
import { MarketHeader } from '../components/market/MarketHeader'
import { PriceChart } from '../components/market/PriceChart'
import { Tape } from '../components/tape/Tape'
import { useSelectedMarket } from '../hooks/useMarket'
import { useStream } from '../hooks/useStream'

function Panel({ title, children, className = '' }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`flex min-h-0 flex-col bg-panel ${className}`}>
      <h2 className="shrink-0 border-b border-line px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
        {title}
      </h2>
      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
    </section>
  )
}

export function App() {
  useStream()
  const { id, market, ticks } = useSelectedMarket()

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <main className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-line lg:grid-cols-[260px_1fr_380px]">
        <Panel title="Markets" className="max-lg:max-h-56">
          <MarketList />
        </Panel>

        <section className="flex min-h-0 flex-col bg-panel">
          {market && id ? (
            <>
              <MarketHeader market={market} />
              <div className="min-h-64 flex-1 p-4">
                <PriceChart marketId={id} />
              </div>
            </>
          ) : (
            <EmptyState title="Pick a market">Or paste a link or ask a question in the bar above.</EmptyState>
          )}
        </section>

        <Panel title="Tape">{id ? <Tape ticks={ticks} /> : <EmptyState title="No market selected" />}</Panel>
      </main>
    </div>
  )
}
