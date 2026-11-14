import { useEffect } from 'react'
import { api } from '../lib/api'
import { useStore } from '../state/store'

/** The weekend record, refreshed every minute (it is a query on the backend, cheap to ask again). */
export function useRecord(): void {
  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const r = await api.record()
        if (alive) useStore.getState().setRecord(r)
      } catch {
        // keep the last numbers; the connection dot already says when the backend is gone
      }
    }
    void load()
    const t = setInterval(load, 60_000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])
}
