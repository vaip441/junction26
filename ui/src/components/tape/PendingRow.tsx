import type { PendingTick } from '../../state/store'
import { Badge } from '../common/Badge'

/** A sentence sent for scoring, on the tape at once so the wait reads as work. */
export function PendingRow({ p }: { p: PendingTick }) {
  return (
    <li className="slide-in flex flex-col gap-1 bg-panel-2 px-3 py-2.5">
      <div className="flex items-baseline gap-3">
        <span className="animate-pulse text-[0.8125rem] font-bold text-text">Scoring…</span>
        <Badge tone="madeup">{p.kind === 'mic' ? 'Spoken' : 'Typed'}</Badge>
        <span className="ml-auto text-xs text-faint">just now</span>
      </div>
      <p className="text-[0.9375rem] font-medium leading-snug text-text">{p.text}</p>
      <div className="h-[3px] w-full overflow-hidden bg-line">
        <span className="scan block h-full w-1/3 bg-text/70" />
      </div>
    </li>
  )
}
