import { useEffect, useState } from 'react'
import { onNewTick } from '../../lib/bus'
import { useStore } from '../../state/store'

const BIG = 0.6

/**
 * A strong call on the market on screen: the screen's edges glow its colour. Small calls stay still so
 * the big ones land.
 */
export function EdgeFlash() {
  const [flash, setFlash] = useState<{ verdict: 'up' | 'down'; n: number } | null>(null)

  useEffect(() => {
    let n = 0
    let timer: ReturnType<typeof setTimeout> | undefined
    const off = onNewTick((t) => {
      const { selectedId } = useStore.getState()
      if (t.market_id !== selectedId || t.backfill || t.verdict === 'none' || Math.abs(t.strength) < BIG) return
      if (document.hidden) return // a backlog after a reconnect must not fire a burst
      setFlash({ verdict: t.verdict, n: ++n })
      clearTimeout(timer)
      timer = setTimeout(() => setFlash(null), 1400)
    })
    return () => {
      off()
      clearTimeout(timer)
    }
  }, [])

  if (!flash) return null
  return (
    <div
      key={flash.n}
      aria-hidden
      className={`edge-flash pointer-events-none fixed inset-0 z-30 ${flash.verdict === 'up' ? 'text-up' : 'text-down'}`}
    />
  )
}
