import { useEffect } from 'react'
import { api } from '../lib/api'
import { useStore } from '../state/store'
import { loadMarket } from './useStream'

/** The selected market's summary, detail, ticks and prices, loading them the first time it is selected. */
export function useSelectedMarket() {
  const id = useStore((s) => s.selectedId)
  const market = useStore((s) => (id ? s.markets[id] : undefined))
  const detail = useStore((s) => (id ? s.details[id] : undefined))
  const ticks = useStore((s) => (id ? s.ticks[id] : undefined))
  const prices = useStore((s) => (id ? s.prices[id] : undefined))

  useEffect(() => {
    if (!id) return
    void loadMarket(id)
    // sources and related prices change slowly: refresh the detail once a minute
    const t = setInterval(() => {
      api
        .market(id)
        .then((d) => useStore.getState().setDetail(d))
        .catch(() => {})
    }, 60_000)
    return () => clearInterval(t)
  }, [id])

  return { id, market, detail, ticks, prices }
}
