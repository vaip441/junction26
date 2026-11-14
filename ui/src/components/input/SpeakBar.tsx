import { useState } from 'react'
import { speechInputAvailable } from '../../hooks/useSpeechInput'
import { resetDemo } from '../../lib/actions'
import { ConfirmButton } from '../common/ConfirmButton'
import { MicBar } from './MicBar'
import { TypeTickBox } from './TypeTickBox'

/** The demo market: the one the backend lets be put back to its starting price, after a rehearsal. */
const DEMO_ID = 'mu-demo'

function ResetDemo({ marketId }: { marketId: string }) {
  const [note, setNote] = useState<string | null>(null)
  return (
    <span className="ml-auto flex shrink-0 items-center gap-2">
      {note && <span className="text-xs text-down">{note}</span>}
      <ConfirmButton
        label="Reset"
        question="Empty the tape?"
        title="Put the demo market back to its starting price with an empty tape, after a rehearsal"
        onConfirm={async () => setNote(await resetDemo(marketId))}
      />
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
