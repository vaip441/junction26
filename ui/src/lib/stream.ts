import { API_URL } from './api'
import type { StreamEvent } from './types'

const EVENT_TYPES = ['tick', 'tick_update', 'price', 'move', 'market', 'page_check'] as const

export type StreamStatus = 'connecting' | 'live' | 'reconnecting'

/** Out of sight for this long, the connection is not trusted to have survived. */
const AWAY_MS = 30_000

/**
 * One EventSource on /stream for the whole app; it carries every market.
 * Reconnects with backoff. `onReconnect` fires after a dropped connection comes back, so the caller can
 * refetch whatever it may have missed. Returns a function that closes the stream.
 *
 * A phone that slept, or a tab left in the background, can come back to a connection that is dead without
 * ever having reported an error: the tape then stands still and nothing says so. A page shown again after
 * `AWAY_MS` out of sight connects afresh, which also refetches what was missed.
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
  let hiddenAt: number | null = document.hidden ? Date.now() : null

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

  const onVisibility = () => {
    if (document.hidden) {
      hiddenAt = Date.now()
      return
    }
    const away = hiddenAt == null ? 0 : Date.now() - hiddenAt
    hiddenAt = null
    if (closed || away < AWAY_MS) return
    clearTimeout(timer) // a retry that is already waiting: connect now instead
    source?.close()
    dropped = true
    retry = 1000
    connect()
  }
  document.addEventListener('visibilitychange', onVisibility)

  connect()
  return () => {
    closed = true
    clearTimeout(timer)
    document.removeEventListener('visibilitychange', onVisibility)
    source?.close()
  }
}
