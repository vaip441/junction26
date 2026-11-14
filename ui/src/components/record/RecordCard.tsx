import { recordFigures } from '../../lib/record'
import { useStore } from '../../state/store'
import { HitBar } from './HitBar'

/**
 * The weekend record in the market column: how often the price followed our calls. R opens it full screen.
 * `compact`: one row that stays at the foot of the list of markets on a narrow screen; a tap opens it.
 */
export function RecordCard({ compact = false }: { compact?: boolean }) {
  const record = useStore((s) => s.record)
  const open = useStore((s) => s.toggleRecord)
  if (!record) return null
  const f = recordFigures(record)
  if (compact) {
    return (
      <button
        onClick={() => open(true)}
        aria-label="Open the weekend record"
        className="sticky bottom-0 z-10 flex w-full shrink-0 items-center gap-3 border-t border-line bg-panel px-3 py-2.5 text-left active:bg-panel-2"
      >
        <span className="board text-4xl text-text">{f.hitRate == null ? '—' : `${Math.round(f.hitRate)}%`}</span>
        <span className="flex min-w-0 flex-1 flex-col gap-1.5">
          <span className="flex items-baseline justify-between gap-2">
            <span className="label">Weekend record</span>
            <span className="truncate text-xs text-muted">
              price went our way in <span className="num">{f.sameWay}</span> of <span className="num">{f.moved}</span> moves
            </span>
          </span>
          <HitBar f={f} />
        </span>
      </button>
    )
  }
  return (
    <button
      onClick={() => open(true)}
      className="flex w-full shrink-0 flex-col gap-2 border-t border-line bg-panel p-3 text-left hover:bg-panel-2"
      title="Open the weekend record (R)"
    >
      <span className="label flex items-center justify-between">
        Weekend record
        <span className="font-normal text-faint">press R</span>
      </span>
      <span className="flex items-baseline justify-between gap-2">
        <span className="board text-5xl text-text">{f.hitRate == null ? '—' : `${Math.round(f.hitRate)}%`}</span>
        <span className="text-right text-xs leading-tight text-muted">
          price went our way
          <br />
          <span className="num">{f.sameWay}</span> of <span className="num">{f.moved}</span> moves
        </span>
      </span>
      <HitBar f={f} />
      <span className="text-[11px] text-faint">
        <span className="num">{f.called}</span> calls since {f.since}
      </span>
    </button>
  )
}
