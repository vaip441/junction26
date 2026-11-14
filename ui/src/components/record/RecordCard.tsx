import { recordFigures } from '../../lib/record'
import { useStore } from '../../state/store'
import { HitBar } from './HitBar'

/** The weekend record in the market column: how often the price followed our calls. R opens it full screen. */
export function RecordCard() {
  const record = useStore((s) => s.record)
  const open = useStore((s) => s.toggleRecord)
  if (!record) return null
  const f = recordFigures(record)
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
