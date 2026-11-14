import { useMemo } from 'react'
import { useNow } from '../../hooks/useNow'
import { tickLifecycle } from '../../lib/lifecycle'
import type { Move, PricePoint, Tick } from '../../lib/types'
import { useStore, type PendingTick } from '../../state/store'
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
  const moves = useStore((s) => (s.selectedId ? s.moves[s.selectedId] : undefined))
  // the tick each move names as its cause carries a badge; the newest move wins when a tick caused two
  const caused = useMemo(() => {
    const by = new Map<number, Move>()
    for (const m of moves ?? []) if (m.cause && !by.has(m.cause.id)) by.set(m.cause.id, m)
    return by
  }, [moves])
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
        <TickRow key={t.id} tick={t} life={tickLifecycle(t, prices, madeUp, now)} move={caused.get(t.id)} now={now} />
      ))}
    </ul>
  )
}
