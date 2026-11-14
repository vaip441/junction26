// Mock of the terminal backend, for building and testing the UI without the real one.
//
// Serves the whole "Interface for the frontend" contract (docs/superpowers/specs/2026-11-13-terminal-design.md)
// with made-up data, and keeps the stream busy: prices drift, new ticks arrive, and a strong call is often
// followed by a move its way, so the tape's lifecycle badges change while you watch. Every market title starts
// with "MOCK" so mock data is never mistaken for real data on a screenshot.
//
//   node mock/server.mjs              port 8765, writes open
//   MOCK_KEY=secret node ...          writes need X-Terminal-Key: secret (to test the key prompt)
//   MOCK_QUIET=1 node ...             no scripted live ticks (prices still drift)
//
// Magic words, to reach error and edge states on purpose:
//   ask "fail ..."          -> 502 after "searching venues" (search failed)
//   ask "hello"/"asdf"      -> 422 not a question
//   ask "... made up ..."   -> no contract matches: a made-up market, price null until a price event arrives
//   say/type "fail503 ..."  -> 503 scoring unavailable
// Words with good/win/great/... score up, bad/lose/broken/... score down, anything else mostly no effect.

import http from 'node:http'

const PORT = Number(process.env.MOCK_PORT ?? 8765)
const KEY = process.env.MOCK_KEY ?? ''
const QUIET = Boolean(process.env.MOCK_QUIET)
const WINDOW = 900

const now = () => Date.now() / 1000
const rand = (a, b) => a + Math.random() * (b - a)
const pick = (xs) => xs[Math.floor(Math.random() * xs.length)]
const clamp = (p) => Math.min(99, Math.max(1, p))
const round = (p) => Math.round(p * 10) / 10
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** Same log-odds nudge as terminal/pricing.py, so the demo market moves like the real one. */
function nudge(price, strength, k = 0.4) {
  const p = clamp(price) / 100
  const x = Math.log(p / (1 - p)) + k * strength
  return clamp(100 / (1 + Math.exp(-x)))
}

// ---- store ---------------------------------------------------------------------------------------------

/** id -> { id, venue, title, url, rules, queries, lead_id, poll_seconds, created } */
const markets = new Map()
/** id -> [{ ts, price }] in time order */
const prices = new Map()
/** id -> [tick] newest first */
const ticks = new Map()
let nextTickId = 1
const startedAt = now()

function addMarket(m) {
  markets.set(m.id, { url: null, rules: 'Mock market: made-up rules.', queries: [], lead_id: null, poll_seconds: 900, created: now(), ...m })
  prices.set(m.id, prices.get(m.id) ?? [])
  ticks.set(m.id, ticks.get(m.id) ?? [])
}

function addPrice(id, ts, price) {
  const list = prices.get(id)
  list.push({ ts, price: round(price) })
  list.sort((a, b) => a.ts - b.ts)
}

function priceAt(id, ts) {
  let found = null
  for (const p of prices.get(id) ?? []) {
    if (p.ts > ts) break
    found = p.price
  }
  return found
}

const latest = (id) => priceAt(id, Infinity)

/** A random walk of `hours` ending at `end`, one point every `step` seconds. */
function history(id, end, hours = 30, step = 600, vol = 0.8) {
  const t1 = now()
  let p = end
  const points = []
  for (let t = t1; t > t1 - hours * 3600; t -= step) {
    points.push({ ts: t, price: round(p) })
    p = clamp(p + rand(-vol, vol))
  }
  for (const pt of points.reverse()) addPrice(id, pt.ts, pt.price)
}

