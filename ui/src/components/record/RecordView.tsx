import { followThrough, methodology, recordFigures } from '../../lib/record'
import { useStore } from '../../state/store'
import { CountUp } from '../common/CountUp'
import { EmptyState } from '../common/EmptyState'
import { HitBar } from './HitBar'

function Figure({ value, label, note, tone = 'text-text' }: { value: number; label: string; note: string; tone?: string }) {
  return (
    <div className="flex flex-col items-center gap-1 text-center">
      <span className={`board text-6xl ${tone}`}>
        <CountUp value={value} />
      </span>
      <span className="text-sm font-semibold text-text">{label}</span>
      <span className="max-w-44 text-xs text-muted">{note}</span>
    </div>
  )
}

/**
 * Full screen: the live calls and what the price did after each, every count on the table and the method in
 * plain sight. The share is only ever given with what it is a share of. R or Esc closes.
 */
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
        className="press absolute right-3 top-3 flex h-9 w-9 items-center justify-center rounded-xs text-sm text-muted hover:bg-panel-2 hover:text-text"
      >
        ✕
      </button>
      {!f ? (
        <EmptyState title="Loading the record…" />
      ) : (
        <div className="m-auto flex w-full max-w-5xl flex-col items-center gap-8">
          <div className="flex flex-col items-center gap-2 text-center">
            <h1 className="text-3xl font-semibold tracking-[-0.015em] text-text">Directional follow-through</h1>
            <p className="max-w-2xl text-base text-muted">
              Live calls on real markets{f.since !== '—' && ` since ${f.since}`}
              {f.markets > 0 && `, across ${f.markets} ${f.markets === 1 ? 'market' : 'markets'}`}. Replays and made-up markets are not in
              these numbers.
            </p>
          </div>

          {f.calls === 0 ? (
            <p className="max-w-xl text-center text-base text-muted">
              No live call has completed its {f.windowMinutes}-minute window yet, so there is nothing to count. Nothing is shown in its place.
            </p>
          ) : (
            <>
              <div className="grid w-full grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-5">
                <Figure value={f.calls} label="Calls" note="items scored up or down, window over" />
                <Figure value={f.evaluable} label="Qualifying move" note={`price moved ${f.minMove} pt or more within ${f.windowMinutes} min`} />
                <Figure value={f.same} label="Same direction" note="price moved the way the call said" tone="text-up" />
                <Figure value={f.opposite} label="Opposite direction" note="price moved the other way" tone="text-down" />
                <Figure value={f.noMove} label="No qualifying move" note={`price moved less than ${f.minMove} pt`} tone="text-none" />
              </div>

              <div className="flex w-full max-w-3xl flex-col items-center gap-3">
                <p className="text-balance text-center text-2xl font-semibold leading-snug text-text">{followThrough(f)}</p>
                <p className="num text-center text-base text-muted">
                  {f.evaluable > 0 && (
                    <>
                      That is {f.same} of {f.evaluable} ({Math.round((f.same / f.evaluable) * 100)}%).{' '}
                    </>
                  )}
                  {f.opposite} moved the opposite way. {f.noMove} of the {f.calls} calls had no qualifying move.
                </p>
                <div className="w-full">
                  <HitBar f={f} tall />
                  <div className="mt-1.5 flex flex-wrap justify-between gap-x-4 text-xs text-muted">
                    <span>
                      <span className="mr-1 inline-block h-2 w-2 bg-up" />
                      same direction {f.same}
                    </span>
                    <span>
                      <span className="mr-1 inline-block h-2 w-2 bg-down" />
                      opposite {f.opposite}
                    </span>
                    <span>
                      <span className="mr-1 inline-block h-2 w-2 bg-none/60" />
                      no qualifying move {f.noMove}
                    </span>
                    <span>all {f.calls} calls</span>
                  </div>
                </div>
              </div>
            </>
          )}

          <p className="max-w-3xl border-t border-line pt-4 text-sm leading-relaxed text-muted">
            <span className="font-semibold text-text">Method. </span>
            {methodology(f)}
          </p>
        </div>
      )}
    </div>
  )
}
