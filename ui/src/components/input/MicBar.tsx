import { useEffect, useState } from 'react'
import { useSpeechInput, type MicState } from '../../hooks/useSpeechInput'
import { sendTick } from '../../lib/actions'
import { touchOnly } from '../../lib/device'
import { useStore } from '../../state/store'

const LABEL: Record<MicState, string> = {
  off: 'Press Space, then talk: each sentence is scored',
  starting: 'Starting the mic…',
  listening: 'Listening: each sentence is scored',
  unsupported: 'No microphone to use here: type below',
  denied: 'Mic blocked: allow it in the address bar, or type below',
}

/** Every sentence said near the laptop becomes a SPOKEN tick. Space toggles it. */
export function MicBar({ marketId }: { marketId: string }) {
  const micOn = useStore((s) => s.micOn)
  const setMic = useStore((s) => s.setMic)
  const [error, setError] = useState<string | null>(null)
  const show = (err: string | null) => {
    setError(err)
    if (err) setTimeout(() => setError(null), 6000)
  }
  const { state, hearing, writing, interim, start, stop } = useSpeechInput(
    (text) => void sendTick(marketId, text, 'mic').then(show),
    show,
  )

  useEffect(() => {
    if (micOn) start()
    else stop()
  }, [micOn, start, stop])

  // a blocked or missing mic turns the switch back off, so Space doesn't look like it does something
  useEffect(() => {
    if (state === 'denied' || state === 'unsupported') setMic(false)
  }, [state, setMic])

  const live = state === 'listening'
  const usable = state !== 'unsupported' && state !== 'denied'
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex items-center gap-3">
        <button
          onClick={() => setMic(!micOn)}
          disabled={!usable}
          title="Space"
          aria-pressed={micOn}
          className={`press btn flex h-9 shrink-0 items-center gap-2 px-3! max-lg:h-11 max-lg:px-4! ${micOn ? 'border-text! text-text!' : ''}`}
        >
          <span className={`h-2 w-2 ${live ? 'animate-pulse bg-down' : micOn ? 'bg-madeup' : 'bg-faint'}`} />
          {micOn ? 'Mic on' : 'Mic off'}
        </button>
        <span className="truncate text-xs text-muted">
          {interim ? (
            <span className="italic text-text">“{interim}”</span>
          ) : live && hearing ? (
            <span className="italic text-text">Hearing you…</span>
          ) : writing ? (
            <span className="italic text-text">Writing down what was said…</span>
          ) : state === 'off' && touchOnly() ? (
            'Tap, then talk: each sentence is scored' // no Space key under a finger
          ) : (
            LABEL[state]
          )}
        </span>
      </div>
      {error && <p className="text-xs text-down">{error}</p>}
    </div>
  )
}
