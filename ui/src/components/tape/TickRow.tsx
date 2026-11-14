import { absoluteTime, tickTime, timeAgo } from '../../lib/format'
import type { Lifecycle } from '../../lib/lifecycle'
import type { Move, Tick, TickKind } from '../../lib/types'
import { useStore } from '../../state/store'
import { shortSource } from '../../lib/sources'
import { Badge } from '../common/Badge'
import { SourceIcon } from '../common/SourceIcon'
import { MoveSpan } from '../market/MovesPanel'
import { DecisionBar } from './DecisionBar'
import { LifecycleBadge } from './LifecycleBadge'
import { VerdictBadge } from './VerdictBadge'

const KIND_LABEL: Record<TickKind, string> = {
  article: 'Article',
  post: 'Post',
  filing: 'Filing',
  page: 'Page',
  mic: 'Spoken',
  typed: 'Typed',
}


export function TickRow({
  tick,
  life,
  move,
  now,
}: {
  tick: Tick
  life: Lifecycle | null
  move?: Move
  now: number
}) {
  const showRule = useStore((s) => s.showRule)
  const setTab = useStore((s) => s.setTab)
  const at = tickTime(tick)
  const quiet = tick.verdict === 'none'
  // arrived in the last few seconds: animate the decision (first paint of history stays still)
  const fresh = !tick.backfill && now - tick.ts < 15
  // found in the last few seconds, live news or earlier coverage alike: the row opens up in place, so the
  // rows under it glide down (history already here on first paint stays still)
  const arrived = now - tick.ts < 12
  return (
    <li id={`tick-${tick.id}`} className={`grid ${arrived ? 'row-in' : ''}`}>
      <div
        className={`flex min-h-0 flex-col gap-1 overflow-hidden border-l-2 px-3 py-2.5 ${fresh ? 'tick-flash' : ''} ${tick.backfill ? 'opacity-60' : ''} ${
          life?.state === 'edge' ? (tick.verdict === 'up' ? 'border-l-up' : 'border-l-down') : 'border-l-transparent'
        }`}
      >
      <div className="flex items-center gap-2">
        <span className={fresh ? 'verdict-late' : ''}>
          <VerdictBadge verdict={tick.verdict} confidence={tick.confidence} strength={tick.strength} />
        </span>
        <Badge tone={tick.test ? 'madeup' : 'neutral'}>{KIND_LABEL[tick.kind]}</Badge>
        {tick.backfill && <Badge>Earlier</Badge>}
        <span className="ml-auto shrink-0 text-[11px] text-faint" title={absoluteTime(at)}>
          {timeAgo(at)}
        </span>
      </div>
      <p className={`text-sm leading-snug ${quiet ? 'line-clamp-1 text-muted' : 'line-clamp-3 text-text'}`}>
        {tick.url ? (
          <a href={tick.url} target="_blank" rel="noreferrer" className="hover:underline">
            {tick.headline}
          </a>
        ) : (
          tick.headline
        )}
      </p>
      <DecisionBar up={tick.up} none={tick.none} down={tick.down} fresh={fresh} />
      {tick.rule && (
        <button
          onClick={() => showRule(tick.rule!)}
          title={`The sentence of the rules that makes this matter: ${tick.rule.text}`}
          className="line-clamp-1 text-left text-[11px] italic text-muted hover:text-text"
        >
          § “{tick.rule.text}”
        </button>
      )}
      {(life || move) && (
        <div className="flex flex-wrap items-center gap-1.5">
          {move && (
            <button
              onClick={() => setTab('moves')}
              title="The terminal names this as the likely cause of a price jump"
              className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-text hover:border-accent"
            >
              Moved the price <MoveSpan move={move} />
            </button>
          )}
          {life && <LifecycleBadge life={life} verdict={tick.verdict} />}
        </div>
      )}
      <p className="flex items-center gap-3 text-[11px] text-faint">
        <span className="flex min-w-0 items-center gap-1.5">
          <SourceIcon source={tick.source} className="h-3 w-3" />
          <span className="truncate">{shortSource(tick.source)}</span>
        </span>
        {tick.likes != null && <span className="num">♥ {tick.likes}</span>}
        {tick.replies != null && <span className="num">↩ {tick.replies}</span>}
      </p>
      </div>
    </li>
  )
}
