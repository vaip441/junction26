import { useLayoutEffect, useRef, type ReactNode } from 'react'
import { EmptyState } from '../components/common/EmptyState'
import { AskStrip, AskTakeover } from '../components/input/AskStage'
import { JudgePrompt } from '../components/input/JudgePrompt'
import { KeyPrompt } from '../components/input/KeyPrompt'
import { SpeakBar } from '../components/input/SpeakBar'
import { BottomNav } from '../components/layout/BottomNav'
import { EdgeFlash } from '../components/layout/EdgeFlash'
import { MarketList } from '../components/layout/MarketList'
import { ReadingStrip } from '../components/layout/ReadingStrip'
import { TopBar } from '../components/layout/TopBar'
import { DEMO_ID, MarketHeader, Remove } from '../components/market/MarketHeader'
import { MoveBanner } from '../components/market/MoveBanner'
import { MarketTabs } from '../components/market/MarketTabs'
import { PriceChart } from '../components/market/PriceChart'
import { ReplayBar, ReplayResult } from '../components/market/ReplayBar'
import { RecordCard } from '../components/record/RecordCard'
import { RecordView } from '../components/record/RecordView'
import { Tape } from '../components/tape/Tape'
import { useSelectedMarket } from '../hooks/useMarket'
import { useAskShow } from '../hooks/useAskShow'
import { useHotkeys } from '../hooks/useHotkeys'
import { useMedia } from '../hooks/useMedia'
import { useRecord } from '../hooks/useRecord'
import { useStream } from '../hooks/useStream'
import { NARROW } from '../lib/device'
import { useStore, type PendingTick, type View } from '../state/store'

function Panel({ title, children, className = '' }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`flex min-h-0 flex-col bg-panel ${className}`}>
      <h2 className="label shrink-0 border-b border-line px-3 py-2">{title}</h2>
      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
    </section>
  )
}

/** What both layouts are drawn from: the picked market and what is known about it. */
type Shown = ReturnType<typeof useSelectedMarket> & {
  /** A question fills the centre of the screen: the tape of the market behind it would only distract. */
  asking: boolean
  pending: PendingTick[] | undefined
  /** Nobody has said anything to this made-up market yet, and it has no chart to show: tell the judge to talk. */
  silent: boolean
}

/** What sits over the chart: the banner of a move just explained, a replay's result, the search strip, the prompt to talk. */
function OverChart({ id, market, silent }: Pick<Shown, 'silent'> & { id: string; market: NonNullable<Shown['market']> }) {
  return (
    <>
      {!market.made_up && <MoveBanner marketId={id} />}
      {market.replay && <ReplayResult market={market} replay={market.replay} />}
      <AskStrip marketId={id} />
      {silent && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-panel p-6">
          <JudgePrompt />
        </div>
      )}
    </>
  )
}

/** A wide screen: the markets, the picked market and its tape side by side, each column scrolling on its own. */
function Columns({ id, market, detail, ticks, prices, asking, pending, silent }: Shown) {
  return (
    // the middle column may shrink below what it holds: left at `1fr`, a window under about 1220px wide kept
    // it at its full width and pushed half of the tape off the right edge of the screen
    <main className="grid min-h-0 flex-1 grid-cols-[260px_minmax(0,1fr)_380px] gap-px bg-line">
      <div className="flex min-h-0 flex-col bg-panel">
        <Panel title="Markets" className="min-h-0 flex-1">
          <MarketList />
        </Panel>
        <RecordCard />
      </div>

      <section className="relative flex min-h-0 flex-col bg-panel">
        <AskTakeover />
        {market && id ? (
          <>
            <MarketHeader market={market} />
            {market.replay && <ReplayBar key={id} market={market} replay={market.replay} />}
            <div className="relative min-h-64 flex-1 p-4">
              <PriceChart marketId={id} />
              <OverChart id={id} market={market} silent={silent} />
            </div>
            <MarketTabs marketId={id} madeUp={market.made_up || Boolean(market.replay)} detail={detail} />
            {market.made_up && <SpeakBar marketId={id} />}
          </>
        ) : (
          <EmptyState title="Pick a market">Or paste a link or ask a question in the bar above.</EmptyState>
        )}
      </section>

      <Panel title="Tape">
        {asking ? (
          <EmptyState title="The tape fills as the terminal reads the web">Each item it scores lands here.</EmptyState>
        ) : id ? (
          <Tape ticks={ticks} prices={prices} madeUp={market?.made_up ?? false} pending={pending} />
        ) : (
          <EmptyState title="No market selected" />
        )}
      </Panel>
    </main>
  )
}

