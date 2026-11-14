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
      <span className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-muted">
        Weekend record
        <kbd className="num rounded border border-line px-1 text-[10px] font-normal text-faint">R</kbd>
      </span>
      <span className="flex items-baseline justify-between gap-2">
        <span className="num text-3xl font-bold text-text">{f.hitRate == null ? '—' : `${Math.round(f.hitRate)}%`}</span>
        <span className="text-right text-[11px] leading-tight text-muted">
          price went our way
          <br />
          <span className="num">{f.sameWay}</span> of <span className="num">{f.moved}</span> moves
        </span>
      </span>
      <HitBar f={f} />
      <span className="text-[10px] text-faint">
        <span className="num">{f.called}</span> calls since {f.since}
      </span>
    </button>
  )
}
