import { ApiError, api } from './api'
import { announceTick } from './bus'
import { loadMarket } from '../hooks/useStream'
import { useStore } from '../state/store'

/**
 * Send a spoken or typed sentence to be scored. Shows a pending "scoring…" row at once, and returns the
 * error text to show if it failed (the backend's own words), or null when it was scored.
 */
export async function sendTick(marketId: string, text: string, kind: 'mic' | 'typed'): Promise<string | null> {
  const key = useStore.getState().addPending(marketId, text, kind)
  try {
    const tick = await api.addTick(marketId, text, kind)
    useStore.getState().apply({ type: 'tick', data: tick })
    announceTick(tick)
    return null
  } catch (e) {
    const err = e instanceof ApiError ? e : new ApiError(0, 'something went wrong, try again')
    if (err.status === 401) {
      useStore.getState().setNeedKey(true)
      return 'needs the terminal key: enter it, then send again'
    }
    return err.detail
  } finally {
    useStore.getState().removePending(marketId, key)
  }
}

/**
 * Track a market from a link or a question in plain words. Progress shows in the AskBar's checklist;
 * the new market opens as soon as the backend answers. Returns true when it is now tracked.
 */
export async function askFor(query: string): Promise<boolean> {
  const s = useStore.getState()
  if (s.ask && !s.ask.marketId && !s.ask.error) return false // one at a time
  s.startAsk(query)
  try {
    const market = await api.addMarket(query)
    useStore.getState().askDone(market)
    void loadMarket(market.id)
    return true
  } catch (e) {
    const err = e instanceof ApiError ? e : new ApiError(0, 'something went wrong, try again')
    if (err.status === 401) useStore.getState().setNeedKey(true)
    useStore.getState().askFailed(err.status === 401 ? 'needs the terminal key: enter it, then ask again' : err.detail)
    return false
  }
}

/**
 * Ask why a market moved over the last day. The answer arrives as a `move` event (and is stored here too,
 * in case the stream is slow). Returns the text to show if it could not be answered, or null.
 */
export async function askWhy(marketId: string): Promise<string | null> {
  try {
    useStore.getState().apply({ type: 'move', data: await api.why(marketId) })
    return null
  } catch (e) {
    const err = e instanceof ApiError ? e : new ApiError(0, 'something went wrong, try again')
    if (err.status === 401) {
      useStore.getState().setNeedKey(true)
      return 'needs the terminal key: enter it, then ask again'
    }
    return err.detail
  }
}

/** Put the demo market back to its starting price with an empty tape. Returns the error text, or null. */
export async function resetDemo(marketId: string): Promise<string | null> {
  try {
    await api.resetMarket(marketId)
    void loadMarket(marketId)
    return null
  } catch (e) {
    const err = e instanceof ApiError ? e : new ApiError(0, 'something went wrong, try again')
    if (err.status === 401) {
      useStore.getState().setNeedKey(true)
      return 'needs the terminal key: enter it, then reset again'
    }
    return err.detail
  }
}
