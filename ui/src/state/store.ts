import { create } from 'zustand'
import type { StreamStatus } from '../lib/stream'
import type { MarketDetail, MarketEvent, MarketSummary, PricePoint, StreamEvent, Tick, WeekendRecord } from '../lib/types'

const MAX_TICKS = 500

/** A spoken or typed sentence sent for scoring, shown on the tape until its scored tick arrives. */
export interface PendingTick {
  key: number
  text: string
  kind: 'mic' | 'typed'
}

let pendingKey = 0

/**
 * A link or question being turned into a tracked market. Its `market` events carry `query` until the
 * market exists; after that (tracking, finding sources, ready) only `market_id`, so both are followed.
 */
export interface Ask {
  query: string
  steps: MarketEvent[]
  /** Set once the POST answers with the market now tracked. */
  marketId: string | null
  /** False when no contract matched and a market was made up for the question. */
  matched: boolean | null
  error: string | null
  started: number
}

interface State {
  markets: Record<string, MarketSummary>
  order: string[]
  details: Record<string, MarketDetail>
  ticks: Record<string, Tick[]>
  prices: Record<string, PricePoint[]>
  selectedId: string | null
  stream: StreamStatus
  /** Live `market` status steps for a plain-words question being worked on. */
  ask: Ask | null
  pending: Record<string, PendingTick[]>
  /** Stage controls. */
  muted: boolean
  micOn: boolean
  presentation: boolean
  /** A write was refused for want of the key: the key prompt is open. */
  needKey: boolean
  record: WeekendRecord | null
  /** Latest streamed price of contracts that are not in the market list (related contracts). */
  otherPrices: Record<string, number>
  recordOpen: boolean

  setMarkets: (list: MarketSummary[]) => void
  setDetail: (d: MarketDetail) => void
  setTicks: (id: string, ticks: Tick[]) => void
  setPrices: (id: string, prices: PricePoint[]) => void
  select: (id: string | null) => void
  setStream: (s: StreamStatus) => void
  startAsk: (query: string) => void
  askDone: (market: MarketDetail & { matched: boolean }) => void
  askFailed: (error: string) => void
  clearAsk: () => void
  apply: (e: StreamEvent) => void
  addPending: (marketId: string, text: string, kind: 'mic' | 'typed') => number
  removePending: (marketId: string, key: number) => void
  toggleMute: () => void
  setMic: (on: boolean) => void
  togglePresentation: (on?: boolean) => void
  setNeedKey: (on: boolean) => void
  setRecord: (r: WeekendRecord) => void
  toggleRecord: (open?: boolean) => void
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
  pending: {},
  muted: false,
  micOn: false,
  presentation: false,
  needKey: false,
  record: null,
  otherPrices: {},
  recordOpen: false,

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
  startAsk: (query) =>
    set({ ask: { query, steps: [], marketId: null, matched: null, error: null, started: Date.now() / 1000 } }),
  askDone: (d) =>
    set((s) => ({
      ask: s.ask ? { ...s.ask, marketId: d.id, matched: d.matched } : s.ask,
      // the new market joins the list and is opened at once
      markets: { ...s.markets, [d.id]: { ...s.markets[d.id], ...d } },
      details: { ...s.details, [d.id]: d },
      order: s.order.includes(d.id) ? s.order : [...s.order, d.id],
      selectedId: d.id,
    })),
  askFailed: (error) => set((s) => ({ ask: s.ask ? { ...s.ask, error } : s.ask })),
  clearAsk: () => set({ ask: null }),
  addPending: (marketId, text, kind) => {
    const key = ++pendingKey
    set((s) => ({ pending: { ...s.pending, [marketId]: [{ key, text, kind }, ...(s.pending[marketId] ?? [])] } }))
    return key
  },
  removePending: (marketId, key) =>
    set((s) => ({ pending: { ...s.pending, [marketId]: (s.pending[marketId] ?? []).filter((p) => p.key !== key) } })),
  toggleMute: () => set((s) => ({ muted: !s.muted })),
  setMic: (micOn) => set({ micOn }),
  togglePresentation: (on) => set((s) => ({ presentation: on ?? !s.presentation })),
  setNeedKey: (needKey) => set({ needKey }),
  setRecord: (record) => set({ record }),
  toggleRecord: (open) => set((s) => ({ recordOpen: open ?? !s.recordOpen })),

  apply: (e) =>
    set((s) => {
      switch (e.type) {
        case 'tick': {
          const t = e.data
          const list = s.ticks[t.market_id] ?? []
          if (list.some((x) => x.id === t.id)) return {}
          const m = s.markets[t.market_id]
          // the scored version of a sentence we sent replaces its pending row (the POST may still be in flight)
          const waiting = s.pending[t.market_id] ?? []
          const match = t.test ? waiting.find((p) => p.text.trim() === t.headline.trim()) : undefined
          return {
            pending: match ? { ...s.pending, [t.market_id]: waiting.filter((p) => p !== match) } : s.pending,
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
          if (!m) return { otherPrices: { ...s.otherPrices, [market_id]: price } }
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
          const ask = s.ask
          if (ask && ((ev.query && ev.query === ask.query) || (ev.market_id && ev.market_id === ask.marketId))) {
            return { ask: { ...ask, steps: [...ask.steps, ev] } }
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
