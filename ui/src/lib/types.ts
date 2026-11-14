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

/** A page a Context.dev monitor checks every ten minutes; a change that bears on the market becomes a `page` tick. */
export interface WatchedPage {
  url: string
  title: string | null
  /** Null until the first check, and until the first change. */
  checked_ts: number | null
  changed_ts: number | null
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
  /** The page Context.dev watches for this market; empty until one is found (needs a public backend address). */
  pages: WatchedPage[]
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
  /** The rules sentence that makes this tick matter: only on ticks called up or down. For a spoken or typed
   * one it is the closest sentence, however weak, so its confidence is not shown. */
  rule?: RuleRef | null
}

/** A related contract that moved over the same stretch as a move: often the whole story when no news explains it. */
export interface MovedWith {
  id: string
  title: string
  from: number
  to: number
}

/**
 * "Why did it move?": the price went from `from` at `since` to `to` at `ts`. Either a jump the terminal saw
 * itself, or (`asked`) the market's last day, explained on request.
 */
export interface Move {
  id: number
  market_id: string
  ts: number
  since: number
  from: number
  to: number
  /** The move in plain words, enough to show by itself. */
  summary: string
  /** Whether an item is taken as the reason: then it is `cause`; otherwise `closest` holds the nearest item. */
  explained: boolean
  /** Explained on request (the last day), not a jump the terminal saw. */
  asked: boolean
  cause: Tick | null
  /** The nearest item when nothing explains the move: "closest news", never the reason. */
  closest: Tick | null
  confidence: number | null
  rule: RuleRef | null
  related: MovedWith[]
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
  /** On `scoring`: how many items the searches found; each is scored, and those worth showing arrive as ticks. */
  found?: number
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
  | { type: 'page_check'; data: { market_id: string; url: string; ts: number; changed: boolean } }
