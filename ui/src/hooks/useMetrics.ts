import { useEffect } from 'react'
import { api } from '../lib/api'
import { useStore } from '../state/store'

/** Measured latency and the backend's mode, asked again every half minute. An older backend has no such route: then nothing is shown. */
export function useMetrics(): void {
  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const m = await api.metrics()
        if (alive) useStore.getState().setMetrics(m)
      } catch {
        // unreachable or not there: the status line shows no figures rather than old or made-up ones
      }
    }
    void load()
    const t = setInterval(load, 30_000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])
}
