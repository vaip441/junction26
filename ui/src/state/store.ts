import { create } from 'zustand'
import type { StreamStatus } from '../lib/stream'
import type { MarketDetail, MarketEvent, MarketSummary, PricePoint, StreamEvent, Tick } from '../lib/types'

const MAX_TICKS = 500

interface State {
  markets: Record<string, MarketSummary>
  order: string[]
  details: Record<string, MarketDetail>
  ticks: Record<string, Tick[]>
  prices: Record<string, PricePoint[]>
  selectedId: string | null
  stream: StreamStatus
  /** Live `market` status steps for a plain-words question being worked on. */
  ask: { query: string; steps: MarketEvent[] } | null

  setMarkets: (list: MarketSummary[]) => void
  setDetail: (d: MarketDetail) => void
  setTicks: (id: string, ticks: Tick[]) => void
  setPrices: (id: string, prices: PricePoint[]) => void
  select: (id: string | null) => void
  setStream: (s: StreamStatus) => void
  startAsk: (query: string) => void
  clearAsk: () => void
  apply: (e: StreamEvent) => void
}

export const useStore = create<State>((set) => ({
  markets: {},
  order: [],
  details: {},
  ticks: {},
  prices: {},
  selectedId: null,
  stream: 'connecting',
  ask: null,

  setMarkets: (list) =>
    set((s) => ({
      markets: Object.fromEntries(list.map((m) => [m.id, m])),
      order: list.map((m) => m.id),
      selectedId: s.selectedId && list.some((m) => m.id === s.selectedId) ? s.selectedId : (list[0]?.id ?? null),
    })),
  setDetail: (d) =>
    set((s) => ({ details: { ...s.details, [d.id]: d }, markets: { ...s.markets, [d.id]: { ...s.markets[d.id], ...d } } })),
  setTicks: (id, ticks) => set((s) => ({ ticks: { ...s.ticks, [id]: ticks.slice(0, MAX_TICKS) } })),
  setPrices: (id, prices) => set((s) => ({ prices: { ...s.prices, [id]: prices } })),
  select: (id) => set({ selectedId: id }),
  setStream: (stream) => set({ stream }),
  startAsk: (query) => set({ ask: { query, steps: [] } }),
  clearAsk: () => set({ ask: null }),

  apply: (e) =>
    set((s) => {
      switch (e.type) {
        case 'tick': {
          const t = e.data
          const list = s.ticks[t.market_id] ?? []
          if (list.some((x) => x.id === t.id)) return {}
          const m = s.markets[t.market_id]
          return {
            ticks: { ...s.ticks, [t.market_id]: [t, ...list].slice(0, MAX_TICKS) },
            markets: m ? { ...s.markets, [m.id]: { ...m, ticks_today: m.ticks_today + 1 } } : s.markets,
          }
        }
        case 'tick_update': {
          const t = e.data
          const list = s.ticks[t.market_id]
          if (!list) return {}
          return { ticks: { ...s.ticks, [t.market_id]: list.map((x) => (x.id === t.id ? t : x)) } }
        }
        case 'price': {
          const { market_id, ts, price } = e.data
          const m = s.markets[market_id]
          const points = s.prices[market_id]
          return {
            markets: m ? { ...s.markets, [market_id]: { ...m, price } } : s.markets,
            prices: points ? { ...s.prices, [market_id]: [...points, { ts, price }] } : s.prices,
          }
        }
        case 'market': {
          const ev = e.data
          if (ev.status === 'deleted' && ev.market_id) {
            const { [ev.market_id]: _gone, ...markets } = s.markets
            return {
              markets,
              order: s.order.filter((id) => id !== ev.market_id),
              selectedId: s.selectedId === ev.market_id ? (s.order.find((id) => id !== ev.market_id) ?? null) : s.selectedId,
            }
          }
          if (ev.query && s.ask && ev.query === s.ask.query) {
            return { ask: { ...s.ask, steps: [...s.ask.steps, ev] } }
          }
          return {}
        }
        default:
          return {}
      }
    }),
}))

export const selectMarketList = (s: State): MarketSummary[] =>
  s.order.map((id) => s.markets[id]).filter((m): m is MarketSummary => Boolean(m))
