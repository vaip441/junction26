import type { RecordFigures } from '../../lib/record'

/**
 * Every call, in three parts: followed by a move the predicted way (green), the opposite way (red), and no
 * qualifying move (grey). The whole denominator is on the bar, so the green is never read as a share of less.
 */
export function HitBar({ f, tall = false }: { f: Pick<RecordFigures, 'calls' | 'same' | 'opposite' | 'noMove'>; tall?: boolean }) {
  const share = (n: number) => (f.calls > 0 ? `${(n / f.calls) * 100}%` : '0%')
  return (
    <div
      className={`flex w-full overflow-hidden bg-line ${tall ? 'h-5' : 'h-2'}`}
      role="img"
      aria-label={`${f.same} same direction, ${f.opposite} opposite direction, ${f.noMove} no qualifying move, of ${f.calls} calls`}
    >
      <span className="bar-grow bg-up" style={{ width: share(f.same) }} title={`${f.same} moved in the predicted direction`} />
      <span className="bg-down" style={{ width: share(f.opposite) }} title={`${f.opposite} moved the opposite way`} />
      <span className="bg-none/60" style={{ width: share(f.noMove) }} title={`${f.noMove} had no qualifying move`} />
    </div>
  )
}
