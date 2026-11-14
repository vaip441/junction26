import { ApiError, api } from './api'
import { announceTick } from './bus'
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
