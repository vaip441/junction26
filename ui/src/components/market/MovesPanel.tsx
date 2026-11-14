import { useState } from 'react'
import { askWhy } from '../../lib/actions'
import { absoluteTime, pct, pts, timeAgo } from '../../lib/format'
import { focusTick } from '../../lib/focus'
import { shortSource } from '../../lib/sources'
import type { Move } from '../../lib/types'
import { useStore } from '../../state/store'
import { SourceIcon } from '../common/SourceIcon'

/** "24% → 20%" in the move's colour: a move is an up or a down, so it takes the verdict colours. */
export function MoveSpan({ move, className = '' }: { move: Move; className?: string }) {
  return (
    <span className={`num font-bold ${move.to >= move.from ? 'text-up' : 'text-down'} ${className}`}>
      {pct(move.from)} → {pct(move.to)}
    </span>
  )
}

/**
 * What stands behind a move, said the way the backend means it: an item taken as the reason is the "likely
 * cause" (with the rules sentence it touches); otherwise the nearest item is only the "closest news", and
 * the related contracts that moved at the same time are named, which is often the whole story.
 */
export function MoveStory({ move, onRule }: { move: Move; onRule?: () => void }) {
  const item = move.explained ? move.cause : move.closest
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <p className="text-text">{move.summary}</p>
      {!move.explained && move.related.length > 0 && (
        <p className="flex flex-wrap gap-x-3 text-[11px] text-muted">
          {move.related.map((r) => (
            <span key={r.id} className="min-w-0 truncate">
              {r.title} <span className={`num ${r.to >= r.from ? 'text-up' : 'text-down'}`}>{pts(r.to - r.from)}</span>
            </span>
          ))}
        </p>
      )}
      {item && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            focusTick(item.id)
          }}
          title="Find it on the tape"
          className="flex min-w-0 items-center gap-1.5 text-left text-[11px] text-faint hover:text-text"
        >
          <span className="shrink-0 font-semibold uppercase tracking-wider">{move.explained ? 'Likely cause' : 'Closest news'}</span>
          <SourceIcon source={item.source} className="h-3 w-3" />
          <span className="truncate">
            {shortSource(item.source)}
            {!move.explained && `: ${item.headline}`}
          </span>
        </button>
      )}
      {move.rule && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onRule?.()
          }}
          title="Show it in the rules"
          className="line-clamp-1 text-left text-[11px] italic text-muted hover:text-text"
        >
          § “{move.rule.text}”
        </button>
      )}
    </div>
  )
}

/**
 * "Why did it move?": the market's price moves, newest first, each in one sentence. Most jumps are trades
 * on a thin market, not news, and the list says so. The button asks the same of the market's last day, at
 * any time: the terminal searches the web now and answers in a few seconds.
 */
export function MovesPanel({ marketId, moves }: { marketId: string; moves: Move[] | undefined }) {
  const showRule = useStore((s) => s.showRule)
  const [state, setState] = useState<{ busy: boolean; note: string | null }>({ busy: false, note: null })

  const ask = async () => {
    setState({ busy: true, note: null })
    setState({ busy: false, note: await askWhy(marketId) })
  }

  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-3 border-b border-line px-3 py-1.5">
        <button
          onClick={ask}
          disabled={state.busy}
          className="shrink-0 rounded border border-line px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted hover:border-accent hover:text-text disabled:opacity-50"
        >
          {state.busy ? 'Searching the web…' : 'Explain today’s move'}
        </button>
        <span className={`min-w-0 truncate text-[11px] ${state.note ? 'text-down' : 'text-faint'}`}>
          {state.note ?? 'Why did this market move over the last day? Asked now, answered in a few seconds.'}
        </span>
      </div>
      {moves === undefined ? (
        <p className="p-3 text-xs text-faint">Loading…</p>
      ) : moves.length === 0 ? (
        <p className="p-3 text-xs leading-relaxed text-muted">
          No moves yet. When the price jumps 3 points within 10 minutes, the terminal searches the web at once and says here what, if anything,
          explains it.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {moves.map((m) => (
            <li key={m.id} id={`move-${m.id}`} className="grid grid-cols-[7.5rem_1fr] gap-x-3 px-3 py-2 text-xs">
              <div className="flex flex-col gap-0.5">
                <MoveSpan move={m} className="text-sm" />
                <span className="text-[10px] text-faint" title={`${absoluteTime(m.since)} to ${absoluteTime(m.ts)}`}>
                  {m.asked ? 'the last day' : timeAgo(m.ts)}
                </span>
              </div>
              <MoveStory move={m} onRule={() => m.rule && showRule(m.rule)} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
