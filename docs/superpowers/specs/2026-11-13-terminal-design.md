# Prediction market terminal: design

Junction 2026, Context.dev challenge ("build a product that reacts to the live web").
Status: draft, awaiting Georg's approval. Items marked **(call)** were decided by the
author of this document, not by Georg, and are open to correction.

## Intent

A terminal that watches the live web for anything bearing on a prediction market and
says, for each new item, whether it pushes the YES price up, down, or not at all, and
how confidently. Georg trades these markets and wants to see the news before the price
has finished moving.

The hackathon is won on the demo. Georg's stated priority, above everything else, is a
demo that is very memorable and unique.

## Vocabulary

- **Market**: one contract on one venue: a yes/no question with a YES price. Prices are
  shown and sent as percentages from 0 to 100 (Georg's decision: easier to understand
  than cents). A venue price of 82 cents is 82%. Changes are
  in percentage points ("+18 pts"), so a move from 64% to 82% is never read as "+18%
  of 64" **(call)**.
- **Lead market and related contracts** **(call)**: when a link or question matches
  several contracts on the same underlying event (other deadlines, the other venue),
  the one pasted, or the best match, is the lead market. Only the lead market has a
  tape: each item is scored once, against it. The others are stored as its related
  contracts and carry prices only. A related contract becomes a market of its own
  only if someone adds it by its own link.
- **Headline market**: the one market the demo leads with (the Nvidia CEO-exit
  market). It is polled fastest. Any market can be given this treatment; nothing
  about it is hard-coded.
- **Tick**: one new item attached to a market: an article, a filing, a change on a
  watched page, a sentence from the microphone, or a typed headline.
- **Score**: Gemini Decision 1's verdict on a tick: three probabilities (up, no
  effect, down) and a strength from -1 (down a lot) to 1 (up a lot).
- **Made-up market**: a market we make up, with no venue behind it. Its price is driven
  only by scored ticks.

## Goals

1. **The market on us (demo opener).** A made-up market, "Will this team win the
   Context.dev challenge?", starts at 20%. Every sentence spoken at the table
   becomes a tick, is scored, and moves the price. The judge discovers they are moving
   the chart by talking. Typing is the fallback when the hall is too loud.
2. **Any market, from a link or plain words.** Paste a Kalshi or Polymarket link, or
   type a question such as "will Jensen get fired". The terminal finds the matching
   contracts and starts tracking them. If no contract matches, it creates a house
   market for the question **(call)**.
3. **Live tape.** For each tracked market: new articles, filings and changes to the
   pages that decide the market arrive as ticks, each scored up / no effect / down with
   a confidence.
4. **Instant fill.** Adding a market pulls and scores recent coverage in one burst, so
   the tape is full within seconds even if no news breaks during the demo.
5. **Weekend record.** About 20 markets log from Friday night. On Sunday we show how
   many ticks were called up or down and how often the price then moved the same way.
6. **One stream for the frontend.** Georg's teammate builds the screen in his own
   stack against a documented HTTP interface. Backend and frontend are built in
   parallel.

## Non-goals

- Placing trades or handling money.
- User accounts, logins, multiple users.
- Explaining why a tick was scored the way it was (Decision 1 cannot produce text).
- The frontend itself. This repo holds a bare debug page only.
- X posts on every market. X is wanted, but it is the one source with no confirmed
  free route, so it is limited to the headline market and built last.

## Anti-goals

- **A dead demo.** Nothing on screen may depend on news happening to break during the
  two minutes. Goals 1 and 4 exist to prevent this.
- **Passing off made-up data as real.** Made-up markets and microphone or typed ticks are
  flagged as such in the data and must never count towards the weekend record.
- **A demo that only works for Nvidia.** Nothing may be specific to one market.

## Constraints

- Hackathon weekend; submission deadline not yet confirmed. The build order below is
  arranged so that stopping after any step leaves something demoable.
- Context.dev: 50,000 credits per account, 50 concurrent requests, monitors
  no faster than every 10 minutes, news search is company-only (not free text).
- Decision 1 is two days old. Its request format has only been read from third-party
  write-ups, and its quality on "will the price move" questions is untested.
- Georg's other projects are Python with uv; this one follows suit **(call)**.