function makeTick(marketId, f) {
  const verdict = f.verdict ?? 'none'
  const confidence = f.confidence ?? 0.7
  const side = (1 - confidence) / 2
  const [up, down] = verdict === 'up' ? [confidence, side] : verdict === 'down' ? [side, confidence] : [side, side]
  const ts = f.ts ?? now()
  const strength = verdict === 'none' ? 0 : (verdict === 'up' ? 1 : -1) * Math.abs(f.strength ?? 0.4)
  return {
    id: nextTickId++, market_id: marketId, ts, published_ts: f.published_ts === undefined ? ts : f.published_ts,
    kind: f.kind ?? 'article', source: f.source ?? 'reuters.com', url: f.url ?? null, headline: f.headline,
    up: round(up * 1000) / 1000, none: round((1 - up - down) * 1000) / 1000, down: round(down * 1000) / 1000,
    strength, verdict, confidence, price_at: f.price_at === undefined ? priceAt(marketId, ts) : f.price_at,
    test: f.kind === 'mic' || f.kind === 'typed', backfill: f.backfill ?? false,
    likes: f.kind === 'post' && f.source?.startsWith('x.com') ? Math.round(rand(20, 4000)) : null,
    replies: f.kind === 'post' && f.source?.startsWith('x.com') ? Math.round(rand(2, 300)) : null,
  }
}

function addTick(t) {
  ticks.get(t.market_id).unshift(t)
  return t
}

function summary(m) {
  const t = now()
  const price = latest(m.id)
  const old = priceAt(m.id, t - 86400)
  const dayStart = new Date().setHours(0, 0, 0, 0) / 1000
  return {
    id: m.id, venue: m.venue, title: m.title, url: m.url, price,
    change_24h: price == null || old == null ? null : round(price - old),
    ticks_today: ticks.get(m.id).filter((x) => x.ts >= dayStart).length,
    made_up: m.venue === 'made_up', poll_seconds: m.poll_seconds,
  }
}

function detail(m) {
  const counts = new Map()
  for (const t of ticks.get(m.id)) {
    const c = counts.get(t.source) ?? { source: t.source, ticks: 0, moved: 0 }
    c.ticks += 1
    if (t.verdict !== 'none') c.moved += 1
    counts.set(t.source, c)
  }
  return {
    ...summary(m), rules: m.rules, queries: m.queries,
    related: [...markets.values()].filter((r) => r.lead_id === m.id).map(summary), pages: [],
    sources: [...counts.values()].sort((a, b) => b.ticks - a.ticks),
  }
}

// Headlines and sources for scripted ticks.
const LIVE_HEADLINES = {
  up: ['Report: board has shortlisted an internal successor', 'Insider buying spikes ahead of announcement', 'Exec spotted at investor dinner, sources say a deal is close',
    'Filing shows new executive compensation package', 'Bank raises its odds of a change in the next quarter'],
  down: ['Company denies any leadership change is planned', 'Key candidate signs multi-year retention deal', 'Regulator opens a review that could delay the move',
    'Spokesperson: "nothing to announce"', 'Earnings call says leadership is staying put'],
  none: ['Shares flat in early trading', 'Conference schedule published', 'Analyst note repeats earlier view', 'Weekly roundup of chip news'],
}
const SOURCES = ['reuters.com', 'bloomberg.com', 'ft.com', 'cnbc.com', 'theinformation.com', 'x.com/marketsdesk', 'reddit.com/r/stocks', 'sec.gov']

// ---- seed data -----------------------------------------------------------------------------------------

const DEMO = 'mu-demo'
addMarket({ id: DEMO, venue: 'made_up', title: 'MOCK · Will this team win the Context.dev challenge?', poll_seconds: 0,
  rules: 'Resolves yes if this team is announced as the winner of the Context.dev challenge at Junction 2026.' })
addPrice(DEMO, now() - 3600, 20)

