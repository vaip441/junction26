import { useEffect, useState } from 'react'
import { speechInputAvailable } from '../../hooks/useSpeechInput'
import { resetDemo } from '../../lib/actions'
import { MicBar } from './MicBar'
import { TypeTickBox } from './TypeTickBox'

/** The demo market: the one the backend lets be put back to its starting price, after a rehearsal. */
const DEMO_ID = 'mu-demo'

/** Two clicks, so a stray one on stage does not wipe the tape: "Reset", then "Empty the tape?" within a few seconds. */
function ResetDemo({ marketId }: { marketId: string }) {
  const [armed, setArmed] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  useEffect(() => {
    if (!armed) return
    const timer = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(timer)
  }, [armed])
  return (
    <span className="ml-auto flex shrink-0 items-center gap-2">
      {note && <span className="text-xs text-down">{note}</span>}
      <button
        onClick={async () => {
          if (!armed) return setArmed(true)
          setArmed(false)
          setNote(await resetDemo(marketId))
        }}
        title="Put the demo market back to its starting price with an empty tape, after a rehearsal"
        className={`rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wider ${
          armed ? 'border-down/60 text-down' : 'border-line text-faint hover:text-text'
        }`}
      >
        {armed ? 'Empty the tape?' : 'Reset'}
      </button>
    </span>
  )
}

/** The made-up market's inputs: the mic, and typing next to it as the fallback for a loud hall. */
export function SpeakBar({ marketId }: { marketId: string }) {
  return (
    <div className="flex flex-col gap-2 border-t border-line p-3">
      <div className="flex items-center gap-3">
        {speechInputAvailable && <MicBar marketId={marketId} />}
        {marketId === DEMO_ID && <ResetDemo marketId={marketId} />}
      </div>
      <TypeTickBox marketId={marketId} />
    </div>
  )
}
