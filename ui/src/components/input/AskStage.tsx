import { useEffect, useRef, useState, type ReactNode } from 'react'
import { pct } from '../../lib/format'
import type { FoundMarket, MarketEvent } from '../../lib/types'
import { useStore, type Ask, type Meter } from '../../state/store'
import { VenueBadge } from '../common/Badge'

function last(steps: MarketEvent[], status: string): MarketEvent | undefined {
  return [...steps].reverse().find((s) => s.status === status)
}

/** Seconds since the question was asked, to a tenth, stopping when the search finished. */
function useElapsed(ask: Ask): number {
  const [now, setNow] = useState(() => Date.now() / 1000)
  const running = ask.finished == null && !ask.error
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now() / 1000), 100)
    return () => clearInterval(timer)
  }, [running])
  return Math.max(0, (ask.finished ?? now) - ask.started)
}

/** A whole number that glides to each new value instead of jumping. Lands on the value even where frames are paused. */
function Tween({ value }: { value: number }) {
  const [shown, setShown] = useState(value)
  const from = useRef(value)
  useEffect(() => {
    const start = from.current
    if (start === value) return
    const began = performance.now()
    let frame = 0
    const step = (t: number) => {
      const p = Math.min(1, (t - began) / 450)
      from.current = Math.round(start + (value - start) * (1 - (1 - p) ** 3))
      setShown(from.current)
      if (p < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    const land = setTimeout(() => {
      from.current = value
      setShown(value)
    }, 500)
    return () => {
      cancelAnimationFrame(frame)
      clearTimeout(land)
    }
  }, [value])
  return <>{shown}</>
}

function Spinner() {
  return <span className="inline-block h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-accent border-t-transparent align-[-1px]" />
}

function Clock({ seconds, className = '' }: { seconds: number; className?: string }) {
  return (
    <span className={`num shrink-0 font-bold text-text ${className}`}>
      {seconds.toFixed(1)}
      <span className="ml-1 text-[0.6em] font-normal text-muted">s</span>
    </span>
  )
}

/** Context.dev doing the work: credits spent on this question so far, and requests in the last minute. */
function ContextMeter({ meter, live, compact = false }: { meter: Meter | null; live: boolean; compact?: boolean }) {
  if (!meter) return null
  return (
    <span className="soft-in flex shrink-0 items-center gap-2 text-xs text-muted">
      <span className={`h-1.5 w-1.5 rounded-full bg-accent ${live ? 'animate-pulse' : ''}`} />
      Context.dev
      {meter.credits != null && (
        <span>
          <span className="num font-semibold text-text">
            <Tween value={meter.credits} />
          </span>{' '}
          credits
        </span>
      )}
      {(!compact || meter.credits == null) && (
        <span>
          <span className="num font-semibold text-text">
            <Tween value={meter.perMinute} />
          </span>{' '}
          {meter.perMinute === 1 ? 'request' : 'requests'} this minute
        </span>
      )}
    </span>
  )
}

/** One market found for the question. The picked one lifts out; the others step back. */
function MarketCard({ card, index, state, picked }: { card: FoundMarket; index: number; state: 'open' | 'picked' | 'passed'; picked?: MarketEvent }) {
  return (
    <li
      className={`rise-in flex flex-col gap-2 rounded border bg-panel-2 p-3 transition-[opacity,border-color,box-shadow,transform] duration-500 ${
        state === 'picked' ? 'border-accent shadow-[0_0_0_1px_var(--color-accent)] lg:-translate-y-1' : state === 'passed' ? 'border-line opacity-35' : 'border-line'
      }`}
      style={{ animationDelay: `${index * 110}ms` }}
    >
      <div className="flex items-center justify-between gap-2">
        <VenueBadge venue={card.venue} />
        <span className="num text-xl font-bold text-text">{pct(state === 'picked' && picked?.price != null ? picked.price : card.price)}</span>
      </div>
      <p className="line-clamp-2 text-sm leading-snug text-text">{state === 'picked' && picked?.title ? picked.title : card.title}</p>
      <p className="text-[11px] text-faint">
        {state === 'picked' ? (
          <span className="font-semibold uppercase tracking-wider text-accent">Picked</span>
        ) : (
          <>
            <span className="num">{card.contracts}</span> {card.contracts === 1 ? 'contract' : 'contracts'}
          </>
        )}
      </p>
    </li>
  )
}

/**
 * A question just asked takes the centre of the screen until its market is picked: the judge's own words,
 * large, a running clock, the markets found as cards, and the one picked lifting out. Then it fades and
 * the market opens underneath.
 */
export function AskTakeover() {
  const ask = useStore((s) => s.ask)
  if (!ask || ask.uncovered) return null
  return <Takeover ask={ask} />
}

function Takeover({ ask }: { ask: Ask }) {
  const meter = useStore((s) => s.meter)
  const clear = useStore((s) => s.clearAsk)
  const seconds = useElapsed(ask)
  const isLink = /^https?:\/\//i.test(ask.query)
  const found = last(ask.steps, 'found contracts')
  const picked = last(ask.steps, 'picked')
  const tracked = ask.marketId != null
  const cards = found?.contracts ?? []

  let line: ReactNode
  if (ask.error) {
    line = <span className="text-down">{ask.error}</span>
  } else if (isLink) {
    line = tracked ? <>Found it on the venue</> : <><Spinner /> Reading the link</>
  } else if (!found) {
    line = <><Spinner /> Searching Kalshi and Polymarket</>
  } else if (found.count === 0) {
    line = tracked ? <>No market asks this, so the terminal made one</> : <><Spinner /> No market asks this. Writing one.</>
  } else if (!picked && !tracked) {
    line = (
      <>
        <Spinner /> Found <span className="num font-semibold text-text">{found.count}</span> {found.count === 1 ? 'market' : 'markets'}. Picking the one that asks
        this.
      </>
    )
  } else {
    line = <>Picked the market that asks this</>
  }

  return (
    <div className={`absolute inset-0 z-30 flex flex-col justify-center gap-6 bg-panel p-8 lg:p-12 ${ask.opened ? 'soft-out' : 'soft-in'}`}>
      <div className="flex items-baseline justify-between gap-4">
        <span className="text-[11px] font-semibold uppercase tracking-[0.3em] text-muted">{isLink ? 'Reading a link' : 'Asking'}</span>
        <Clock seconds={seconds} className="text-2xl" />
      </div>
      <p className={`rise-in font-semibold leading-tight text-text ${isLink ? 'break-all text-xl' : 'text-3xl lg:text-4xl'}`}>
        {isLink ? ask.query : `“${ask.query}”`}
      </p>
      {/* keyed by its text, so each new line fades in over the last */}
      <p key={ask.error ? 'error' : `${Boolean(found)}${Boolean(picked)}${tracked}`} className="soft-in flex items-center gap-2.5 text-lg text-muted">
        {line}
        {ask.error && (
          <button onClick={clear} className="ml-2 text-sm text-muted underline hover:text-text">
            close (Esc)
          </button>
        )}
      </p>
      {cards.length > 0 && (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {cards.map((c, i) => (
            <MarketCard
              key={`${c.venue}${c.title}${i}`}
              card={c}
              index={i}
              picked={picked}
              state={picked?.winner == null ? 'open' : picked.winner === i ? 'picked' : 'passed'}
            />
          ))}
        </ul>
      )}
      {!ask.error && <ContextMeter meter={meter} live />}
    </div>
  )
}

/**
 * Once the asked market is open: a strip over its chart that says what the terminal is doing (the phrases
 * it searches with, how much it found, items landing on the tape as they
 * are scored), and ends on one line that sums the search up.
 */
export function AskStrip({ marketId }: { marketId: string }) {
  const ask = useStore((s) => (s.ask?.marketId === marketId && s.ask.opened ? s.ask : null))
  if (!ask) return null
  return <Strip ask={ask} marketId={marketId} />
}

function Strip({ ask, marketId }: { ask: Ask; marketId: string }) {
  const meter = useStore((s) => s.meter)
  const clear = useStore((s) => s.clearAsk)
  const ticks = useStore((s) => s.ticks[marketId])
  const price = useStore((s) => s.markets[marketId]?.price)
  const seconds = useElapsed(ask)
  const sourcing = last(ask.steps, 'finding sources')
  const scoring = last(ask.steps, 'scoring')
  const done = ask.finished != null
  const onTape = ticks?.length ?? 0
  const calls = (ticks ?? []).filter((t) => t.verdict !== 'none').length
  const n = (v: ReactNode) => <span className="num font-bold text-text">{v}</span>

  const phase = done ? 'done' : scoring ? 'scoring' : sourcing ? 'reading' : 'phrases'
  let body: ReactNode
  if (phase === 'done') {
    body = (
      <p className="text-base leading-snug text-muted">
        {scoring?.found != null ? (
          <>
            Read {n(scoring.found)} items in {n(Math.round(seconds))} seconds. {n(onTape)} made the tape, {n(calls)} {calls === 1 ? 'is a call' : 'are calls'}.{' '}
          </>
        ) : (
          <>
            {n(onTape)} {onTape === 1 ? 'item' : 'items'} on the tape, {n(calls)} {calls === 1 ? 'call' : 'calls'}.{' '}
          </>
        )}
        {price != null && (
          <>
            {ask.matched === false ? 'Starting odds' : 'Market says'} {n(pct(price))}.
          </>
        )}
      </p>
    )
  } else if (phase === 'scoring') {
    body = (
      <p className="text-sm text-muted">
        <Spinner /> <span className="ml-1.5">Found</span> {n(scoring?.found ?? 0)} items. Scoring each one.{' '}
        <span className="ml-1 whitespace-nowrap text-text">
          {n(<Tween value={onTape} />)} on the tape
        </span>
      </p>
    )
  } else {
    body = (
      <p className="text-sm text-muted">
        <Spinner />{' '}
        <span className="ml-1.5">
          {ask.matched === false && 'No market asked this, so the terminal made one. '}
          {phase === 'reading' ? 'Reading the web: news, posts, filings' : 'Writing what to search the web for'}
        </span>
      </p>
    )
  }

  const queries = sourcing?.queries ?? []
  return (
    <div className="rise-in absolute left-4 right-4 top-3 z-20 overflow-hidden rounded border border-line bg-panel-2/95 shadow-xl backdrop-blur-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-2.5">
        <div key={phase} className="soft-in min-w-0 flex-1">
          {body}
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-4">
          {!done && <Clock seconds={seconds} className="text-sm" />}
          <ContextMeter meter={meter} live={!done} compact />
          <button onClick={clear} className="text-xs text-muted hover:text-text" title="Close (Esc)">
            ✕
          </button>
        </div>
      </div>
      {!done && queries.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 px-4 pb-2.5">
          <span className="soft-in text-[10px] font-semibold uppercase tracking-wider text-faint">Searching for</span>
          {queries.map((q, i) => (
            <span key={q} className="rise-in rounded border border-line bg-bg px-2 py-0.5 text-xs text-text" style={{ animationDelay: `${i * 120}ms` }}>
              {q}
            </span>
          ))}
        </div>
      )}
      {!done && (
        <div className="relative h-0.5 overflow-hidden bg-line">
          <span className="scan absolute inset-y-0 w-1/3 bg-accent/70" />
        </div>
      )}
    </div>
  )
}
