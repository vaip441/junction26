import type { Tick } from '../../lib/types'
import { EmptyState } from '../common/EmptyState'
import { TickRow } from './TickRow'

export function Tape({ ticks }: { ticks: Tick[] | undefined }) {
  if (ticks === undefined) return <EmptyState title="Loading the tape…" />
  if (ticks.length === 0) {
    return <EmptyState title="Nothing on the tape yet">Scored news, posts and spoken lines appear here as they arrive.</EmptyState>
  }
  return (
    <ul className="divide-y divide-line">
      {ticks.map((t) => (
        <TickRow key={t.id} tick={t} />
      ))}
    </ul>
  )
}
