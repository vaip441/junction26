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
| Find | News through Context.dev web search, every query of a market on every pass, for markets about a company through Context.dev's news index, and through Google News feeds; both are minutes behind the publishers. One story is one tick, whichever outlet or search it came from. Posts on X and Reddit through the same search, plus the newest posts of subreddits that were relevant before. Trump's Truth Social posts within about 30 seconds, from the scraper in `trump-social-scraper/`. | `terminal/poller.py`, `terminal/posts.py`, `terminal/truth.py` |
| Filter | An item is looked at once per market. Replies, link-only posts, posts nobody liked, recurring Reddit threads and removed posts are kept off the tape without a model call. | `terminal/posts.py` |
| Score | Gemini Decision 1 is told the market, its rules, the current price, the rival contracts and what was already reported, then asked how far the new item should move the price and whether it is news at all. For a tick that moves the price it also picks the sentence of the rules that makes the item matter. | `terminal/scoring.py`, `terminal/pipeline.py`, `terminal/rules.py` |
| Store and stream | SQLite, and one server-sent-events stream for the frontend. | `terminal/db.py`, `terminal/api.py` |

It also works backwards, from the price to the web: when a real market's price jumps 3 points within
10 minutes, the terminal searches for that market at once and Decision 1 names the item most likely
behind the jump, with the sentence of the rules it touches (`terminal/moves.py`).

A question in plain words is matched to a real market by searching both venues and letting Decision 1 pick
(`terminal/match.py`). When nothing matches, a text model writes a yes/no question with a deadline, Decision 1
gives its starting odds from the coverage found, and each shown tick afterwards nudges the price
(`terminal/madeup.py`, `terminal/pricing.py`).

Prices are percentages from 0 to 100 and times are unix seconds, everywhere.

## Run it

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```sh
cp .env.example .env          # fill in the keys; see the comments in the file
uv run --env-file .env uvicorn terminal.api:app --port 18911
uv run --env-file .env python scripts/seed_markets.py http://127.0.0.1:18911   # tracks the markets in markets.txt
```

Open http://127.0.0.1:18911/ for a plain debug page: ask a question, pick a market, type a sentence and
watch it become a tick. The real screen is a separate frontend that talks to the interface below.

| Variable | Meaning |
| --- | --- |
| `GEMINI_API_KEY` | Google AI key with access to `gemini-decision-1` and the text model |
| `CONTEXT_DEV_API_KEY` | one Context.dev key, or several separated by commas; each adds 10 requests a minute |
| `TERMINAL_KEY` | shared secret that every write must send in an `X-Terminal-Key` header |
| `DB_PATH` | the SQLite file |
| `GEMINI_TEXT_MODEL` | the model that writes search queries and made-up questions |
| `TRUTH_FEED` | optional: the file `trump-social-scraper` appends new posts to |

## Interface

Reads are open; writes need the `X-Terminal-Key` header. The full description, with the shape of a tick
and of every stream event, is in
[the design document](docs/superpowers/specs/2026-11-13-terminal-design.md#interface-for-the-frontend).

| Request | What it does |
| --- | --- |
| `GET /markets`, `GET /markets/{id}` | tracked markets with price, 24-hour change and ticks today; one market with its related contracts and sources |
| `POST /markets` | track a market from a link or from plain words |
| `DELETE /markets/{id}` | stop tracking a market |
| `GET /markets/{id}/ticks`, `GET /markets/{id}/prices` | history for the tape and the chart |
| `GET /markets/{id}/moves` | "why did it move?": the market's price jumps, each with its likely cause |
| `POST /markets/{id}/ticks` | a spoken or typed sentence, scored like any other tick |
| `GET /stream` | server-sent events: `tick`, `tick_update`, `price`, `move`, `market` |
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

The unit files hold absolute paths for the machine they were written on; change them for another one.

## Tests

```sh
uv run pytest                                                     # the terminal; no network needed
(cd trump-social-scraper && python -m unittest test_trump_scraper)  # the scraper
```
