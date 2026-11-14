import { absoluteTime, tickTime, timeAgo } from '../../lib/format'
import type { Tick, TickKind } from '../../lib/types'
import { Badge } from '../common/Badge'
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

export function TickRow({ tick }: { tick: Tick }) {
  const at = tickTime(tick)
  const quiet = tick.verdict === 'none'
  return (
    <li className={`flex flex-col gap-1 px-3 py-2.5 ${tick.backfill ? 'opacity-60' : ''}`}>
      <div className="flex items-center gap-2">
        <VerdictBadge verdict={tick.verdict} confidence={tick.confidence} strength={tick.strength} />
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
      <p className="flex gap-3 text-[11px] text-faint">
        <span className="truncate">{shortSource(tick.source)}</span>
        {tick.likes != null && <span className="num">♥ {tick.likes}</span>}
        {tick.replies != null && <span className="num">↩ {tick.replies}</span>}
      </p>
    </li>
  )
}
