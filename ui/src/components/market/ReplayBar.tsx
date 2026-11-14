import { useEffect } from 'react'
import { useNow } from '../../hooks/useNow'
import { WINDOW_SECONDS } from '../../lib/lifecycle'
import { playReplay, stopReplay, tally } from '../../lib/replay'
import type { MarketSummary, Replay } from '../../lib/types'
import { useStore } from '../../state/store'

function when(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function Count({ n, label, title }: { n: number; label: string; title?: string }) {
  return (
    <span title={title} className="whitespace-nowrap">
      <span className="num text-sm font-semibold text-text">{n}</span> {label}
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
    <div className="border-b border-line bg-panel-2/60 px-4 py-2.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <button
          type="button"
          onClick={() => (playing ? stopReplay() : void playReplay(market.id))}
          title={playing ? 'Stop and show the whole of it (Space)' : 'Play it back from the start (Space)'}
          className="press num rounded border border-accent/60 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-accent hover:bg-accent/10"
        >
          {playing ? '■ Stop' : '▶ Replay'}
        </button>
        <span className="num text-sm text-text" aria-live="off">
          {when(playing ? now : replay.end)}
        </span>
        <span className="flex flex-wrap items-center gap-x-3 text-xs text-muted" title={rule}>
          <Count n={calls} label={calls === 1 ? 'call' : 'calls'} />
          <Count n={score.followed} label="✓ price followed" />
          <Count n={score.against} label="✗ went against" />
          <Count n={score.flat} label="no move" />
          {score.open > 0 && <Count n={score.open} label="still open" title="Inside their 15 minutes" />}
        </span>
        {!playing && (
          <span className="pop-in num ml-auto rounded border border-line px-2 py-0.5 text-xs font-semibold uppercase tracking-wider text-text">
            Resolved {replay.outcome === 'yes' ? 'Yes' : 'No'}
          </span>
        )}
      </div>
      <div className="mt-2 h-0.5 overflow-hidden rounded bg-line" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(done * 100)}>
        <div className="h-full origin-left bg-accent transition-transform duration-100 ease-linear" style={{ transform: `scaleX(${done})` }} />
      </div>
      <p className="mt-1.5 text-[11px] leading-snug text-faint">
        {playing
          ? 'Each post lands when it was posted. The model sees only what was known at that minute.'
          : `The last ${hours} hours of a finished market: its real prices, and what people posted as it happened. Each post was scored knowing only what was known at that minute.`}
      </p>
    </div>
  )
}
