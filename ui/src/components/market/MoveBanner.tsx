import { useEffect, useState } from 'react'
import { focusTick } from '../../lib/focus'
import { shortSource } from '../../lib/sources'
import type { Move } from '../../lib/types'
import { useStore } from '../../state/store'
import { SourceIcon } from '../common/SourceIcon'
import { MoveSpan } from './MovesPanel'

const SHOWN_MS = 9000
const ANSWER_MS = 1400

/**
 * A price jump on the market on screen, just explained: the question lands first, the answer a beat later,
 * so it reads as the terminal answering. The backend sends the move only once it has searched the web, so
 * both halves are already here; the pause is ours.
 */
export function MoveBanner({ marketId }: { marketId: string }) {
  const move = useStore((s) => (s.liveMove?.market_id === marketId ? s.liveMove : null))
  if (!move || document.hidden) return null
  return <Banner key={move.id} move={move} /> // a new move starts over, question first
}

function Banner({ move }: { move: Move }) {
  const clear = useStore((s) => s.clearLiveMove)
  const setTab = useStore((s) => s.setTab)
  const [answered, setAnswered] = useState(false)

  useEffect(() => {
    const a = setTimeout(() => setAnswered(true), ANSWER_MS)
    const b = setTimeout(clear, SHOWN_MS)
    return () => {
      clearTimeout(a)
      clearTimeout(b)
    }
  }, [clear])

  return (
    <button
      onClick={() => {
        setTab('moves')
        if (move.cause) focusTick(move.cause.id)
        clear()
      }}
      title="Show it under the chart"
      className="slide-in absolute left-1/2 top-3 z-20 flex w-[min(34rem,calc(100%-2rem))] -translate-x-1/2 flex-col gap-1 rounded border border-line bg-panel-2/95 px-4 py-2.5 text-left shadow-xl"
    >
      <span className="flex items-baseline gap-3">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">Why did it move?</span>
        <MoveSpan move={move} className="text-lg" />
      </span>
      {!answered ? (
        <span className="relative h-4 overflow-hidden rounded bg-line/60">
          <span className="scan absolute inset-y-0 w-1/3 bg-accent/40" />
        </span>
      ) : move.cause ? (
        <span className="fade-in flex min-w-0 flex-col gap-0.5">
          <span className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted">
            likely cause{move.confidence != null && <span className="num">{Math.round(move.confidence * 100)}%</span>}
            <SourceIcon source={move.cause.source} className="h-3 w-3" />
            <span className="truncate">{shortSource(move.cause.source)}</span>
          </span>
          <span className="line-clamp-2 text-sm leading-snug text-text">{move.cause.headline}</span>
          {move.rule && <span className="line-clamp-1 text-[11px] italic text-muted">§ “{move.rule.text}”</span>}
        </span>
      ) : (
        <span className="fade-in text-sm text-muted">No cause found on the web</span>
      )}
    </button>
  )
}