// The Nvidia market carries one tick in every lifecycle state, on a price path built to produce them.
const NV = 'mock-nvidia-ceo'
addMarket({ id: NV, venue: 'polymarket', title: 'MOCK · Will Ian Buck be the next CEO of Nvidia?', poll_seconds: 60,
  url: 'https://polymarket.com/event/next-ceo-of-nvidia/will-ian-buck-be-the-next-ceo-of-nvidia',
  queries: ['Ian Buck Nvidia CEO', 'Jensen Huang succession', 'Nvidia leadership change'] })
{
  const m = (mins) => now() - mins * 60
  history(NV, 40, 30, 600, 0.6)
  prices.set(NV, prices.get(NV).filter((p) => p.ts < m(180)))
  for (const [mins, p] of [[180, 40], [115, 44], [100, 45], [80, 48], [70, 48], [40, 48.3], [30, 50], [9, 51], [6, 53], [0.5, 53.2]]) {
    addPrice(NV, m(mins), p)
  }
  const seed = [
    [200, { verdict: 'up', strength: 0.6, confidence: 0.8, backfill: true, headline: 'Earlier coverage: Nvidia succession talk resurfaces after GTC' }],
    [120, { verdict: 'up', strength: 0.6, confidence: 0.8, headline: 'Jensen Huang said to be weighing a step back from day-to-day role', source: 'bloomberg.com' }],
    [90, { verdict: 'down', strength: 0.4, confidence: 0.7, headline: 'Nvidia board reaffirms full confidence in current leadership', source: 'reuters.com' }],
    [60, { verdict: 'up', strength: 0.3, confidence: 0.65, headline: 'Ian Buck keynote moved to a bigger hall at GTC', source: 'theverge.com' }],
    [10, { verdict: 'up', strength: 0.5, confidence: 0.75, headline: 'Analysts list Buck as frontrunner in succession note', source: 'cnbc.com' }],
    [8, { verdict: 'down', strength: 0.35, confidence: 0.6, kind: 'post', source: 'x.com/chipwatcher', headline: 'Hearing Buck is in talks with a rival chipmaker. Big if true.' }],
    [3, { verdict: 'up', strength: 0.8, confidence: 0.9, kind: 'filing', source: 'sec.gov', headline: 'Nvidia 8-K names Ian Buck president and chief operating officer' }],
    [2, { verdict: 'down', strength: 0.2, confidence: 0.55, kind: 'post', source: 'reddit.com/r/nvidia', headline: 'Unconfirmed: Buck skipped the all-hands today', published_ts: null }],
    [1, { verdict: 'none', confidence: 0.8, headline: 'Nvidia stock closes flat ahead of earnings', source: 'marketwatch.com' }],
  ]
  for (const [mins, f] of seed) addTick(makeTick(NV, { ...f, ts: m(mins) }))
  for (const [id, title, venue, p, url] of [
    ['mock-nvidia-ceo-2027', 'MOCK · Nvidia CEO change announced by March 2027?', 'polymarket', 18, 'https://polymarket.com/event/next-ceo-of-nvidia/nvidia-ceo-change-by-march-2027'],
    ['mock-kx-nvidia-ceo', 'MOCK · Will Ian Buck be named Nvidia CEO? (Kalshi)', 'kalshi', 51, 'https://kalshi.com/markets/kxnvdaceo/nvidia-ceo/kxnvdaceo-buck'],
  ]) {
    addMarket({ id, venue, title, lead_id: NV, url })
    history(id, p, 30, 1800, 0.5)
  }
}

const AI = 'mock-openai-anthropic-ipo'
addMarket({ id: AI, venue: 'kalshi', title: 'MOCK · OpenAI or Anthropic: which IPOs first?', url: 'https://kalshi.com/markets/kxoaianth' })
history(AI, 62, 30, 900, 1.2)
for (let i = 0; i < 14; i++) {
  const v = pick(['up', 'up', 'down', 'none', 'none'])
  addTick(makeTick(AI, { ts: now() - rand(600, 86000), verdict: v, strength: rand(0.1, 0.9), confidence: rand(0.5, 0.95),
    backfill: i < 5, headline: pick(LIVE_HEADLINES[v]), source: pick(SOURCES) }))
}
ticks.get(AI).sort((a, b) => b.ts - a.ts)

// ---- stream --------------------------------------------------------------------------------------------

const clients = new Set()

function send(event, data) {
  const frame = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
  for (const res of clients) res.write(frame)
}

