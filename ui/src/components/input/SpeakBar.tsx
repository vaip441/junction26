import { speechInputAvailable } from '../../hooks/useSpeechInput'
import { MicBar } from './MicBar'
import { TypeTickBox } from './TypeTickBox'

/** The made-up market's inputs: the mic, and typing next to it as the fallback for a loud hall. */
export function SpeakBar({ marketId }: { marketId: string }) {
  return (
    <div className="flex flex-col gap-2 border-t border-line p-3">
      {speechInputAvailable && <MicBar marketId={marketId} />}
      <TypeTickBox marketId={marketId} />
    </div>
  )
}
