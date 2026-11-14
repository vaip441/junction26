import { useEffect } from 'react'
import { api } from '../lib/api'
import { announceTick } from '../lib/bus'
import { openStream } from '../lib/stream'
import { useStore } from '../state/store'

async function refreshMarkets() {
  try {
    useStore.getState().setMarkets(await api.markets())
  } catch {
    // backend unreachable: the connection dot already says so
  }
}

/** Opens the one app-wide stream, loads the market list, and refetches after a dropped connection. */
export function useStream(): void {
  useEffect(() => {
    void refreshMarkets()
    return openStream({
      onEvent: (e) => {
        const store = useStore.getState()
        store.apply(e)
        if (e.type === 'tick') announceTick(e.data)
        // a market the list has not seen yet (new, or tracked from another screen): reload the list
        if (e.type === 'market' && e.data.market_id && !store.markets[e.data.market_id] && e.data.status !== 'deleted') {
          void refreshMarkets()
        }
        // the backend fills a new market's tape and sources in one burst, without a tick event each: fetch them
        if (e.type === 'market' && e.data.status === 'ready' && e.data.market_id) {
          void refreshMarkets()
          if (e.data.market_id === useStore.getState().selectedId) void loadMarket(e.data.market_id)
        }
      },
      onStatus: (s) => useStore.getState().setStream(s),
      onReconnect: () => {
        void refreshMarkets()
        const id = useStore.getState().selectedId
        if (id) void loadMarket(id)
      },
    })
  }, [])
}

/** First paint for one market: detail, ticks and prices. The stream keeps them current afterwards. */
export async function loadMarket(id: string): Promise<void> {
  const store = useStore.getState()
  const [detail, ticks, prices] = await Promise.allSettled([api.market(id), api.ticks(id), api.prices(id)])
  if (detail.status === 'fulfilled') store.setDetail(detail.value)
  if (ticks.status === 'fulfilled') store.setTicks(id, ticks.value)
  if (prices.status === 'fulfilled') store.setPrices(id, prices.value)
}
