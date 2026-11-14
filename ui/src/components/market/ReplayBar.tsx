import { useEffect } from 'react'
import { useNow } from '../../hooks/useNow'
import { pct } from '../../lib/format'
import { WINDOW_SECONDS } from '../../lib/lifecycle'
import { playReplay, stopReplay, tally } from '../../lib/replay'
import type { MarketSummary, Replay } from '../../lib/types'
import { useStore } from '../../state/store'

/**
 * The punchline, over the chart, when a replay has played to its end: how the market resolved, how far
 * the price travelled, and how the calls did. It leaves on a click, after a while, or with the next replay.
 */
export function ReplayResult({ market, replay }: { market: MarketSummary; replay: Replay }) {
  const shown = useStore((s) => s.replayDone === market.id)
  const ticks = useStore((s) => s.ticks[market.id])
  const prices = useStore((s) => s.prices[market.id])
  useEffect(() => {
    if (!shown) return
    const timer = setTimeout(() => useStore.setState({ replayDone: null }), 12_000)
    return () => clearTimeout(timer)
  }, [shown])
  if (!shown || !prices?.length) return null
  const score = tally(ticks, prices, replay.end + WINDOW_SECONDS)
  const moved = score.followed + score.against
  const calls = moved + score.flat
  return (
    <button
      type="button"
      onClick={() => useStore.setState({ replayDone: null })}
      title="Dismiss"
      className="pop-in absolute left-1/2 top-1/2 z-20 max-h-[calc(100%-0.5rem)] w-[min(32rem,94%)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xs border border-line bg-panel/95 px-5 py-3.5 text-center shadow-2xl"
    >
      <p className="flex items-center justify-center gap-3">
        <span className="tag-replay">REPLAY</span>
        <span className="label">Resolved</span>
        <span className="board text-4xl text-text">{replay.outcome === 'yes' ? 'Yes' : 'No'}</span>
        <span className="num text-sm text-muted">
          {pct(prices[0].price)} → {pct(prices[prices.length - 1].price)} in {Math.round((replay.end - replay.start) / 3600)} hours
        </span>
      </p>
      {/* the same terms and the same full counts as the live record, which these calls are never added to */}
      <p className="mt-2.5 text-sm font-medium leading-snug text-text">
        Directional follow-through: of <span className="num font-semibold">{moved}</span> {moved === 1 ? 'call' : 'calls'} followed by a
        qualifying price move, <span className="num font-semibold">{score.followed}</span> moved in the predicted direction.
      </p>
      <p className="num mt-1.5 text-xs text-muted">
        {score.against} opposite · {score.flat} no qualifying move · {calls} calls in this replay
      </p>
      <p className="mt-1.5 text-xs leading-snug text-muted">
        Prerecorded, and kept apart from the live record. Association with later price movement, not proof of cause.
      </p>
    </button>
  )
}

function when(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function Count({ n, label, title }: { n: number; label: string; title?: string }) {
  return (
    <span title={title} className="whitespace-nowrap">
      <span className="num font-semibold text-text">{n}</span> {label}
    </span>
  )
}

/**
 * A finished market, played back: the button, the replay's clock and how far through it is, and the
 * scoreboard of the calls so far. Everything here is told as of the replay's time (see useNow), so
 * while it plays the outcome stays unsaid.
 */
export function ReplayBar({ market, replay }: { market: MarketSummary; replay: Replay }) {
  const playing = useStore((s) => s.replay?.id === market.id)
  const ticks = useStore((s) => s.ticks[market.id])
  const prices = useStore((s) => s.prices[market.id])
  const now = useNow()
  // leaving the market mid-replay ends it: the next visit starts from the whole of it
  useEffect(() => () => stopReplay(), [])

  const done = Math.min(1, Math.max(0, (now - replay.start) / (replay.end - replay.start)))
  const score = tally(ticks, prices, now)
  const calls = score.followed + score.against + score.flat + score.open
  const hours = Math.round((replay.end - replay.start) / 3600)
  const rule = `A call is judged by the price ${WINDOW_SECONDS / 60} minutes after it, like every call on the tape.`

  return (
    <div className="border-b border-line bg-panel-2/60 px-5 py-2.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="tag-replay" title="A finished market played back from stored data: prerecorded, not live">
          REPLAY
        </span>
        <button
          type="button"
          onClick={() => (playing ? stopReplay() : void playReplay(market.id))}
          title={playing ? 'Stop and show the whole of it (Space)' : 'Play it back from the start (Space)'}
          className={`press btn ${playing ? '' : 'btn-solid'}`}
        >
          {playing ? '■ Stop' : '▶ Replay'}
        </button>
        <span className="num text-sm text-text" aria-live="off">
          {when(playing ? now : replay.end)}
        </span>
        <span
          className="text-xs text-muted"
          title={`The last ${hours} hours of a finished market: its real prices, and what people posted as it happened. Each post was scored knowing only what was known at that minute: the date, the price then and the posts before it, nothing later.`}
        >
          Prerecorded · no new API calls
        </span>
        <span className="flex basis-full flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted" title={rule}>
          <Count n={calls} label={calls === 1 ? 'call' : 'calls'} />
          <Count n={score.followed} label="✓ same direction" />
          <Count n={score.against} label="✗ opposite" />
          <Count n={score.flat} label="no qualifying move" />
          {score.open > 0 && <Count n={score.open} label="still open" title="Inside their 15 minutes" />}
          {!playing && (
            <span className="pop-in ml-auto rounded-xs bg-text px-1.5 text-xs font-semibold leading-5 text-bg">
              Resolved {replay.outcome === 'yes' ? 'Yes' : 'No'}
            </span>
          )}
        </span>
      </div>
      <div className="mt-2 h-0.5 overflow-hidden rounded bg-line" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(done * 100)}>
        <div className="h-full origin-left bg-text transition-transform duration-100 ease-linear" style={{ transform: `scaleX(${done})` }} />
      </div>
    </div>
  )
}
