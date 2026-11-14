import { followThrough, recordFigures } from '../../lib/record'
import { useStore } from '../../state/store'
import { HitBar } from './HitBar'

/**
 * The live record in the market column: directional follow-through, as counts with their denominator. No
 * percentage stands alone here. R opens it full screen, with the method spelled out.
 */
export function RecordCard() {
  const record = useStore((s) => s.record)
  const open = useStore((s) => s.toggleRecord)
  if (!record) return null
  const f = recordFigures(record)
  return (
    <button
      onClick={() => open(true)}
      className="flex w-full shrink-0 flex-col gap-2 border-t border-line bg-panel p-3 text-left hover:bg-panel-2"
      title="Open the record and its method (R)"
    >
      <span className="label flex items-baseline justify-between gap-2">
        Directional follow-through
        <span className="shrink-0 font-normal text-faint">R</span>
      </span>
      {f.calls === 0 ? (
        <span className="text-xs leading-snug text-muted">No live call has completed its {f.windowMinutes}-minute window yet.</span>
      ) : (
        <>
          <span className="board whitespace-nowrap text-4xl text-text">
            {f.same}
            <span className="text-muted"> / {f.evaluable}</span>
          </span>
          <HitBar f={f} />
          <span className="text-xs leading-snug text-text">{followThrough(f)}</span>
          <span className="num text-xs leading-snug text-muted">
            {f.opposite} opposite · {f.noMove} no qualifying move · {f.calls} calls
            {f.markets > 0 && ` on ${f.markets} ${f.markets === 1 ? 'market' : 'markets'}`}
          </span>
        </>
      )}
      <span className="text-xs leading-snug text-faint">
        Price {f.windowMinutes} min after each call, moves of {f.minMove} pt or more. Not accuracy, not proof of cause.
      </span>
    </button>
  )
}
