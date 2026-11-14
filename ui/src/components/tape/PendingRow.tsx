import type { PendingTick } from '../../state/store'
import { Badge } from '../common/Badge'

/** A sentence sent for scoring, on the tape at once so the wait reads as work. */
export function PendingRow({ p }: { p: PendingTick }) {
  return (
    <li className="slide-in flex flex-col gap-1 bg-panel-2 px-3 py-2.5">
      <div className="flex items-center gap-2">
        <span className="num animate-pulse text-xs font-bold text-accent">⋯ SCORING</span>
        <Badge tone="madeup">{p.kind === 'mic' ? 'Spoken' : 'Typed'}</Badge>
        <span className="ml-auto text-[11px] text-faint">just now</span>
      </div>
      <p className="text-sm leading-snug text-text">{p.text}</p>
      <div className="h-1 w-full overflow-hidden rounded-full bg-line">
        <span className="scan block h-full w-1/3 rounded-full bg-accent/60" />
      </div>
    </li>
  )
}