/** The name of a part of a view: it stays at the top while what it names scrolls under it. */
function Heading({ children }: { children: ReactNode }) {
  return <h2 className="label sticky top-0 z-10 border-b border-line bg-panel px-3 py-2">{children}</h2>
}

/**
 * A narrow screen: one view at a time (see BottomNav), and one thing that scrolls. Stacked, the three
 * columns were three boxes that each scrolled inside a page that scrolled too, so a finger moved whichever
 * it happened to land on. Here the question and its price stay above the page, the bar of views under it,
 * and everything between them is one page: nothing in it scrolls on its own.
 */
function OneView({ id, market, detail, ticks, prices, asking, pending, silent }: Shown) {
  const view = useStore((s) => s.view)
  // a question being asked covers the page: the market behind it is not what the header should name
  const covered = useStore((s) => s.ask != null && !s.ask.uncovered)
  const page = useRef<HTMLElement>(null)
  const kept = useRef<Record<View, number>>({ markets: 0, live: 0, details: 0 })
  const last = useRef(id)

  // The views share the one page, so each is put back where it was left; another market starts at its top.
  useLayoutEffect(() => {
    if (last.current !== id) {
      last.current = id
      kept.current.live = 0
      kept.current.details = 0
    }
    if (page.current) page.current.scrollTop = kept.current[view]
  }, [view, id])

  let shown: ReactNode
  if (view === 'markets') {
    shown = (
      <div className="flex min-h-full flex-col">
        <Heading>Markets</Heading>
        <div className="flex-1">
          <MarketList />
        </div>
        <RecordCard compact />
      </div>
    )
  } else if (!market || !id) {
    shown = <EmptyState title="Pick a market">Or paste a link or ask a question in the bar above.</EmptyState>
  } else if (view === 'live') {
    shown = (
      <>
        {market.replay && <ReplayBar key={id} market={market} replay={market.replay} />}
        {/* tall enough to read, short enough that the top of the tape shows under it */}
        <div className="relative h-[clamp(16rem,42dvh,21rem)] px-2 pb-1 pt-2">
          <PriceChart marketId={id} />
          <OverChart id={id} market={market} silent={silent} />
        </div>
        {market.made_up && <SpeakBar marketId={id} />}
        <section className="border-t border-line">
          <Heading>Tape</Heading>
          {asking ? (
            <EmptyState title="The tape fills as the terminal reads the web">Each item it scores lands here.</EmptyState>
          ) : (
            <Tape ticks={ticks} prices={prices} madeUp={market.made_up} pending={pending} />
          )}
        </section>
      </>
    )
  } else {
    shown = (
      <>
        <MarketTabs marketId={id} madeUp={market.made_up || Boolean(market.replay)} detail={detail} flow />
        {!market.replay && id !== DEMO_ID && (
          <div className="flex justify-end border-t border-line p-3">
            <Remove key={id} marketId={id} />
          </div>
        )}
      </>
    )
  }

  return (
    <>
      {market && view !== 'markets' && !covered && <MarketHeader market={market} compact />}
      <div className="relative min-h-0 flex-1 bg-panel">
        <main
          ref={page}
          onScroll={(e) => (kept.current[view] = e.currentTarget.scrollTop)}
          className="absolute inset-0 overflow-y-auto"
        >
          {shown}
        </main>
        <AskTakeover />
      </div>
      <BottomNav onAgain={() => page.current?.scrollTo({ top: 0, behavior: 'smooth' })} />
    </>
  )
}

export function App() {
  useStream()
  useHotkeys()
  useRecord()
  useAskShow()
  const narrow = useMedia(NARROW)
  const selected = useSelectedMarket()
  const { id, market, ticks, prices } = selected
  const asking = useStore((s) => s.ask != null && !s.ask.opened && !s.ask.error)
  const pending = useStore((s) => (id ? s.pending[id] : undefined))
  // A made-up market whose coverage drew it a chart shows the chart: the prompt used to cover it until
  // someone typed, so the news found for a question never showed as a line. One price is not a line yet.
  const charted = (prices?.length ?? 0) > 1
  const silent = Boolean(market?.made_up && ticks && !ticks.some((t) => t.test) && !pending?.length && !charted)
  const shown: Shown = { ...selected, asking, pending, silent }

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <ReadingStrip />
      {narrow ? <OneView {...shown} /> : <Columns {...shown} />}
      <EdgeFlash />
      <KeyPrompt />
      <RecordView />
    </div>
  )
}
