import type { RecordFigures } from '../../lib/record'

/**
 * Of the calls the price then moved on: same way (green) against wrong way (red), with a mark at 50% so
 * the gap to a coin flip is visible at a glance.
 */
export function HitBar({ f, tall = false }: { f: RecordFigures; tall?: boolean }) {
  const same = f.moved > 0 ? (f.sameWay / f.moved) * 100 : 0
  return (
    <div className={`relative w-full overflow-hidden rounded-full bg-line ${tall ? 'h-5' : 'h-2'}`}>
      {f.moved > 0 && (
        <>
          <span className="bar-grow absolute inset-y-0 left-0 bg-up" style={{ width: `${same}%` }} />
          <span className="absolute inset-y-0 right-0 bg-down/70" style={{ width: `${100 - same}%` }} />
        </>
      )}
      <span className="absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 bg-bg" title="a coin flip: 50%" />
    </div>
  )
}
