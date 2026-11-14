import { absoluteTime, pct, timeAgo } from '../../lib/format'
import { focusTick } from '../../lib/focus'
import { shortSource } from '../../lib/sources'
import type { Move } from '../../lib/types'
import { useStore } from '../../state/store'
import { EmptyState } from '../common/EmptyState'
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
  return `${Math.max(1, Math.round(seconds / 60))} min`
}

/**
 * "Why did it move?": the market's price jumps, newest first, each with the item the terminal names as its
 * likely cause and the sentence of the rules that item touches. A jump nothing explains is listed too.
 */
export function MovesPanel({ moves }: { moves: Move[] | undefined }) {
  const showRule = useStore((s) => s.showRule)
  if (moves === undefined) return <p className="p-3 text-xs text-faint">Loading…</p>
  if (moves.length === 0) {
    return (
      <EmptyState title="No price jumps yet">
        When the price moves 3 points within 10 minutes, the terminal searches the web at once and names the likely cause here.
      </EmptyState>
    )
  }
  return (
    <ul className="divide-y divide-line">
      {moves.map((m) => (
        <li key={m.id} id={`move-${m.id}`} className="grid grid-cols-[7.5rem_1fr] gap-x-3 px-3 py-2 text-xs">
          <div className="flex flex-col gap-0.5">
            <MoveSpan move={m} className="text-sm" />
            <span className="text-[10px] text-faint" title={`${absoluteTime(m.since)} to ${absoluteTime(m.ts)}`}>
              in {minutes(m.ts - m.since)} · {timeAgo(m.ts)}
            </span>
          </div>
          {m.cause ? (
            <div className="flex min-w-0 flex-col gap-0.5">
              <button
                onClick={() => focusTick(m.cause!.id)}
                title="Find it on the tape"
                className="flex min-w-0 items-baseline gap-1.5 text-left hover:underline"
              >
                <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wider text-muted">
                  Likely cause{m.confidence != null && <span className="num"> {Math.round(m.confidence * 100)}%</span>}
                </span>
                <span className="line-clamp-2 text-text">{m.cause.headline}</span>
              </button>
              <span className="flex items-center gap-1.5 text-[11px] text-faint">
                <SourceIcon source={m.cause.source} className="h-3 w-3" />
                <span className="truncate">{shortSource(m.cause.source)}</span>
              </span>
              {m.rule && (
                <button
                  onClick={() => showRule(m.rule!)}
                  title="Show it in the rules"
                  className="line-clamp-1 text-left text-[11px] italic text-muted hover:text-text"
                >
                  § “{m.rule.text}”
                </button>
              )}
            </div>
          ) : (
            <span className="self-center text-muted">No cause found on the web</span>
          )}
        </li>
      ))}
    </ul>
  )
}
