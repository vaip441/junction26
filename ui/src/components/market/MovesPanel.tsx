import { useState } from 'react'
import { askWhy } from '../../lib/actions'
import { absoluteTime, pct, pts, timeAgo } from '../../lib/format'
import { focusTick } from '../../lib/focus'
import { causeLabel } from '../../lib/moves'
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

function minutes(seconds: number): string {
  const m = Math.max(1, Math.round(seconds / 60))
  return m >= 90 ? `${Math.round(m / 60)} h` : `${m} min`
}

/**
 * What stands behind a move, laid out our way from the backend's fields (its one-sentence `summary` is the
 * tooltip): an item taken as the reason is the likely or possible cause, shown by its headline with the
 * rules sentence it touches. Otherwise the row says that no news explains it, names the related contracts
 * that moved at the same time (often the whole story), and offers the nearest item only as "closest news".
 */
export function MoveStory({ move, onRule }: { move: Move; onRule?: () => void }) {
  if (move.explained && move.cause) {
    const cause = move.cause
    const { label, percent } = causeLabel(move)
    return (
      <div className="flex min-w-0 flex-col gap-0.5" title={move.summary}>
        <button
          onClick={(e) => {
            e.stopPropagation()
            focusTick(cause.id)
          }}
          title="Find it on the tape"
          className="flex min-w-0 items-baseline gap-1.5 text-left hover:underline"
        >
          <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wider text-muted">
            {label}
            {percent != null && <span className="num"> {percent}%</span>}
          </span>
          <span className="line-clamp-2 text-text">{cause.headline}</span>
        </button>
        <span className="flex items-center gap-1.5 text-[11px] text-faint">
          <SourceIcon source={cause.source} className="h-3 w-3" />
          <span className="truncate">{shortSource(cause.source)}</span>
        </span>
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
  const closest = move.closest
  return (
    <div className="flex min-w-0 flex-col gap-0.5" title={move.summary}>
      <p className="text-muted">
        No news explains it
        {move.related.length > 0 && <span className="text-faint">: the contracts beside it moved at the same time</span>}
      </p>
      {move.related.length > 0 && (
        <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-text">
          {move.related.map((r) => (
            <span key={r.id} className="flex min-w-0 items-baseline gap-1.5">
              <span className="truncate">{r.title}</span>
              <span className={`num shrink-0 ${r.to >= r.from ? 'text-up' : 'text-down'}`}>{pts(r.to - r.from)}</span>
            </span>
          ))}
        </p>
      )}
      {closest && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            focusTick(closest.id)
          }}
          title="Find it on the tape"
          className="flex min-w-0 items-center gap-1.5 text-left text-[11px] text-faint hover:text-text"
        >
          <span className="shrink-0 font-semibold uppercase tracking-wider">Closest news</span>
          <SourceIcon source={closest.source} className="h-3 w-3" />
          <span className="truncate">
            {shortSource(closest.source)}: {closest.headline}
          </span>
        </button>
      )}
    </div>
  )
}

/**
 * "Why did it move?": the market's price moves, newest first, each in one sentence. Most jumps are trades
 * on a thin market, not news, and the list says so. The button asks the same of the market's last day, at
 * any time: the backend answers in about a second from the day's strongest items.
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
          {state.busy ? 'Working out why it moved…' : 'Explain today’s move'}
        </button>
        <span className={`min-w-0 truncate text-[11px] ${state.note ? 'text-down' : 'text-faint'}`}>
          {state.note ?? 'Why did this market move over the last day? Asked now, answered in about a second.'}
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
                  {m.asked ? 'over the last day' : `in ${minutes(m.ts - m.since)}`} · {timeAgo(m.ts)}
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
