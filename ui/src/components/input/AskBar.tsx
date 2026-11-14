import { useState, type FormEvent } from 'react'
import { ApiError, api } from '../../lib/api'
import { loadMarket } from '../../hooks/useStream'
import { useStore } from '../../state/store'
import { AskProgress } from './AskProgress'

export const ASK_INPUT_ID = 'ask-input'

/** One box for a Kalshi/Polymarket link or a question in plain words. `/` focuses it. */
export function AskBar() {
  const [text, setText] = useState('')
  const ask = useStore((s) => s.ask)
  const working = Boolean(ask && !ask.marketId && !ask.error)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const query = text.trim()
    if (!query || working) return
    const s = useStore.getState()
    s.startAsk(query)
    try {
      const market = await api.addMarket(query)
      useStore.getState().askDone(market)
      setText('')
      void loadMarket(market.id)
    } catch (err) {
      const e2 = err instanceof ApiError ? err : new ApiError(0, 'something went wrong, try again')
      if (e2.status === 401) useStore.getState().setNeedKey(true)
      useStore.getState().askFailed(e2.status === 401 ? 'needs the terminal key: enter it, then ask again' : e2.detail)
    }
  }

  return (
    <form onSubmit={submit} className="relative min-w-0 flex-1">
      <input
        id={ASK_INPUT_ID}
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={working}
        placeholder="Paste a Kalshi or Polymarket link, or ask anything: “will Jensen step down this year?”   ( / )"
        className="h-8 w-full rounded border border-line bg-bg px-3 text-sm text-text placeholder:text-faint focus:border-accent focus:outline-none disabled:opacity-60"
      />
      {ask && <AskProgress />}
    </form>
  )
}