## Approaches considered

1. **One Python process, picked (call).** A single service polls sources, scores
   ticks, writes them to a SQLite file and pushes them to the browser. Fewest moving
   parts, one thing to deploy, one log to read at 3am.
2. **Separate collector, scorer and API joined by a queue.** Scales further and
   isolates failures, but adds two services and a queue to run for a weekend where one
   process handles the load easily. Rejected as unneeded.
3. **Driven by Context.dev monitors and webhooks, hosted as functions.** Leans hardest
   on the sponsor's product, but monitors fire at most every 10 minutes, which kills
   the live feel the demo depends on. Rejected; monitors are still used for the slow
   deciding pages.

Georg picked the demo (the market on us, opening into real markets, closing on the
weekend record). The build approach is the author's call.

## Design

### Shape

One FastAPI service. Background tasks poll sources per market. Every new item goes
through the same path regardless of origin:

    source -> dedupe -> score -> store -> push to stream

A microphone sentence, a typed headline, an article and a page change are all ticks
and differ only in their `kind`. This is what makes the demo opener cheap: it is the
real pipeline with a different source.

One thing runs the other way, from the price back to the web ("why did it move?").

- **A jump.** When a real market's price is 3 points or more away from where it was
  within the last 10 minutes, the terminal searches for that market at once, outside
  its polling interval, and asks Decision 1 which of the items published in the three
  hours before the move began is its most likely cause, with "none of these" as a
  choice. Each item is shown to the model with how long before the move it appeared.
- **On request.** `POST /markets/{id}/why` asks the same about the market's change over
  the last day, for any market at any time, choosing among the day's strongest items.
  It makes no search, so it answers in about a second.
- **What is stored.** The move, the item (the `cause` when Decision 1 thinks it likelier
  than "none of these", otherwise only the `closest` item), the sentence of the rules a
  cause touches, and the related contracts that moved 1.5 points or more over the same
  stretch. With a dozen items to choose from the vote is split, so a cause can carry a
  low probability: under 0.4 the summary says "possible cause", from 0.4 "likely cause".

Measured on 14 Nov: the tracked markets made about ten jumps a day, and for 10 of 11
no item on the tape explained the jump, whether the look-back was 30 minutes or three
hours. Most are thin markets moving on trades, not news, which is why a move also says
what else moved: a contract falling while its rival rises is the whole story.

### Sources

