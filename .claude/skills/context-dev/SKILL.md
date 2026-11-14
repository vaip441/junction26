---
name: context-dev
description: How this repo uses Context.dev (web search, news search, scrape, page monitors), what each call costs and how it is rate-limited. Use before adding or changing any Context.dev call, when a search returns too little or too late, when credits or rate limits are in question, or to try a query by hand before writing code.
---

# Context.dev in this repo

The challenge is "a product that reacts to the live web", and Context.dev is how the terminal reaches it.
Every call goes through `terminal/contextdev.py`. Nothing else in the repo talks to the API.

## What is used, and what it costs

| Call | Function | Used for | Cost |
| --- | --- | --- | --- |
| `POST /web/search` | `contextdev.search` | every query of every market on every pass; the venues' pages for a question in plain words; X and Reddit by restricting domains | 2 credits |
| `POST /news/search` | `contextdev.news` | markets that name a company: its newest articles | 3 credits |
| `POST /web/scrape` | `contextdev.scrape` | the text and publish time of a page | not written down in the repo: measure it |
| `POST /monitors` | `contextdev.create_monitor` | one watched page per market, checked every 10 minutes, calling `/hooks/context/...` | 1 credit per check, for as long as the monitor exists |

The costs are the ones recorded in the code's own docstrings. If you measure a different one, fix the docstring.

What was measured, and where it is written down:

- The news index is minutes behind the publishers but knows companies only; for people, countries and public
  bodies it was weeks behind (`contextdev.news`).
- The web search returns pages from anywhere in the last day (`freshness="last_24_hours"`), so it is hours
  behind where the news index is minutes.
- A market's four queries returned 25 to 28 different results between them, which is why every query runs on
  every pass (`poller.fetch_articles`).
- Search restricted to `polymarket.com` and `kalshi.com` found the right market page in the top three for six
  of six questions that had a market (`docs/superpowers/plans/2026-11-13-terminal-plain-words.md`).

## Limits the code already respects

- **10 requests a minute per key** (`CONTEXT_DEV_RPM`). `CONTEXT_DEV_API_KEY` may hold several keys separated
  by commas; `Limiter` spreads requests evenly and rests a key the server refuses (30 s or `Retry-After` for
  a 429; ten minutes for 401, 402 or 403).
- **A person comes first.** Background passes call with `reserve=BACKGROUND_RESERVE` (2 a minute per key left
  free), so a question typed on stage is not queued behind routine fetching. A scrape is skipped rather than
  queued when capacity is short.
- **A question gives up after 10 seconds** of waiting on search (`match.SEARCH_SECONDS`) and says so.
- **Monitors belong to the key that made them** and bill whether or not the terminal runs. They exist only
  when `PUBLIC_URL` is set. `scripts/stop_monitors.py` deletes them all; stop the terminal first.

## Seeing what is being spent

`GET /status` on a running terminal: per key (numbered, never shown), requests in the last minute, seconds a
refused key is resting, and credits left as last reported by the server.

```sh
curl -s http://127.0.0.1:18911/status
```

## Trying a call before writing code

If the Context.dev MCP server is connected in this session, use its tools to see what a query really returns
before designing around it: the web search, news search and scrape tools for results, the usage tool for
credits. Otherwise call the functions from a scratch script with the keys in `.env`:

```sh
uv run --env-file .env python -c "
import asyncio
from terminal import contextdev
print(asyncio.run(contextdev.search('nvidia ceo succession', num_results=5)))"
```

Either way it spends real credits on a real account. Try one query, not a loop; write down what came back
(how many results, how fresh, whether they carry a date) next to the code that depends on it.

## Adding a call

1. Add it to `contextdev.py` beside the others: a pure `parse_*` function and a thin `async` wrapper over
   `_call`. State the cost in the docstring.
2. Choose `wait=True` (queue for capacity) or `wait=False` (skip when there is none), and a `reserve` if it
   runs in the background.
3. Work out the bill before merging: calls per pass, times markets, times passes an hour. The deployment
   tracks about a dozen markets, most on a 15-minute pass (`markets.txt`).
4. Tests use a recorded response under `tests/fixtures/` and never the API (`tests/test_contextdev.py`).

## Not known

The spec's "Not yet verified" list still stands where the code does not say otherwise: how far back the
freshness filter reaches, how well monitors ignore trivial edits, whether scrape reads X. Say "not verified"
rather than guessing, and prefer a one-call measurement to an assumption.