function emitTick(t) {
  addTick(t)
  send('tick', t)
  // Like the real backend, the publish time can arrive a minute or two later as a tick_update.
  if (t.published_ts == null && t.kind === 'article') {
    setTimeout(() => {
      t.published_ts = t.ts - rand(60, 1800)
      send('tick_update', t)
    }, rand(20, 60) * 1000)
  }
}

function emitPrice(id, price, ts = now()) {
  addPrice(id, ts, price)
  send('price', { market_id: id, ts, price: round(price) })
}

// ---- live activity -------------------------------------------------------------------------------------

function venueMarkets() {
  return [...markets.values()].filter((m) => m.venue !== 'made_up')
}

/** Drift every venue price a little; related contracts too, so the side panel moves. */
setInterval(() => {
  for (const m of venueMarkets()) {
    const p = latest(m.id)
    if (p != null && Math.random() < 0.5) emitPrice(m.id, clamp(p + rand(-0.4, 0.4)))
  }
}, 4000)

/** A new scored item on a lead venue market every 12-25 s; a strong call is usually followed by a move its way. */
async function liveTicks() {
  for (;;) {
    await sleep(rand(12, 25) * 1000)
    const leads = venueMarkets().filter((m) => m.lead_id == null)
    if (QUIET || leads.length === 0) continue
    const m = pick(leads)
    const verdict = pick(['up', 'down', 'none', 'up', 'down'])
    const strength = rand(0.15, 0.95)
    const kind = pick(['article', 'article', 'post', 'filing', 'page'])
    const source = kind === 'post' ? pick(['x.com/marketsdesk', 'x.com/chipwatcher', 'reddit.com/r/stocks']) : kind === 'filing' ? 'sec.gov' : pick(SOURCES.slice(0, 5))
    const t = makeTick(m.id, { verdict, strength, confidence: rand(0.5, 0.95), kind, source, headline: pick(LIVE_HEADLINES[verdict]),
      published_ts: kind === 'article' && Math.random() < 0.5 ? null : now() - rand(5, 300) })
    emitTick(t)
    if (verdict !== 'none' && Math.random() < 0.6 + 0.3 * strength) {
      // the market catches up over the next couple of minutes
      const dir = verdict === 'up' ? 1 : -1
      const steps = 4
      for (let i = 1; i <= steps; i++) {
        setTimeout(() => {
          const p = latest(m.id)
          if (p != null) emitPrice(m.id, clamp(p + (dir * strength * rand(1.5, 4)) / steps))
        }, i * rand(15, 35) * 1000)
      }
    }
  }
}
void liveTicks()

/** A deciding page checked now and then. */
setInterval(() => {
  const m = pick(venueMarkets())
  if (m) send('page_check', { market_id: m.id, url: m.url, status: 'unchanged', checked_ts: now() })
}, 30000)

// ---- writes --------------------------------------------------------------------------------------------

const UP_WORDS = /\b(win|wins|winning|great|amazing|impressive|best|love|brilliant|strong|fast|wow|yes|beautiful|clever)\b/i
const DOWN_WORDS = /\b(lose|losing|bad|boring|broken|slow|worst|weak|bug|crash|no|fail|failed|meh|confusing)\b/i

function fakeScore(text) {
  const up = UP_WORDS.test(text)
  const down = DOWN_WORDS.test(text)
  if (up && !down) return { verdict: 'up', strength: rand(0.35, 0.9), confidence: rand(0.65, 0.95) }
  if (down && !up) return { verdict: 'down', strength: rand(0.35, 0.9), confidence: rand(0.65, 0.95) }
  return { verdict: 'none', strength: 0, confidence: rand(0.5, 0.8) }
}

async function postTick(m, body) {
  const text = String(body.text ?? '').trim()
  if (!text) return [422, { detail: 'say something first' }]
  await sleep(rand(700, 1600)) // scoring takes a moment on the real backend too
  if (/fail503/i.test(text)) return [503, { detail: 'scoring unavailable, try again' }]
  const s = fakeScore(text)
  const t = makeTick(m.id, { ...s, kind: body.kind === 'mic' ? 'mic' : 'typed', source: body.kind === 'mic' ? 'microphone' : 'keyboard', headline: text, price_at: latest(m.id) })
  if (m.venue === 'made_up' && t.price_at != null) emitPrice(m.id, nudge(t.price_at, t.strength))
  emitTick(t)
  return [200, t]
}

