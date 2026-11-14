import { create } from 'zustand'
import type { StreamStatus } from '../lib/stream'
import type { MarketDetail, MarketEvent, MarketSummary, Move, PricePoint, RuleRef, StreamEvent, Tick, WeekendRecord } from '../lib/types'

const MAX_TICKS = 500
const MAX_MOVES = 100

/** The tabs under the chart. */
export type Tab = 'moves' | 'sources' | 'related' | 'rules'

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
  /** When the backend said the market is ready (its tape filled); the search took `finished - started`. */
  finished: number | null
  /** The market's own panel is uncovered: the question no longer fills the centre of the screen. */
  opened: boolean
  /** The question has finished fading away: it is off the screen. */
  uncovered: boolean
  /** Events that name a market, received before the POST said which market this ask became. */
  early: MarketEvent[]
}

/** Context.dev use while a question is worked on: credits spent since it was asked, and requests this minute. */
export interface Meter {
  credits: number | null
  perMinute: number
}

interface State {
  markets: Record<string, MarketSummary>
  order: string[]
  details: Record<string, MarketDetail>
  ticks: Record<string, Tick[]>
  prices: Record<string, PricePoint[]>
  /** "Why did it move?": price jumps with their likely cause, newest first. Real markets only. */
  moves: Record<string, Move[]>
  /** A move that arrived on the stream just now, for the banner over the chart. */
  liveMove: Move | null
  tab: Tab
  /** A rules sentence to scroll to and flash in the Rules tab; `n` makes a repeat click count. */
  focusRule: { start: number; end: number; n: number } | null
  selectedId: string | null
  stream: StreamStatus
  /** Live `market` status steps for a plain-words question being worked on. */
  ask: Ask | null
  meter: Meter | null
  pending: Record<string, PendingTick[]>
  /** Stage controls. */
  micOn: boolean
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
  setMoves: (id: string, moves: Move[]) => void
  clearLiveMove: () => void
  setTab: (tab: Tab) => void
  showRule: (rule: RuleRef) => void
  select: (id: string | null) => void
  setStream: (s: StreamStatus) => void
  startAsk: (query: string) => void
  askDone: (market: MarketDetail & { matched: boolean }) => void
  askFailed: (error: string) => void
  clearAsk: () => void
  openAsk: () => void
  uncoverAsk: () => void
  finishAsk: () => void
  setMeter: (m: Meter | null) => void
  apply: (e: StreamEvent) => void
  addPending: (marketId: string, text: string, kind: 'mic' | 'typed') => number
  removePending: (marketId: string, key: number) => void
  setMic: (on: boolean) => void
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
  moves: {},
  liveMove: null,
  tab: 'moves',
  focusRule: null,
  selectedId: null,
  stream: 'connecting',
  ask: null,
  meter: null,
  pending: {},
  micOn: false,
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
  setMoves: (id, moves) => set((s) => ({ moves: { ...s.moves, [id]: moves.slice(0, MAX_MOVES) } })),
  clearLiveMove: () => set({ liveMove: null }),
  setTab: (tab) => set({ tab }),
  showRule: (rule) => set((s) => ({ tab: 'rules', focusRule: { start: rule.start, end: rule.end, n: (s.focusRule?.n ?? 0) + 1 } })),
  select: (id) => set({ selectedId: id }),
  setStream: (stream) => set({ stream }),
  startAsk: (query) =>
    set({
      ask: { query, steps: [], marketId: null, matched: null, error: null, started: Date.now() / 1000, finished: null, opened: false, uncovered: false, early: [] },
      meter: null,
    }),
  askDone: (d) =>
    set((s) => {
      // a market tracked before answers at once with its tape already filled: there is no search to wait for
      const known = d.sources.length > 0
      const ask = s.ask
      // what the stream said about this market before the POST named it
      const early = ask ? ask.early.filter((ev) => ev.market_id === d.id) : []
      const ready = early.some((ev) => ev.status === 'ready')
      return {
      ask: ask
        ? { ...ask, marketId: d.id, matched: d.matched, steps: [...ask.steps, ...early], early: [],
            finished: known || ready ? Date.now() / 1000 : ask.finished }
        : ask,
      // the new market joins the list and is opened at once
      markets: { ...s.markets, [d.id]: { ...s.markets[d.id], ...d } },
      details: { ...s.details, [d.id]: d },
      order: s.order.includes(d.id) ? s.order : [...s.order, d.id],
      selectedId: d.id,
      }
    }),
  askFailed: (error) => set((s) => ({ ask: s.ask ? { ...s.ask, error } : s.ask })),
  clearAsk: () => set({ ask: null, meter: null }),
  openAsk: () => set((s) => (s.ask ? { ask: { ...s.ask, opened: true } } : {})),
  uncoverAsk: () => set((s) => (s.ask ? { ask: { ...s.ask, uncovered: true } } : {})),
  finishAsk: () => set((s) => (s.ask && s.ask.finished == null ? { ask: { ...s.ask, finished: Date.now() / 1000 } } : {})),
  setMeter: (meter) => set({ meter }),
  addPending: (marketId, text, kind) => {
    const key = ++pendingKey
    set((s) => ({ pending: { ...s.pending, [marketId]: [{ key, text, kind }, ...(s.pending[marketId] ?? [])] } }))
    return key
  },
  removePending: (marketId, key) =>
    set((s) => ({ pending: { ...s.pending, [marketId]: (s.pending[marketId] ?? []).filter((p) => p.key !== key) } })),
  setMic: (micOn) => set({ micOn }),
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
        case 'move': {
          const mv = e.data
          const list = s.moves[mv.market_id] ?? []
          if (list.some((x) => x.id === mv.id)) return {}
          // its cause is a whole tick again: it may carry a rule the copy on the tape lacks
          const tape = s.ticks[mv.market_id]
          const cause = mv.cause
          return {
            moves: { ...s.moves, [mv.market_id]: [mv, ...list].slice(0, MAX_MOVES) },
            liveMove: mv,
            ticks: tape && cause ? { ...s.ticks, [mv.market_id]: tape.map((x) => (x.id === cause.id ? cause : x)) } : s.ticks,
          }
        }
        case 'page_check': {
          // Context.dev has just checked the market's watched page
          const { market_id, url, ts, changed } = e.data
          const d = s.details[market_id]
          if (!d) return {}
          const pages = d.pages.map((p) => (p.url === url ? { ...p, checked_ts: ts, changed_ts: changed ? ts : p.changed_ts } : p))
          return { details: { ...s.details, [market_id]: { ...d, pages } } }
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
          if (ev.status === 'reset' && ev.market_id) {
            // the demo market, put back after a rehearsal: its tape, moves and prices start over (the price
            // event that follows gives the starting price)
            const id = ev.market_id
            const m = s.markets[id]
            return {
              ticks: { ...s.ticks, [id]: [] },
              moves: { ...s.moves, [id]: [] },
              prices: { ...s.prices, [id]: [] },
              pending: { ...s.pending, [id]: [] },
              markets: m ? { ...s.markets, [id]: { ...m, ticks_today: 0, change_24h: null } } : s.markets,
            }
          }
          const ask = s.ask
          if (ask && ((ev.query && ev.query === ask.query) || (ev.market_id && ev.market_id === ask.marketId))) {
            const finished = ev.status === 'ready' && ask.finished == null ? Date.now() / 1000 : ask.finished
            return { ask: { ...ask, steps: [...ask.steps, ev], finished } }
          }
          if (ask && ask.marketId == null && ev.market_id) {
            return { ask: { ...ask, early: [...ask.early, ev].slice(-20) } } // may be about the market being made
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
