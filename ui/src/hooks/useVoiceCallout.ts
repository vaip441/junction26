import { useEffect } from 'react'
import { onNewTick } from '../lib/bus'
import { say, silence } from '../lib/voice'
import { useStore } from '../state/store'

const WORD = { up: 'Up', down: 'Down', none: 'No effect' } as const

/**
 * Reads each new tick on the market on screen out loud: "Up, 82 percent. Price 26 percent."
 * News that changes nothing is not read (it would drown the rest); a spoken or typed sentence always is.
 */
export function useVoiceCallout(): void {
  const muted = useStore((s) => s.muted)

  useEffect(() => {
    if (muted) silence()
  }, [muted])

  useEffect(
    () =>
      onNewTick((t) => {
        const s = useStore.getState()
        if (s.muted || t.market_id !== s.selectedId || t.backfill || document.hidden) return
        if (t.verdict === 'none' && !t.test) return
        const price = s.markets[t.market_id]?.price
        const call = t.verdict === 'none' ? 'No effect.' : `${WORD[t.verdict]}, ${Math.round(t.confidence * 100)} percent.`
        say(price == null ? call : `${call} Price ${Math.round(price)} percent.`)
      }),
    [],
  )
}
