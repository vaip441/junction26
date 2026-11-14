// Mirrors "Interface for the frontend" in docs/superpowers/specs/2026-11-13-terminal-design.md.
// Prices are percentages 0-100; timestamps are unix seconds.

export type Venue = 'kalshi' | 'polymarket' | 'made_up'
export type Verdict = 'up' | 'none' | 'down'
export type TickKind = 'article' | 'post' | 'filing' | 'page' | 'mic' | 'typed'

export interface MarketSummary {
  id: string
  venue: Venue
  title: string
  url: string | null
  price: number | null
  change_24h: number | null
  ticks_today: number
  made_up: boolean
  poll_seconds: number
}

export interface Source {
  source: string
  ticks: number
  moved: number
}

export interface MarketDetail extends MarketSummary {
  rules: string
  queries: string[] | null
  related: MarketSummary[]
  pages: unknown[]
  sources: Source[]
}

export interface Tick {
  id: number
  market_id: string
  ts: number
  published_ts: number | null
  kind: TickKind
  source: string
  url: string | null
  headline: string
  up: number
  none: number
  down: number
  strength: number
  verdict: Verdict
  confidence: number
  price_at: number | null
  test: boolean
  backfill: boolean
  likes: number | null
  replies: number | null
}

export interface PricePoint {
  ts: number
  price: number
}

export interface WeekendRecord {
  called: number
  moved: number
  same_way: number
  window_seconds: number
  since: number
}

/** A `market` stream event. While plain words are being worked on, market_id is null and query is set. */
export interface MarketEvent {
  market_id: string | null
  status: string
  query?: string
  /** On `found contracts`: how many groups of contracts matched. */
  count?: number
  /** On `ready`: how many items the instant fill put on the tape. */
  ticks?: number
}

export interface PriceEvent {
  market_id: string
  ts: number
  price: number
}

export type StreamEvent =
  | { type: 'tick'; data: Tick }
  | { type: 'tick_update'; data: Tick }
  | { type: 'price'; data: PriceEvent }
  | { type: 'market'; data: MarketEvent }
  | { type: 'page_check'; data: { market_id: string } & Record<string, unknown> }
