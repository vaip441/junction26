import { useNow } from '../../hooks/useNow'
import { absoluteTime, timeAgo } from '../../lib/format'
import type { Source, WatchedPage } from '../../lib/types'
import { shortSource } from '../../lib/sources'
import { EmptyState } from '../common/EmptyState'
import { SourceIcon } from '../common/SourceIcon'

/**
 * The page a Context.dev monitor watches for this market: the one most likely to change when the outcome
 * is decided. Checked every ten minutes; a change that bears on the market lands on the tape as a PAGE tick.
 */
function Watched({ page }: { page: WatchedPage }) {
  const now = useNow(10_000)
  const host = page.url.replace(/^https?:\/\//, '').split('/')[0].replace(/^www\./, '')
  return (
    <div className="flex items-center gap-3 border-b border-line px-3 py-2 text-xs">
      <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wider text-accent">Watched page</span>
      <a href={page.url} target="_blank" rel="noreferrer" className="flex min-w-0 flex-1 items-center gap-1.5 text-text hover:underline" title={page.url}>
        <SourceIcon source={host} />
        <span className="truncate">{page.title || host}</span>
      </a>
      <span className="shrink-0 text-[11px] text-muted" title={page.checked_ts ? `Context.dev checked it ${absoluteTime(page.checked_ts)}` : undefined}>
        {page.checked_ts ? `checked ${timeAgo(page.checked_ts, now)}` : 'first check within ten minutes'}
        {page.changed_ts && <span className="text-text"> · changed {timeAgo(page.changed_ts, now)}</span>}
      </span>
    </div>
  )
}

/** Where this market's ticks came from, found by the terminal itself: items per source and how many were calls. */
export function SourcesPanel({ sources, pages = [] }: { sources: Source[]; pages?: WatchedPage[] }) {
  const top = Math.max(1, ...sources.map((s) => s.ticks))
  return (
    <div className="flex flex-col">
      {pages.map((p) => (
        <Watched key={p.url} page={p} />
      ))}
      {sources.length === 0 ? (
        <EmptyState title="No sources yet">The terminal is still searching the web for this market.</EmptyState>
      ) : (
        <ul className="flex flex-col gap-1.5 p-3">
          {sources.map((s) => (
            <li key={s.source} className="grid grid-cols-[minmax(0,10rem)_1fr_auto] items-center gap-3 text-xs">
              <span className="flex min-w-0 items-center gap-1.5 text-text">
                <SourceIcon source={s.source} />
                <span className="truncate">{shortSource(s.source)}</span>
              </span>
              <span className="relative h-1.5 overflow-hidden rounded-full bg-line" title={`${s.ticks} items, ${s.moved} called up or down`}>
                <span className="absolute inset-y-0 left-0 bg-none/60" style={{ width: `${(s.ticks / top) * 100}%` }} />
                <span className="absolute inset-y-0 left-0 bg-accent/80" style={{ width: `${(s.moved / top) * 100}%` }} />
              </span>
              <span className="num whitespace-nowrap text-muted">
                {s.ticks} <span className="text-faint">· {s.moved} calls</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
