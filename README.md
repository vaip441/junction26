# Prediction market terminal

A terminal for tracking how news and other signals move prediction market prices and the likelihood of events.
Built at Junction 2026 for the Context.dev challenge: a product that reacts to the live web.

Ask a question in plain words, or paste a Kalshi or Polymarket link. The terminal finds the market that
asks the same thing, watches the web for it, and puts every new article and post on a tape with a verdict:
does this move the price of YES up, down, or not at all. If no market exists for the question, it makes
one up and sets the odds itself.

It reads public data only and places no trades.

## How it works

Every item takes the same path: found, deduplicated, scored, stored, streamed to the frontend.

| Step | What happens | Where |
| --- | --- | --- |
| Find | News through Context.dev web search, every query of a market on every pass, for markets about a company through Context.dev's news index, and through Google News feeds (the last two hours only); both are minutes behind the publishers. One story is one tick, whichever outlet or search it came from. Posts on X and Reddit through the same search, plus the newest posts of subreddits that were relevant before. The newest comments under the market on Polymarket (its own, or the same question's there), as posts. Trump's Truth Social posts within about 30 seconds, from the scraper in `trump-social-scraper/`. | `terminal/poller.py`, `terminal/posts.py`, `terminal/truth.py` |
| Filter | An item is looked at once per market. Replies, link-only posts, posts nobody liked, recurring Reddit threads and removed posts are kept off the tape without a model call; so are Polymarket comments that are replies, reported, under eight words or adverts. | `terminal/posts.py` |
| Score | Gemini Decision 1 is told the market, its rules, the current price, the rival contracts and what was already reported, then asked how far the new item should move the price and whether it is news at all. For a tick that moves the price it also picks the sentence of the rules that makes the item matter. | `terminal/scoring.py`, `terminal/pipeline.py`, `terminal/rules.py` |
| Store and stream | SQLite, and one server-sent-events stream for the frontend. | `terminal/db.py`, `terminal/api.py` |

It also works backwards, from the price to the web: when a real market's price jumps 3 points within
10 minutes, the terminal searches for that market at once and Decision 1 names the item most likely
behind the jump, with the sentence of the rules it touches, or says that no news explains it and which
related contracts moved at the same time. The same can be asked of any market's last day on request
(`terminal/moves.py`).

Each market also has one page watched for it by a Context.dev monitor: the page most likely to change
when the outcome is decided (a newsroom, a results page, a Wikipedia article), found by search and chosen
by Decision 1. Context.dev checks it every ten minutes and calls a signed webhook; a change that bears on
the market becomes a tick (`terminal/pages.py`). This needs an address the internet can reach (`PUBLIC_URL`).

A question in plain words is matched to a real market by searching both venues and letting Decision 1 pick
(`terminal/match.py`). When the other venue lists a contract that resolves the same way (the same person,
threshold and deadline, as Decision 1 judges it), the two are paired and the market carries a `consensus`:
both venues' prices, their middle and how far apart they are. When nothing matches, a text model writes a yes/no question with a deadline, Decision 1
gives its starting odds from the coverage found, and each shown tick afterwards nudges the price
(`terminal/madeup.py`, `terminal/pricing.py`).

A market tracked just now starts with the venue's last week of prices, about one an hour
(`terminal/venues/`), so its chart is not empty and the news found for it has a price to stand on.
From then on the terminal samples the price itself.

Prices are percentages from 0 to 100 and times are unix seconds, everywhere.

## Run it

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```sh
cp .env.example .env          # fill in the keys; see the comments in the file
uv run --env-file .env uvicorn terminal.api:app --port 18911
uv run --env-file .env python scripts/seed_markets.py http://127.0.0.1:18911   # tracks the markets in markets.txt
```

The real screen is the React app in `ui/`. Built once, the terminal serves it at http://127.0.0.1:18911/
(build it again after every change to `ui/`, then restart the terminal):

```sh
(cd ui && npm ci && VITE_API_URL= npm run build)   # an empty VITE_API_URL: the screen talks to the address it came from
```

http://127.0.0.1:18911/debug is a plain debug page: ask a question, pick a market, type a sentence and
watch it become a tick. It is also what `/` shows until the screen is built.

| Variable | Meaning |
| --- | --- |
| `GEMINI_API_KEY` | Google AI key with access to `gemini-decision-1` and the text model |
| `CONTEXT_DEV_API_KEY` | one Context.dev key, or several separated by commas; each adds 10 requests a minute |
| `TERMINAL_KEY` | shared secret that every write must send in an `X-Terminal-Key` header |
| `DB_PATH` | the SQLite file |
| `GEMINI_TEXT_MODEL` | the model that writes search queries and made-up questions |
| `TRUTH_FEED` | optional: the file `trump-social-scraper` appends new posts to |
| `PUBLIC_URL` | optional: the address the internet reaches this service at; turns on page watching, since Context.dev calls back `PUBLIC_URL/hooks/context/...` |

## Interface

Reads are open; writes need the `X-Terminal-Key` header. The full description, with the shape of a tick
and of every stream event, is in
[the design document](docs/superpowers/specs/2026-11-13-terminal-design.md#interface-for-the-frontend).

| Request | What it does |
| --- | --- |
| `GET /markets`, `GET /markets/{id}` | tracked markets with price, 24-hour change and ticks today; one market with its related contracts, sources and watched page |
| `POST /markets` | track a market from a link or from plain words |
| `DELETE /markets/{id}` | stop tracking a market |
| `POST /markets/mu-demo/reset` | put the demo market back to its starting price with an empty tape |
| `GET /markets/{id}/ticks`, `GET /markets/{id}/prices` | history for the tape and the chart |
| `GET /markets/{id}/moves` | "why did it move?": the market's price moves, each in one sentence with its likely cause |
| `POST /markets/{id}/why` | explain the market's move over the last day, now |
| `POST /markets/{id}/pair` | look for the same question on the other venue; found, the two prices are shown as one `consensus` |
| `POST /markets/{id}/ticks` | a spoken or typed sentence, scored like any other tick |
| `GET /stream` | server-sent events: `tick`, `tick_update`, `price`, `move`, `market`, `page_check` |
| `GET /record` | of the ticks called up or down, how often the price then moved that way |
| `GET /status` | Context.dev use and credits per key |

## Deploy

Two systemd user services, in `deploy/`: `terminal.service` runs the terminal, and `trump-scraper.service`
runs the Truth Social scraper, which needs the one-time setup in
[its own README](trump-social-scraper/README.md).

```sh
ln -s "$PWD"/deploy/*.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now terminal trump-scraper
```

Watched pages cost one Context.dev credit per page every ten minutes for as long as their monitors exist,
whether or not the terminal is running. To stop them all:

```sh
PYTHONPATH=. uv run --env-file .env python scripts/stop_monitors.py data/terminal.db
```

The unit files hold absolute paths for the machine they were written on; change them for another one.

## Tests

```sh
uv run pytest                                                     # the terminal; no network needed
(cd trump-social-scraper && python -m unittest test_trump_scraper)  # the scraper
```
