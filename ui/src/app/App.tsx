import { useEffect, type ReactNode } from 'react'
import { EmptyState } from '../components/common/EmptyState'
import { JudgePrompt } from '../components/input/JudgePrompt'
import { KeyPrompt } from '../components/input/KeyPrompt'
import { SpeakBar } from '../components/input/SpeakBar'
import { EdgeFlash } from '../components/layout/EdgeFlash'
import { MarketList } from '../components/layout/MarketList'
import { TopBar } from '../components/layout/TopBar'
import { MarketHeader } from '../components/market/MarketHeader'
import { PriceChart } from '../components/market/PriceChart'
import { Tape } from '../components/tape/Tape'
import { useSelectedMarket } from '../hooks/useMarket'
import { useHotkeys } from '../hooks/useHotkeys'
import { useStream } from '../hooks/useStream'
import { useVoiceCallout } from '../hooks/useVoiceCallout'
import { useStore } from '../state/store'

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
  useHotkeys()
  useVoiceCallout()
  const { id, market, ticks, prices } = useSelectedMarket()
  const pending = useStore((s) => (id ? s.pending[id] : undefined))
  const presentation = useStore((s) => s.presentation)
  // nobody has said anything to this made-up market yet: tell the judge to talk
  const silent = Boolean(market?.made_up && ticks && !ticks.some((t) => t.test) && !pending?.length)

  // presentation mode scales everything (all sizes are rem) and hides the market list
  useEffect(() => {
    document.documentElement.classList.toggle('presentation', presentation)
  }, [presentation])

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <main
        className={`grid min-h-0 flex-1 grid-cols-1 gap-px bg-line ${
          presentation ? 'lg:grid-cols-[1fr_minmax(0,0.75fr)]' : 'lg:grid-cols-[260px_1fr_380px]'
        }`}
      >
        {!presentation && (
          <Panel title="Markets" className="max-lg:max-h-56">
            <MarketList />
          </Panel>
        )}

        <section className="flex min-h-0 flex-col bg-panel">
          {market && id ? (
            <>
              <MarketHeader market={market} />
              <div className="relative min-h-64 flex-1 p-4">
                <PriceChart marketId={id} />
                {silent && (
                  <div className="absolute inset-0 flex items-center justify-center bg-panel/95 p-6">
                    <JudgePrompt />
                  </div>
                )}
              </div>
              {market.made_up && <SpeakBar marketId={id} />}
            </>
          ) : (
            <EmptyState title="Pick a market">Or paste a link or ask a question in the bar above.</EmptyState>
          )}
        </section>

        <Panel title="Tape">{id ? <Tape ticks={ticks} prices={prices} madeUp={market?.made_up ?? false} pending={pending} /> : <EmptyState title="No market selected" />}</Panel>
      </main>
      <EdgeFlash />
      <KeyPrompt />
    </div>
  )
}
