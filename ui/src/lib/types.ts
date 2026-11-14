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

/** A sentence of a market's rules: `start` and `end` are character positions in its `rules` text. */
export interface RuleRef {
  start: number
  end: number
  text: string
  confidence: number
}

export interface MarketDetail extends MarketSummary {
  rules: string
  /** Companies the market is about, for the news index. */
  companies?: string[]
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
  /** The rules sentence that makes this tick matter: on spoken and typed ticks and on ticks that call a move. */
  rule?: RuleRef | null
}

/** "Why did it move?": the price went from `from` at `since` to `to` at `ts`. Real markets only. */
export interface Move {
  id: number
  market_id: string
  ts: number
  since: number
  from: number
  to: number
  /** The tick named as the most likely reason; null when nothing published around the move explains it. */
  cause: Tick | null
  confidence: number | null
  rule: RuleRef | null
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
  /** On `ready`: how many items the first fill stored (most of them hidden). */
  ticks?: number
  /** On `found contracts`: one card per market found. */
  contracts?: FoundMarket[]
  /** On `picked`: which card won, and the contract of it that leads. */
  winner?: number
  venue?: Venue
  title?: string
  price?: number | null
  /** On `finding sources`: the phrases the web is searched with. */
  queries?: string[]
  /** On `scoring`: how many items the searches found, and how many of them are scored. */
  found?: number
  scored?: number
}

/** A market found for a question, shown while the model picks one. */
export interface FoundMarket {
  venue: Venue
  title: string
  price: number | null
  /** How many contracts the market holds. */
  contracts: number
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
  | { type: 'move'; data: Move }
  | { type: 'market'; data: MarketEvent }
  | { type: 'page_check'; data: { market_id: string } & Record<string, unknown> }
