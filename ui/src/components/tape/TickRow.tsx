import { absoluteTime, tickTime, timeAgo } from '../../lib/format'
import type { Lifecycle } from '../../lib/lifecycle'
import type { Tick, TickKind } from '../../lib/types'
import { Badge } from '../common/Badge'
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

function shortSource(source: string): string {
  return source.replace(/^reddit\.com\/r\//, 'r/').replace(/^www\./, '')
}

export function TickRow({ tick, life, now }: { tick: Tick; life: Lifecycle | null; now: number }) {
  const at = tickTime(tick)
  const quiet = tick.verdict === 'none'
  // arrived in the last few seconds: animate the decision (first paint of history stays still)
  const fresh = !tick.backfill && now - tick.ts < 15
  return (
    <li
      id={`tick-${tick.id}`}
      className={`flex flex-col gap-1 border-l-2 ${fresh ? 'slide-in' : ''} px-3 py-2.5 ${tick.backfill ? 'opacity-60' : ''} ${
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
      {life && (
        <div>
          <LifecycleBadge life={life} verdict={tick.verdict} />
        </div>
      )}
      <p className="flex gap-3 text-[11px] text-faint">
        <span className="truncate">{shortSource(tick.source)}</span>
        {tick.likes != null && <span className="num">♥ {tick.likes}</span>}
        {tick.replies != null && <span className="num">↩ {tick.replies}</span>}
      </p>
    </li>
  )
}
