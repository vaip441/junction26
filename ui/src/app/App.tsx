import { useEffect, type ReactNode } from 'react'
import { EmptyState } from '../components/common/EmptyState'
import { AskStrip, AskTakeover } from '../components/input/AskStage'
import { JudgePrompt } from '../components/input/JudgePrompt'
import { KeyPrompt } from '../components/input/KeyPrompt'
import { SpeakBar } from '../components/input/SpeakBar'
import { EdgeFlash } from '../components/layout/EdgeFlash'
import { MarketList } from '../components/layout/MarketList'
import { TopBar } from '../components/layout/TopBar'
import { MarketHeader } from '../components/market/MarketHeader'
import { MoveBanner } from '../components/market/MoveBanner'
import { MarketTabs } from '../components/market/MarketTabs'
import { PriceChart } from '../components/market/PriceChart'
import { RecordCard } from '../components/record/RecordCard'
import { RecordView } from '../components/record/RecordView'
import { Tape } from '../components/tape/Tape'
import { useSelectedMarket } from '../hooks/useMarket'
import { useAskShow } from '../hooks/useAskShow'
import { useHotkeys } from '../hooks/useHotkeys'
import { useRecord } from '../hooks/useRecord'
import { useStream } from '../hooks/useStream'
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
  useRecord()
  useAskShow()
  const { id, market, detail, ticks, prices } = useSelectedMarket()
  // a question fills the centre of the screen: the tape of the market behind it would only distract
  const asking = useStore((s) => s.ask != null && !s.ask.opened && !s.ask.error)
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
        className={`grid min-h-0 flex-1 grid-cols-1 gap-px bg-line max-lg:auto-rows-max max-lg:overflow-y-auto ${
          presentation ? 'lg:grid-cols-[1fr_minmax(0,0.75fr)]' : 'lg:grid-cols-[260px_1fr_380px]'
        }`}
      >
        {!presentation && (
          <div className="flex min-h-0 flex-col bg-panel">
            <Panel title="Markets" className="min-h-0 flex-1 max-lg:max-h-48">
              <MarketList />
            </Panel>
            <RecordCard />
          </div>
        )}

        <section className="relative flex min-h-0 flex-col bg-panel">
          <AskTakeover />
          {market && id ? (
            <>
              <MarketHeader market={market} />
              <div className="relative min-h-64 flex-1 p-4 max-lg:h-80 max-lg:flex-none">
                <PriceChart marketId={id} />
                {!market.made_up && <MoveBanner marketId={id} />}
                <AskStrip marketId={id} />
                {silent && (
                  <div className="absolute inset-0 z-10 flex items-center justify-center bg-panel p-6">
                    <JudgePrompt />
                  </div>
                )}
              </div>
              {!presentation && <MarketTabs marketId={id} madeUp={market.made_up} detail={detail} />}
              {market.made_up && <SpeakBar marketId={id} />}
            </>
          ) : (
            <EmptyState title="Pick a market">Or paste a link or ask a question in the bar above.</EmptyState>
          )}
        </section>

        <Panel title="Tape" className="max-lg:h-[36rem]">
          {asking ? (
            <EmptyState title="The tape fills as the terminal reads the web">Each item it scores lands here.</EmptyState>
          ) : id ? (
            <Tape ticks={ticks} prices={prices} madeUp={market?.made_up ?? false} pending={pending} />
          ) : (
            <EmptyState title="No market selected" />
          )}
        </Panel>
      </main>
      <EdgeFlash />
      <KeyPrompt />
      <RecordView />
    </div>
  )
}
