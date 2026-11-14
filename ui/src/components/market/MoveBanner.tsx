import { useEffect, useState } from 'react'
import { focusTick } from '../../lib/focus'
import type { Move } from '../../lib/types'
import { useStore } from '../../state/store'
import { MoveSpan, MoveStory } from './MovesPanel'

const SHOWN_MS = 9000
const ANSWER_MS = 1400
const LEAVE_MS = 220 // the length of .soft-out

/**
 * A price move on the market on screen, just explained (a jump, or the last day when asked): the question lands first, the answer a beat later,
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
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    const a = setTimeout(() => setAnswered(true), ANSWER_MS)
    const out = setTimeout(() => setLeaving(true), SHOWN_MS - LEAVE_MS)
    const b = setTimeout(clear, SHOWN_MS)
    return () => {
      clearTimeout(a)
      clearTimeout(out)
      clearTimeout(b)
    }
  }, [clear])

  const open = () => {
    setTab('moves')
    const item = move.cause ?? move.closest
    if (item) focusTick(item.id)
    clear()
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={open}
      onKeyDown={(e) => {
        if (e.key !== 'Enter' && e.key !== ' ') return
        e.preventDefault()
        e.stopPropagation() // Space is also the mic's key
        open()
      }}
      title="Show it under the chart"
      className={`${leaving ? 'soft-out' : 'slide-in'} absolute left-1/2 top-3 z-20 flex w-[min(34rem,calc(100%-2rem))] -translate-x-1/2 cursor-pointer flex-col gap-1 rounded border border-line bg-panel-2/95 px-4 py-2.5 text-left shadow-xl`}
    >
      <span className="flex items-baseline gap-3">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">Why did it move?</span>
        <MoveSpan move={move} className="text-lg" />
      </span>
      {!answered ? (
        <span className="relative h-4 overflow-hidden rounded bg-line/60">
          <span className="scan absolute inset-y-0 w-1/3 bg-accent/40" />
        </span>
      ) : (
        <span className="fade-in text-sm">
          <MoveStory move={move} />
        </span>
      )}
    </div>
  )
}
