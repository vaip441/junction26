import { useNow } from '../../hooks/useNow'
import { tickLifecycle } from '../../lib/lifecycle'
import type { PricePoint, Tick } from '../../lib/types'
import type { PendingTick } from '../../state/store'
import { EmptyState } from '../common/EmptyState'
import { PendingRow } from './PendingRow'
import { TickRow } from './TickRow'

export function Tape({
  ticks,
  prices,
  madeUp,
  pending = [],
}: {
  ticks: Tick[] | undefined
  prices: PricePoint[] | undefined
  madeUp: boolean
  pending?: PendingTick[]
}) {
  const now = useNow()
  if (ticks === undefined) return <EmptyState title="Loading the tape…" />
  if (ticks.length === 0 && pending.length === 0) {
    return <EmptyState title="Nothing on the tape yet">Scored news, posts and spoken lines appear here as they arrive.</EmptyState>
  }
  return (
    <ul className="divide-y divide-line">
      {pending.map((p) => (
        <PendingRow key={`p${p.key}`} p={p} />
      ))}
      {ticks.map((t) => (
        <TickRow key={t.id} tick={t} life={tickLifecycle(t, prices, madeUp, now)} now={now} />
      ))}
    </ul>
  )
}
