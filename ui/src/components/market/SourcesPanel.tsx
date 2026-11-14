import type { Source } from '../../lib/types'
import { shortSource } from '../../lib/sources'
import { EmptyState } from '../common/EmptyState'
import { SourceIcon } from '../common/SourceIcon'

/** Where this market's ticks came from, found by the terminal itself: items per source and how many were calls. */
export function SourcesPanel({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return <EmptyState title="No sources yet">The terminal is still searching the web for this market.</EmptyState>
  const top = Math.max(...sources.map((s) => s.ticks))
  return (
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
  )
}
