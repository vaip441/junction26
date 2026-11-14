---
name: add-source
description: Add a new kind of item to the tape (a new site, feed, API or file the terminal should read for its markets), or change how an existing source is fetched or filtered. Use when asked to bring in filings, a new social network, an RSS feed, a venue's own data, or any other live signal.
---

# A new source on the tape

Every item takes one path: found, filtered, scored, stored, streamed. A new source only adds a way of
finding. Everything after that is `pipeline.ingest`, which already dedupes, scores, picks the rules
sentence, stores the tick and puts it on the stream.

## Before writing code

1. **Try the source by hand** and write down what you measured: how fresh it is, whether items carry a
   published time, how many requests a pass costs. The repo records these next to the code ("measured on
   14 Nov, a market's four queries returned 25 to 28 different results"); do the same.
2. **Count the cost.** If it goes through Context.dev, read the `context-dev` skill first.
3. **Decide which shape it is:**

| Shape | Example in the repo | Where it plugs in |
| --- | --- | --- |
| Asked per market, on every pass | web search, Google News, subreddit feeds, Polymarket comments | a new fetcher parameter of `poller.fetch_articles` |
| Pushed or tailed, then matched to markets | Truth Social posts (`terminal/truth.py`) | its own loop, started in `api.py`'s `lifespan` behind an environment variable |
| Called back by someone else | watched pages (`terminal/pages.py`) | a route under `/hooks/` that verifies a signature |

## Writing it

- **One module** in `terminal/` with a pure parser (`parse(...) -> list[dict]`) and a thin fetcher beside
  it. The parser is what the tests cover.
- **Hand each item to `pipeline.ingest`** with `kind`, `source`, `headline`, and `url`, `body`,
  `published_ts`, `likes`, `replies` where known. `kind` is one of `article`, `post`, `filing`, `page`.
  A new kind must also be added to `TickKind` in `ui/src/lib/types.ts`, to the label map in
  `ui/src/components/tape/TickRow.tsx`, and to the spec.
- **`source` is what the screen shows and groups by**: a domain, `x.com/handle`, `reddit.com/r/sub`.
  For a logo and a short name, see `ui/src/lib/sources.ts`.
- **Filter before scoring.** Every item scored is a model call. Throw out what can be thrown out without
  one (replies, link-only posts, adverts, recurring threads): see the `*_trash` functions in
  `terminal/posts.py`.
- **Old items are history, not news.** Pass `backfill=True` for anything found on a market's first pass or
  delivered late, so it is dimmed on the tape and never counts in the record.
- **Take the fetcher as a parameter** (`fetch=None`, defaulting to the real one inside the function), so a
  test passes a stand-in. Add the real one to `tests/conftest.py`'s autouse fixture so a test that forgets
  fails loudly instead of reaching the network.
- **Background fetching leaves room for a person.** Routine passes call Context.dev with
  `reserve=BACKGROUND_RESERVE`, so someone typing a question is not queued behind them.
- **Nothing market-specific**: no company name, market id or handle in the code. A source tied to one
  subject (one person's posts) is matched to markets by their search queries (`posts.shares_words`).

## Tests

Follow `tests/test_truth.py` or `tests/test_googlenews.py`: a fixture of the raw response, the parser's
output asserted, then one test that an item goes through `ingest` with a fake scorer and ends up stored
and on the bus (`tests/test_pipeline.py` has the `setup`, `run` and `drain` helpers). Also test the
filters with the cases you threw out by hand.

## Finishing

Update the "Find" row of the table in `README.md` and the Sources section of the spec, run `check-all`,
and say in the report what was measured and what was not tried against the real source.