function slug(text) {
  return `mock-${text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40)}`
}

/** Fill a new market's tape in one burst, like the backend's instant fill. */
function instantFill(id) {
  const n = Math.round(rand(6, 12))
  for (let i = 0; i < n; i++) {
    const v = pick(['up', 'down', 'none', 'none'])
    const ts = now() - rand(3600, 3 * 86400)
    addTick(makeTick(id, { ts, verdict: v, strength: rand(0.1, 0.8), confidence: rand(0.5, 0.9), backfill: true, headline: pick(LIVE_HEADLINES[v]), source: pick(SOURCES) }))
  }
  ticks.get(id).sort((a, b) => b.ts - a.ts)
  return n
}

async function postMarket(body) {
  const query = String(body.query ?? '').trim()
  const isLink = /^https?:\/\//.test(query)
  const status = (s, more = {}) => send('market', { market_id: null, query, status: s, ...more })
  if (!query) return [422, { detail: 'that does not look like a question about something that could happen' }]

  if (isLink) {
    if (!/kalshi\.com|polymarket\.com/.test(query)) return [422, { detail: 'not a Kalshi or Polymarket link' }]
    if (/closed/.test(query)) return [404, { detail: 'that market is closed or missing' }]
  } else {
    status('searching venues')
    await sleep(1200)
    if (/^fail\b/i.test(query)) {
      status('failed')
      return [502, { detail: 'could not reach search, try again' }]
    }
    if (/^(hello|hi|asdf|test)$/i.test(query) || query.length < 4) {
      status('failed')
      return [422, { detail: 'that does not look like a question about something that could happen' }]
    }
    const madeUp = /made up/i.test(query)
    status('found contracts', { count: madeUp ? 0 : 2 })
    await sleep(1500)
    if (madeUp) {
      const id = `mu-${slug(query).slice(5)}`
      if (!markets.has(id)) addMarket({ id, venue: 'made_up', title: `MOCK · ${query.replace(/\?*$/, '?')}` })
      send('market', { market_id: id, query, status: 'made up' })
      setTimeout(() => emitPrice(id, rand(10, 60)), 6000) // starting odds from coverage, a little later
      setTimeout(() => send('market', { market_id: id, status: 'ready', ticks: instantFill(id) }), 8000)
      return [200, { ...detail(markets.get(id)), matched: false }]
    }
  }

  // a related contract asked for by its own link becomes a market of its own, like the real backend
  const related = isLink ? [...markets.values()].find((m) => m.url === query && m.lead_id) : undefined
  if (related) related.lead_id = null
  const id = related?.id ?? slug(isLink ? query.split('/').filter(Boolean).pop() : query)
  if (!markets.has(id)) {
    addMarket({ id, venue: isLink && /kalshi/.test(query) ? 'kalshi' : 'polymarket', url: isLink ? query : null, poll_seconds: Number(body.poll_seconds ?? 900),
      title: `MOCK · ${isLink ? id.slice(5).replace(/-/g, ' ') : query.replace(/\?*$/, '?')}` })
    history(id, rand(5, 90), 30, 1200, 1)
  }
  // Like the real backend (track() in terminal/api.py): no `query` on this one, even for plain words.
  send('market', { market_id: id, status: 'tracking' })
  setTimeout(() => send('market', { market_id: id, status: 'finding sources' }), 800)
  setTimeout(() => {
    const n = instantFill(id)
    send('market', { market_id: id, status: 'ready', ticks: n })
  }, 4000)
  return [200, { ...detail(markets.get(id)), matched: true }]
}

// ---- http ----------------------------------------------------------------------------------------------

let creditsUsed = 0

