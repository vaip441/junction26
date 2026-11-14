import { useNow } from '../../hooks/useNow'
import { absoluteTime, timeAgo } from '../../lib/format'
import { FOUND_BY, viaContextDev } from '../../lib/provenance'
import type { FoundBy, Source, WatchedPage } from '../../lib/types'
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
      <span className="shrink-0 text-xs font-semibold text-text">Watched page</span>
      <a href={page.url} target="_blank" rel="noreferrer" className="flex min-w-0 flex-1 items-center gap-1.5 text-text hover:underline" title={page.url}>
        <SourceIcon source={host} />
        <span className="truncate">{page.title || host}</span>
      </a>
      <span className="shrink-0 text-xs text-muted" title={page.checked_ts ? `Context.dev checked it ${absoluteTime(page.checked_ts)}` : undefined}>
        {page.checked_ts ? `checked ${timeAgo(page.checked_ts, now)}` : 'first check within ten minutes'}
        {page.changed_ts && <span className="text-text">, changed {timeAgo(page.changed_ts, now)}</span>}
      </span>
    </div>
  )
}

/**
 * How this market's items were found, counted by the backend as each was stored: every item, on the tape or
 * not. Context.dev's three ways are named as such and nothing else is; ticks from before this was recorded
 * are counted as "not recorded".
 */
function FoundByRow({ found }: { found: FoundBy[] }) {
  if (found.length === 0) return null
  const total = found.reduce((n, f) => n + f.items, 0)
  return (
    <p className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-line px-3 py-2 text-xs text-muted">
      <span className="font-semibold text-text">
        <span className="num">{total}</span> {total === 1 ? 'item' : 'items'} found by
      </span>
      {found.map((f) => (
        <span key={f.provenance} title={`${f.items} found, ${f.shown} of them shown on the tape`} className="whitespace-nowrap">
          <span className={viaContextDev(f.provenance) ? 'font-semibold text-text' : ''}>{FOUND_BY[f.provenance] ?? f.provenance}</span>{' '}
          <span className="num text-text">{f.items}</span>
        </span>
      ))}
    </p>
  )
}

/** Where this market's ticks came from, found by the terminal itself: items per source and how many were calls. */
export function SourcesPanel({ sources, pages = [], found = [] }: { sources: Source[]; pages?: WatchedPage[]; found?: FoundBy[] }) {
  const top = Math.max(1, ...sources.map((s) => s.ticks))
  return (
    <div className="flex flex-col">
      <FoundByRow found={found} />
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
              <span className="relative h-1.5 overflow-hidden bg-line" title={`${s.ticks} items, ${s.moved} called up or down`}>
                <span className="absolute inset-y-0 left-0 bg-none/60" style={{ width: `${(s.ticks / top) * 100}%` }} />
                <span className="absolute inset-y-0 left-0 bg-text" style={{ width: `${(s.moved / top) * 100}%` }} />
              </span>
              <span className="num whitespace-nowrap text-muted">
                {s.ticks} <span className="text-faint">items, {s.moved} calls</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