| Job | Source |
|---|---|
| Prices, rules, related contracts | Kalshi and Polymarket public APIs, directly |
| Fresh articles | Context.dev web search with a freshness filter; company news search when the market names a company |
| Article text | Context.dev scrape |
| Deciding pages (named in the market's rules) | Our own poll for the headline market; Context.dev monitors for the rest |
| Company filings | SEC's feed, directly |
| Spoken or typed ticks | Posted by the frontend |
| Reddit posts | Context.dev web search restricted to reddit.com; Reddit's own API is the upgrade if results lag |
| Trader chatter | The comment thread on the Polymarket market itself, from Polymarket's comments endpoint, as `post` ticks with the source `polymarket.com/<author>` |
| Wikipedia edits | Context.dev monitors on the watch list's Wikipedia pages (see Monitors below) |
| Moves on related contracts | Our own price samples: a jump on the other venue is a tick |
| Tech-heavy markets | Hacker News search |
| X posts | Context.dev web search restricted to x.com, plus monitors on the accounts the watch list found. Depends on X being reachable (see Not yet verified); headline market only |

Georg asked for X posts, Reddit posts and news. The rest are the author's additions
**(call)**. Every source is one small function that returns items in the same shape,
so they are added one at a time in the order above and any of them can be dropped.

**Finding what is relevant** happens in three steps:

1. **Watch list, built from the live web, not from a model's memory.** A model asked
   to name subreddits and accounts from memory will invent some and miss whatever is
   new this week. So the model only reads; the web does the finding. Endpoints below
   were checked against docs.context.dev on 13 Nov.
   - **Read the rules.** An ordinary Gemini model reads the market's title and rules
     and pulls out what is written there: the people, companies and tickers, the
     page that decides the market, and three to five search queries.
   - **Official footprint.** For each company, Context.dev brand lookup (by name or
     ticker) returns its domain and its social profiles, which gives the official X
     account. Context.dev URL mapping on that domain, with a search phrase such as
     "press releases and leadership", returns its newsroom and leadership pages.
   - **Where the story lives right now.** Context.dev web search with a freshness
     filter, run four ways: unrestricted (the domains that come back are this
     market's news outlets), restricted to reddit.com (threads, and the subreddits
     they sit in), restricted to x.com (posts and their authors, if X is indexed),
     and restricted to wikipedia.org (the article to monitor).
   - **Follow the citations.** The top articles are scraped, and links inside them
     to X posts, filings and official statements add those accounts and pages.
   - **Sources earn their place.** A source whose ticks get scored up or down stays
     and is polled more often; one that only ever produces "no effect" is dropped.
     Discovery is re-run every hour, so sources that appear as a story develops are
     picked up.

   The watch list is stored per market and returned by `GET /markets/{id}`, so the
   screen can show which sources the terminal found by itself.
2. **Wide net, every poll.** Each source is searched with the watch list. This
   deliberately over-collects.
3. **Scoring is the filter.** Every candidate is scored. Anything Decision 1 calls
   "no effect" with high confidence is stored but kept off the tape, so irrelevant
   items cost a fraction of a cent each and never reach the screen. The threshold is
   left to the builder.

**Monitors** (checked against docs.context.dev on 13 Nov). A Context.dev monitor
watches one page on a schedule and calls a signed webhook when it changes. We use
them for Wikipedia pages and for every deciding page except the headline market's.

- Detection is `exact` (any visible text change) or `semantic` with instructions,
  for example "report if the article now says he is no longer CEO; ignore citation
  and formatting edits". We use `semantic`, so trivial edits never become ticks.
- The interval is at least 10 minutes. A change can therefore reach us up to 10
  minutes late, which is accepted for these secondary signals. Wikipedia's own live
  edit stream would be seconds, and is the upgrade if this lag proves too slow.
- Each successful page check costs 1 credit: one page for the whole weekend is about
  300 credits, 20 pages about 6,000.
- The first run only sets the baseline and is not a change.
- The service exposes `POST /hooks/context/{id}` for these webhooks, one unguessable
  address per watched page, and verifies the signature with that monitor's secret
  before parsing anything.

**As built (14 Nov).** Each polled market gets one watched page, set up on its next
article pass once the service has a public address (`PUBLIC_URL`). The page is found on
the live web, not from a model's memory: the text model writes one search for "the page
most likely to change when the outcome is decided", Context.dev searches without a
freshness filter, and Decision 1 chooses among the results, with "none of these" as a
choice: no page is watched only when that choice is likelier than every page, and
such a market is looked at again six hours later. Tried on four markets, it chose CENTCOM's press-release list for the Iran
ceasefire market and the Wikipedia articles for Eurovision 2027 and the 2028 Republican
primaries. The monitor is `page` with instructions built from the market's title and
rules, every 10 minutes, with both `change.detected` and `run.completed` delivered: the
second is what gives the "last checked" time. A change becomes a tick of kind `page`,
whose headline is Context.dev's summary of what changed; it is scored like any other
tick. A change that cannot be scored is answered with 503, so Context.dev delivers it
again. Deleting a market deletes its monitor; `scripts/stop_monitors.py` deletes them all.

**Where monitors fit and where they do not** **(call)**. A monitor answers "did this
one page change?". It does not answer "what is new about this topic across the web?".

| Source | Monitor? |
|---|---|
| Deciding pages, Wikipedia | Yes, as above |
| Official pages named by the watch list (company newsroom, leadership page, government release page) | Yes. Where the page states a fact, use an `extract` monitor (10 credits per check) that fires when the fact changes, for example the name listed as CEO |
| News | No. Search returns each article as a separate item with a date; a monitor on a results page only says something changed, up to 10 minutes late |
| Reddit | Fallback only, on a subreddit's "new" page, if Reddit's API cannot be reached |
| X | Worth testing: if Context.dev can fetch X pages at all, a monitor on three to five key accounts per market is the cheapest route to X |
| Prices, Polymarket comments | No. These have APIs |

The headline market is never monitor-only: it keeps our own fast polling, because the
demo cannot wait 10 minutes.

**Credit budget.** The team has several Context.dev accounts with 50,000 credits each
(Georg; the count is not yet stated, and pooling them should be cleared with the
Context.dev mentors, since they are also the judges). Each job uses one account's
key, so no key-rotation code is needed **(call)**: one account for search and scrape,
one for monitors, one held back for demo day. Before the weekend log starts, measure
what one search and one scrape cost and set polling intervals so no account runs dry
before Sunday. The headline market polls fastest (target every 30 to 60 seconds).

### Existing venue code to reuse

Georg has working clients for both venues' public, no-login endpoints in other
projects on this machine. Copy the pieces below into this repo; do not import across
repos and do not change the originals.

| Need | Copy from |
|---|---|
| Kalshi: paced GET with retries, paging | `~/scorer-mm/scorer_mm/kalshi.py` (43 lines, whole file) |
| Kalshi: price history (candles) | `candles`, `parse_candles` in `~/football-model/football_model/kalshi.py` |
| Polymarket: GET with retries, the three API hosts | `get` and the host constants in `~/weather-mm/weather_mm/pm.py` |
| Polymarket: price history down to 1 minute | `fetch_prices`, `changes` in `~/football-model/football_model/polymarket.py` |

These are plain blocking functions on the standard library. Call them from the
service in a worker thread instead of rewriting them **(call)**. The larger adapters
in `~/trading-bot-dev` are built around sports bookmakers and are not worth adapting.

Not covered by any of them, so still to write: looking a market up from a pasted
link, searching markets by plain words, and reading a market's rules text.

### Scoring

One function, `score(market, tick) -> (up, none, down, strength)`. It asks Decision 1
one graded question: given this market's title and rules and this new item, how much
does the item move the YES price? The answer has five levels: down a lot, down a
little, no effect, up a little, up a lot. Decision 1 returns a probability for each
level and an expected level.

Graded scoring replaced a plain up / no effect / down question after the first-hour
test (Georg agreed, 13 Nov). The plain question was right on 12 of 12 test headlines
but more than 87% confident on every one, so it could not tell a resignation from an
analyst's remark. The graded question separates them.

- `down` is the probability of the two down levels, `none` of the middle level, `up`
  of the two up levels. `strength` is the expected level rescaled to -1 to 1.
- `verdict` is the largest of the three; `confidence` is its probability.
- If Decision 1 turns out unusable (see First hour), the same function calls an
  ordinary Gemini model with structured output. Nothing else changes.
- Decision 1 is also used to match plain-words input to contracts (see Plain words
  to a market).

### Plain words to a market

Two models are involved, each doing the one thing it is good at: an ordinary Gemini
model writes, Decision 1 chooses. The steps for "will jensen get fired":

1. **Expand.** The ordinary model turns the words into search terms, including names
   the user did not type: Jensen Huang, Nvidia, CEO, resign, step down, out. Needed
   because the matching contract may be titled "Nvidia CEO out before 2027?" and
   share no word with the input.
2. **Find candidates.** The terms are matched against a local index of every open
   contract title on both venues, kept in the same SQLite file with its built-in text
   search and refreshed hourly from the venues' listing endpoints **(call)**. A local
   index is used because Kalshi has no known plain-word search and the judge's
   question must not depend on one. Up to 50 candidates come back.
3. **Choose.** Decision 1 is given the user's words and the candidate titles as
   options, plus "none of these". The most probable candidate becomes the lead
   market if it beats "none of these"; other candidates on the same event become its
   related contracts.
4. **Or make one up.** If "none of these" wins, the ordinary model rewrites the words
   into a proper yes/no question with a deadline, 30 days out unless the words name
   a date **(call)**, for example "Will Jensen Huang stop being Nvidia's CEO before
   13 December 2026?". That becomes a made-up market.
5. **Then the same as any market.** Source discovery, instant fill, and for a made-up
   market the starting odds.

The whole thing takes a few seconds, so each step is announced on the stream as a
`market` event with a status ("searching venues", "found 3 contracts", "finding
sources"). The wait is then something the judge watches happen, not a spinner.

Shortcut to try in the first hour: Context.dev web search restricted to
polymarket.com and kalshi.com with the user's raw words. If that reliably returns
the right market pages, it replaces steps 1 and 2 and the index is not built.

### Made-up market price

A made-up market's price moves only when a tick is scored **(call)**:

    logit(p_new) = logit(p_old) + k * strength

with `k` tuned so one strongly scored sentence moves the price by a visible few
percentage points and the price never leaves 1% to 99%. A made-up market created from a plain-words
question with no matching contract gets its starting price from the news (Georg's
idea): the instant-fill coverage is given to Decision 1 together with the question,
and its probability for "yes" is the starting price. The demo market has no news to
read, so it starts at a fixed 20%.

### Storage

One SQLite file with five tables: markets (related contracts are rows pointing at
their lead market), ticks, prices, moves, watched pages. Every market and related contract has its price
sampled at least once a minute from the venue APIs, which cost no Context.dev credits.

The weekend record is a query, not stored state, so its rule can still change on
Sunday. What cannot be recovered later is logged from the start: both timestamps on
every tick, the backfill flag, and the minute-level prices. The starting rule
**(call)**:

- Eligible ticks: verdict up or down, on a real market, not a test, not backfilled.
- The clock starts when we detected the tick, not when the article was published,
  because that is when a trader could have acted.
- Compare the price at detection with the price 15 minutes later. If it moved less
  than 1 percentage point the tick is left out, and the record reports three numbers: ticks
  called, ticks where the price then moved, and ticks where it moved the same way.

### Interface for the frontend

JSON over HTTP, open CORS. Reads need nothing; the two `POST` routes need the header
`X-Terminal-Key: <the shared key>` (401 without it).

- `GET /markets`: all tracked markets with latest price, 24-hour change, ticks today.
  Each market, here and wherever a market appears, has `consensus`: null, or when the
  same question trades on the other venue and both have a price, `{ "price", "gap",
  "venues": [{ "id", "venue", "price", "url" }, ...] }`: the middle of the two prices,
  how far apart they are, and the two contracts, this market first. Each one's later
  prices arrive as `price` events under its `id`.
- `POST /markets` `{ "query": "<link or plain words>", "poll_seconds": 900 }`: returns
  the lead market now being tracked (the same shape as `GET /markets/{id}`) plus
  `"matched"`: true when it is a Kalshi or Polymarket contract, false when no market
  asks this and one was made up. Takes a few seconds for plain words. Triggers the
  instant fill. A new made-up market has `"price": null` until its starting odds
  arrive as a `price` event, usually within a minute. Related contracts can include
  the same question on the other venue. Errors carry a readable `detail`: 422 (not a
  question), 404 (closed or missing link), 502 or 503 (try again).
- `GET /markets/{id}`: detail, including related contracts, `pages`: the page
  Context.dev watches for this market, as `[{ "url", "title", "checked_ts",
  "changed_ts" }]` (empty until one is found; the two times are null until the first
  check and the first change), and `sources`: where the market's ticks came
  from, most ticks first, as `[{ "source", "ticks", "moved" }]` (`moved` counts the
  ticks called up or down).
- `POST /markets/mu-demo/reset` (needs the key): puts the demo market back to its
  starting price with an empty tape, for use after a rehearsal. Sends a `market` event
  with status `reset` and a `price` event. 409 for any other market.
- `DELETE /markets/{id}`: stop tracking a market; it, its related contracts, their
  ticks and prices are removed. 409 for the demo market. Sends a `market` event with
  status `deleted`. A market its venue has resolved is dropped the same way without
  being asked: every ten minutes each venue is asked which tracked contracts have an
  outcome (Kalshi: determined or finalized; Polymarket: closed), and the event then
  also carries `"resolved": true`. Its calls leave the weekend record with it.
- `GET /markets/{id}/ticks?limit=` and `GET /markets/{id}/prices?since=`: history for
  first paint.
- `GET /markets/{id}/moves?limit=`: the market's price moves, newest first (see "A
  move" below).
- `POST /markets/{id}/why` (needs the key): why did this market move over the last
  day? Answers in about a second with a move that has `asked:
  true`, which is also sent as a `move` event. Asked again within five minutes it
  returns the same answer. 409 when the price moved less than a point.
- `POST /markets/{id}/pair` (needs the key): looks for the same question on the other
  venue and, when Decision 1 is at least 50% sure a contract there resolves in exactly
  the same cases, pairs the two; the answer is the market's detail, with `consensus`
  set when a pair was found. A market is paired this way when it is first tracked, from
  plain words or from a link (a link takes a few seconds longer for it); this route
  looks again, for a market whose other venue was not listed yet or could not be
  searched. 409 for a made-up market.
- `POST /markets/{id}/ticks` `{ "text": "...", "kind": "mic" | "typed" }`: a spoken or
  typed tick. Always stored with `test: true`.
- `GET /record`: the weekend record numbers.
- `GET /status`: Context.dev capacity per key (use, resting time, credits left).
- `GET /stream`: server-sent events. Event types: `tick`, `tick_update`, `price`,
  `move`, `market`, `page_check`. A `page_check` is `{ "market_id", "url", "ts",
  "changed" }`, sent each time Context.dev has checked a watched page (every 10
  minutes); when `changed` is true a `tick` of kind `page` follows. A `move` event is a move as below, sent once, some
  seconds after the price sample that showed it (the web is searched first). A `tick_update` is a whole tick again, sent when its
  `published_ts` arrives about a minute or two after the tick: replace the tick with
  the same `id`. One connection carries all markets; each event has a `market_id`.
  A `market` event is `{ "market_id", "status" }`. While plain words are being worked
  on it also carries `"query"` and `market_id` is null: `searching venues`, then
  `found contracts` (with `count` and `contracts`: up to six markets found, each
  `{ "venue", "title", "price", "contracts" }`), then, when one matches, `picked` (with
  `winner`, its place in `contracts`, and the leading contract's `venue`, `title` and
  `price`), then `tracking` or `made up` with the id, or `failed`. Afterwards the market
  reports `finding sources` (with `queries`, the phrases the web is searched with),
  `scoring` (with `found`, how many items the searches returned), a `tick` for each
  scored item worth showing as it is scored, and `ready` (with `ticks`, how many items
  were stored).

A tick:

    { "id", "market_id", "ts", "published_ts",
      "kind": "article|post|filing|page|mic|typed",
      "source", "url", "headline",
      "up", "none", "down", "strength", "verdict": "up|none|down", "confidence",
      "price_at", "test": false, "backfill": false,
      "likes": 2126, "replies": 113,
      "rule": { "start": 412, "end": 598, "text": "If it becomes impossible ...", "confidence": 0.89 },
      "passage": "On Thursday, the board announced that ..." }

`ts` is when we detected the tick and `price_at` is the price at that moment,
as a percentage from 0 to 100, like every other price in the interface.
A `post` is from X, Reddit or Truth Social; its `source` names who posted, as `x.com/<handle>`,
`reddit.com/r/<subreddit>` or `truthsocial.com/@realDonaldTrump`, and its `headline` is the post's text.
Trump's posts come from the team's own scraper (`trump-social-scraper/`) within about 20 seconds of
being made, and are scored for every market whose search queries share a word with the post.
`passage` is, for an article found by the web search, the excerpt of its page that Context.dev found
relevant to the query (one line, up to about 320 characters), to show beside the tick as its evidence;
null for posts, for articles from the news index or Google News (which bring no page text), and for
spoken, typed and page ticks. It plays no part in scoring.
`rule` is the sentence of the market's rules that makes this tick matter, chosen by Decision 1 from
the sentences of the rules text: `start` and `end` are character positions in the market's `rules`
(from `GET /markets/{id}`), so it can be highlighted in place, and `text` is that exact stretch. It is
set only on ticks that call a move (verdict up or down) and is null on every "no effect" tick. For a
spoken or typed tick it is the closest sentence, however weak; for a tick from the web it is null
when no sentence stands out.
`likes` and `replies` are the post's counts on X when it was found, and null for everything else
(Reddit gives no vote counts without a login). Replies, posts that are only a link, posts on X past
their first hour with under 20 likes, and Reddit's recurring threads and removed posts are never shown.
`published_ts` is when the item was published, where known: show this as the tick's
time and fall back to `ts`. X posts have it at once, and so do Reddit posts read from a
subreddit's feed; news articles get it at once or within a couple of minutes; Reddit posts found
by search and pages that state no time never do. Instant-fill ticks carry
`backfill: true` and are drawn on the chart at `published_ts`.

A move:

    { "id", "market_id", "ts", "since", "from": 23.5, "to": 20.0,
      "summary": "Down 3.5 points in 1 minute. No news explains it. Will Rene Haas be the next CEO of NVIDIA? went up 4.0 at the same time.",
      "explained": false, "asked": false,
      "cause": { ...a tick... } | null, "closest": { ...a tick... } | null, "confidence": 0.65 | null,
      "rule": { "start", "end", "text", "confidence" } | null,
      "related": [ { "id", "title", "from": 20.0, "to": 24.0 } ] }

The price went from `from` at `since` to `to` at `ts`. `summary` says it in plain words
and is enough to show by itself. `explained` tells whether an item is taken as the reason:
if so it is in `cause` (a whole tick, also on the tape) and `rule` is the sentence of the
rules it touches; if not, `cause` is null and `closest` holds the nearest item, to be
shown as "closest news", never as the reason. `confidence` is Decision 1's probability
for whichever of the two is set. `related` lists the related contracts whose price
changed 1.5 points or more over the same stretch, biggest change first. `asked` is true
for a move explained on request (the last day), false for a jump the terminal saw itself.
Made-up markets have no jumps of their own, but can be asked about.

The frontend owns speech-to-text (microphone to sentences), the spoken call-out of
each verdict, and all layout. The concept mockup is at
https://claude.ai/artifact/Rx3hfxQFtQ1tNFfjSwvvKm (sample data, concept only).

### Hosting

One Railway service with a volume for the SQLite file **(call)**, so the teammate and
the demo laptop get a stable public address that does not depend on Georg's home
connection.

### Demo script (about two minutes)

1. The market on us. Judge talks, price moves, voice calls each verdict.
2. "Now swap the microphone for the whole live web": the Nvidia CEO-exit market, with
   the ticks we flagged against its real price chart.
3. Judge asks any question in plain words; contracts appear and the tape fills.
4. The weekend record.

## Build order

Each step is demoable on its own. Stop wherever time runs out.

1. **First hour: Decision 1 test.** Throwaway script. Score a dozen real headlines
   against one real market and look at the answers. Decides Decision 1 versus the
   fallback. Also measure Context.dev credit costs here.
2. Tick pipeline with typed ticks, a made-up market, the stream and the debug page.
   This alone is the demo opener, and it unblocks the teammate.
3. Add a market by link; prices from the venue; articles as ticks; instant fill.
4. Deploy, add about 20 markets, start the weekend log.
5. Plain-words input and made-up markets for unmatched questions.
6. Deciding pages and filings, then the extra sources in the order of the Sources
   table (Reddit first, X last).
7. Related contracts across venues; the record endpoint.

## Left to the builder

- Library choices beyond FastAPI, httpx and the standard-library sqlite3.
- Polling intervals, within the credit budget.
- The value of `k`, and sentence splitting for long typed text.
- Dedupe rule. Start with URL plus normalised headline; the same story from several
  outlets may still arrive as several ticks, which is acceptable for the weekend.
- Which ordinary Gemini model writes search queries and serves as the fallback scorer.
- One automated test proving a tick flows from a fake source through a fake scorer to
  the store and the stream, and one for the house price rule.

## Not yet verified

- Decision 1's official request format and its quality on this task.
- Listing every open contract on Kalshi and Polymarket for the local index (how many
  there are, how long a full listing takes), and looking one up from a pasted link. (Public access and price history are already proven by Georg's
  existing clients.)
- Context.dev credit cost per call, and how far back its freshness filter reaches.
- Junction's judging format and submission deadline.
- A route to X posts: whether Context.dev's scrape handles X (ask the mentors), and
  failing that, what a paid third-party scraper costs.
- The Polymarket comments endpoint, believed to be free and not yet called.
- What Context.dev's web search returns when restricted to reddit.com and x.com: how
  fresh the results are, whether X posts are indexed at all, and whether each result
  carries a published date. This decides how much of the discovery works as written.
- Whether Context.dev's fetcher can read Wikipedia pages, and how well its semantic
  detection ignores trivial edits.
