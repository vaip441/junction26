import { API_URL } from './api'
import type { StreamEvent } from './types'

const EVENT_TYPES = ['tick', 'tick_update', 'price', 'move', 'market', 'page_check'] as const

export type StreamStatus = 'connecting' | 'live' | 'reconnecting'

/**
 * One EventSource on /stream for the whole app; it carries every market.
 * Reconnects with backoff. `onReconnect` fires after a dropped connection comes back, so the caller can
 * refetch whatever it may have missed. Returns a function that closes the stream.
 */
export function openStream(handlers: {
  onEvent: (e: StreamEvent) => void
  onStatus: (s: StreamStatus) => void
  onReconnect: () => void
}): () => void {
  let source: EventSource | null = null
  let closed = false
  let retry = 1000
  let dropped = false
  let timer: ReturnType<typeof setTimeout> | undefined

  const connect = () => {
    if (closed) return
    handlers.onStatus(dropped ? 'reconnecting' : 'connecting')
    source = new EventSource(`${API_URL}/stream`)
    source.onopen = () => {
      handlers.onStatus('live')
      retry = 1000
      if (dropped) handlers.onReconnect()
      dropped = false
    }
    source.onerror = () => {
      source?.close()
      dropped = true
      handlers.onStatus('reconnecting')
      timer = setTimeout(connect, retry)
      retry = Math.min(retry * 2, 15000)
    }
    for (const type of EVENT_TYPES) {
      source.addEventListener(type, (msg) => {
        try {
          handlers.onEvent({ type, data: JSON.parse((msg as MessageEvent<string>).data) } as StreamEvent)
        } catch {
          // a malformed event is dropped, never fatal
        }
      })
    }
  }

  connect()
  return () => {
    closed = true
    clearTimeout(timer)
    source?.close()
  }
}