function readBody(req) {
  return new Promise((resolve) => {
    let raw = ''
    req.on('data', (c) => (raw += c))
    req.on('end', () => {
      try {
        resolve(raw ? JSON.parse(raw) : {})
      } catch {
        resolve({})
      }
    })
  })
}

async function route(req, url) {
  const parts = url.pathname.split('/').filter(Boolean).map(decodeURIComponent)
  const write = req.method !== 'GET'
  if (write && KEY && req.headers['x-terminal-key'] !== KEY) return [401, { detail: 'missing or wrong X-Terminal-Key header' }]

  if (req.method === 'GET' && url.pathname === '/markets') return [200, [...markets.values()].filter((m) => m.lead_id == null).map(summary)]
  if (req.method === 'POST' && url.pathname === '/markets') return postMarket(await readBody(req))
  if (req.method === 'GET' && url.pathname === '/record') {
    return [200, { called: 142, moved: 97, same_way: 71, window_seconds: WINDOW, since: startedAt - 2 * 86400 }]
  }
  if (req.method === 'GET' && url.pathname === '/status') {
    creditsUsed += Math.round(rand(0, 6))
    const keys = [1, 2, 3].map((key) => ({ key, used_last_minute: Math.round(rand(0, 10)), per_minute: 10,
      resting_seconds: Math.random() < 0.1 ? Math.round(rand(1, 20)) : 0, credits_remaining: 50000 - 3000 * key - creditsUsed }))
    return [200, { context_dev: { keys, per_minute: 30, used_last_minute: keys.reduce((a, k) => a + k.used_last_minute, 0) } }]
  }

  if (parts[0] === 'markets' && parts[1]) {
    const m = markets.get(parts[1])
    if (!m || (m.lead_id && req.method === 'DELETE')) return [404, { detail: 'no such market' }]
    if (parts.length === 2 && req.method === 'GET') return [200, detail(m)]
    if (parts.length === 2 && req.method === 'DELETE') {
      if (m.id === DEMO) return [409, { detail: 'the demo market cannot be deleted' }]
      for (const r of [...markets.values()]) if (r.id === m.id || r.lead_id === m.id) markets.delete(r.id)
      send('market', { market_id: m.id, status: 'deleted' })
      return [200, { deleted: m.id }]
    }
    if (parts[2] === 'ticks' && req.method === 'GET') {
      const limit = Math.min(500, Math.max(1, Number(url.searchParams.get('limit') ?? 100)))
      return [200, ticks.get(m.id).slice(0, limit)]
    }
    if (parts[2] === 'ticks' && req.method === 'POST') return postTick(m, await readBody(req))
    if (parts[2] === 'prices' && req.method === 'GET') {
      const since = Number(url.searchParams.get('since') ?? 0)
      return [200, prices.get(m.id).filter((p) => p.ts >= since)]
    }
  }
  return [404, { detail: 'not found' }]
}

const server = http.createServer(async (req, res) => {
  res.setHeader('access-control-allow-origin', '*')
  res.setHeader('access-control-allow-methods', '*')
  res.setHeader('access-control-allow-headers', '*')
  if (req.method === 'OPTIONS') return res.writeHead(204).end()
  const url = new URL(req.url, `http://localhost:${PORT}`)

  if (url.pathname === '/stream') {
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive' })
    res.write(': connected\n\n')
    clients.add(res)
    const keepalive = setInterval(() => res.write(': keepalive\n\n'), 15000)
    req.on('close', () => {
      clearInterval(keepalive)
      clients.delete(res)
    })
    return
  }

  try {
    const [status, body] = await route(req, url)
    res.writeHead(status, { 'content-type': 'application/json' })
    res.end(JSON.stringify(body))
  } catch (e) {
    res.writeHead(500, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ detail: `mock crashed: ${e.message}` }))
  }
})

server.listen(PORT, () => {
  console.log(`mock terminal backend on http://localhost:${PORT}${KEY ? ' (writes need the key)' : ''}${QUIET ? ' (quiet)' : ''}`)
})
