import { recordFigures } from '../../lib/record'
import { useStore } from '../../state/store'
import { CountUp } from '../common/CountUp'
import { EmptyState } from '../common/EmptyState'
import { HitBar } from './HitBar'

function Figure({ value, label, note }: { value: number; label: string; note: string }) {
  return (
    <div className="flex flex-col items-center gap-1 text-center">
      <span className="num text-6xl font-bold text-text">
        <CountUp value={value} />
      </span>
      <span className="text-xs font-semibold uppercase tracking-wider text-muted">{label}</span>
      <span className="max-w-48 text-xs text-faint">{note}</span>
    </div>
  )
}

/** Beat 4, full screen: the calls we made all weekend and how often the price then followed. R or Esc closes. */
export function RecordView() {
  const open = useStore((s) => s.recordOpen)
  const record = useStore((s) => s.record)
  const close = useStore((s) => s.toggleRecord)
  if (!open) return null
  const f = record ? recordFigures(record) : null

  return (
    <div className="fade-in fixed inset-0 z-40 flex flex-col overflow-y-auto bg-bg px-4 py-8">
      <button
        onClick={() => close(false)}
        aria-label="Close"
        title="Close (Esc)"
        className="press absolute right-3 top-3 flex h-9 w-9 items-center justify-center rounded text-sm text-muted hover:bg-panel-2 hover:text-text"
      >
        ✕
      </button>
      {!f ? (
        <EmptyState title="Loading the weekend record…" />
      ) : (
        <div className="m-auto flex w-full max-w-3xl flex-col items-center gap-10">
          <div className="flex flex-col items-center gap-2 text-center">
            <h1 className="text-sm font-semibold uppercase tracking-[0.3em] text-muted">The weekend record</h1>
            <p className="max-w-xl text-sm text-faint">
              Every up or down call on a real market since {f.since}, judged by the price {f.windowMinutes} minutes
              later. Moves under 1 pt count as no move.
            </p>
          </div>

          <div className="grid w-full grid-cols-1 gap-8 sm:grid-cols-3">
            <Figure value={f.called} label="Calls made" note="news, posts and filings we scored up or down" />
            <Figure value={f.moved} label="Price moved" note={`${f.noMove} calls the price ignored are left out`} />
            <Figure value={f.sameWay} label="Went our way" note={`${f.wrongWay} went the other way`} />
          </div>

          <div className="flex w-full flex-col items-center gap-3">
            <span className={`num text-8xl font-bold ${f.hitRate != null && f.hitRate >= 50 ? 'text-up' : 'text-text'}`}>
              {f.hitRate == null ? '—' : <CountUp value={f.hitRate} ms={1600} format={(n) => `${Math.round(n)}%`} />}
            </span>
            <span className="text-sm text-muted">of the time the price moved, it moved the way we called it</span>
            <div className="w-full max-w-xl">
              <HitBar f={f} tall />
              <div className="mt-1 flex justify-between text-[11px] text-faint">
                <span>0%</span>
                <span>coin flip</span>
                <span>100%</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
