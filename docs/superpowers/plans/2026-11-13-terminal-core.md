# Terminal Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running service that scores ticks with Gemini Decision 1, drives the "market on us" demo opener, tracks real Kalshi and Polymarket markets from a pasted link with live articles, and logs everything the weekend record needs.

**Architecture:** One FastAPI process. Every item, whatever its origin, goes through `pipeline.ingest`: dedupe, score, store in SQLite, publish on an in-process bus that feeds one server-sent-events stream. Background loops sample prices and search for articles.

**Tech Stack:** Python 3.12+, uv, FastAPI, uvicorn, httpx, google-genai, standard-library sqlite3, pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-terminal-design.md`

**Scope:** This is plan 1 of 2. It covers the spec's build-order steps 1 to 4 plus the record endpoint. Plan 2 (plain-words input, source discovery, monitors and webhooks, Reddit, X, Polymarket comments, cross-venue contracts) is written after Task 1, because its design depends on what Task 1 finds.

## Global Constraints

- Python with uv. One process. SQLite through the standard-library `sqlite3`.
- Every price in the database and the API is a percentage from 0 to 100 (a venue price of 0.82 is `82.0`). Changes are percentage points.
- Every timestamp in the database and the API is unix seconds as a number.
- Ticks of kind `mic` or `typed` are stored with `test = 1`. Test ticks, backfilled ticks and ticks on made-up markets never count in the record.
- Nothing may be specific to one market: no market id, title or company name in code outside `terminal/seed.py` and tests.
- Venue client code is copied into this repo. Never import from, or modify, `~/scorer-mm`, `~/weather-mm`, `~/football-model`, `~/trading-bot-dev`.
- Secrets live in `.env`, which is git-ignored. Variables: `GEMINI_API_KEY`, `CONTEXT_DEV_API_KEY`, `DB_PATH` (default `terminal.db`), `SCORER` (`decision1` or `fallback`), `GEMINI_TEXT_MODEL`.
- The API has open CORS and no auth.
- Work on branch `terminal-core`. Commit after each task.

## Review Focus

Conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **The scorer fails or times out mid-demo.** Expected: the tick is not stored (so it is retried, not swallowed by dedupe), the service keeps running, and a typed or spoken tick gets a 503 with a readable message. Task 4 and Task 5.
2. **A venue has no usable price** (no bids, closed market). Expected: the sample is skipped, the loop continues, and ticks carry `price_at: null`. Task 6.
3. **The same article arrives under several addresses** (`?utm_source=`, trailing slash, `#fragment`, upper-case host). Expected: one tick. Task 4.
4. **A stream client stalls or reconnects** (the frontend reloads all weekend). Expected: publishing never blocks or raises, and a full subscriber queue is dropped. Task 4.
5. **The service restarts** (every deploy). Expected: no data lost, exactly one demo market, loops resume. Task 5.

## File Structure

```
pyproject.toml, .gitignore, .env.example
terminal/
  db.py            schema and every query
  scoring.py       Score type, verdict rule, hide rule, the real scorers
  pricing.py       made-up market price rule
  bus.py           in-process publish/subscribe for the stream
  pipeline.py      ingest(): dedupe -> score -> store -> publish
  api.py           FastAPI app, routes, stream, startup
  record.py        weekend record query
  contextdev.py    Context.dev search
  watch.py         search queries from a market's title and rules
  poller.py        price loop, article loop, instant fill
  seed.py          the demo market's fixed text
  venues/__init__.py, venues/kalshi.py, venues/polymarket.py
  static/debug.html
scripts/spike.py   throwaway
tests/             one test file per module, fixtures in tests/fixtures/
```

---

### Task 1: Spike: does Decision 1 work, and what does Context.dev return?

Throwaway script, no tests. Needs `GEMINI_API_KEY` and `CONTEXT_DEV_API_KEY` in `.env`.

**Files:**
- Create: `pyproject.toml`, `.gitignore` (`.env`, `*.db`, `.venv/`, `__pycache__/`), `.env.example`, `scripts/spike.py`
- Create: `tests/fixtures/decision1_response.json`, `tests/fixtures/search_response.json`

**Produces:** the two fixtures (real, unedited API responses) and a filled-in "Spike results" table at the bottom of this plan. Tasks 3 and 7 read both.

- [ ] **Step 1:** `uv init --package --name terminal`, add `fastapi uvicorn httpx google-genai`, dev `pytest`. Run `uv run python -c "import fastapi, httpx, google.genai"`; expect no output.
- [ ] **Step 2:** Find the official Decisions API request format at ai.google.dev (leads from third-party write-ups, unconfirmed: model `gemini-decision-1`, API version `v1beta`, closed questions with 2 to 255 options, a probability per option, up to 1,000 questions per call). Get one call working and save the raw response to `tests/fixtures/decision1_response.json`.
- [ ] **Step 3:** Pick one open Polymarket market. Write 12 headlines for it by hand: 4 that should clearly move YES up, 4 clearly down, 4 irrelevant. Score all 12 with the question from Task 3. **Decision 1 is usable if at least 9 of 12 verdicts match the label.** Otherwise `SCORER=fallback`.
- [ ] **Step 4:** Call Context.dev `POST https://api.context.dev/v1/web/search` (`Authorization: Bearer`, body `{"query", "freshness": "last_24_hours", "numResults": 10}`) for that market's topic. Save the raw response to `tests/fixtures/search_response.json`. Note `key_metadata.credits_consumed`.
- [ ] **Step 5:** Repeat the search with `"includeDomains"` set to `["reddit.com"]`, then `["x.com"]`, then `["polymarket.com", "kalshi.com"]` with a plain-words question. For each, note how many results came back and whether they are from the last day.
- [ ] **Step 6:** Call `POST /v1/web/scrape` (`{"url", "formats": {"markdown": true}, "sharedParams": {"mainContentOnly": true}}`) on one article. Note the credits and whether `metadata` carries a publish date.
- [ ] **Step 7:** Fill in "Spike results" below. Commit.

---

### Task 2: Store

**Files:**
- Create: `terminal/db.py`, `tests/test_db.py`

**Interfaces (Produces):**
- `connect(path: str) -> sqlite3.Connection`: creates the schema if missing, `row_factory = sqlite3.Row`, WAL mode, `check_same_thread=False`.
- `add_market(db, *, id: str, venue: str, venue_ref: str | None, title: str, rules: str, url: str | None, lead_id: str | None = None, queries: list[str] = [], poll_seconds: int = 900) -> dict`. `venue` is `"polymarket" | "kalshi" | "made_up"`. Inserting an existing `id` returns the existing row unchanged.
- `get_market(db, id) -> dict | None`, `list_markets(db) -> list[dict]` (lead markets only, `lead_id IS NULL`), `related(db, lead_id) -> list[dict]`, `all_priced(db) -> list[dict]` (every row whose venue is not `made_up`).
- `add_price(db, market_id: str, ts: float, price: float) -> None`
- `price_at(db, market_id: str, ts: float) -> float | None`: the latest sample at or before `ts`.
- `prices(db, market_id: str, since: float = 0) -> list[dict]` as `{"ts", "price"}`, oldest first.
- `add_tick(db, tick: dict) -> dict | None`: returns the stored tick with its `id`, or `None` if `(market_id, dedupe_key)` already exists.
- `ticks(db, market_id: str, limit: int = 100, include_hidden: bool = False) -> list[dict]`, newest first.

Tick columns: `id, market_id, ts, published_ts, kind, source, url, headline, up, none, down, strength, verdict, confidence, price_at, test, backfill, hidden, dedupe_key`. `test`, `backfill`, `hidden` are returned as booleans. `queries` is stored as JSON and returned as a list.

- [ ] **Step 1: Write the failing tests**

```python
def test_price_at_returns_latest_sample_at_or_before():
    db = connect(":memory:")
    add_market(db, id="m", venue="kalshi", venue_ref="T", title="t", rules="r", url=None)
    add_price(db, "m", 100, 40.0); add_price(db, "m", 200, 55.0)
    assert price_at(db, "m", 99) is None
    assert price_at(db, "m", 150) == 40.0
    assert price_at(db, "m", 200) == 55.0

def test_duplicate_tick_is_rejected_per_market():
    # same dedupe_key twice on market "m" -> second add_tick returns None, ticks() has 1
    # same dedupe_key on market "n" -> stored

def test_hidden_ticks_are_excluded_by_default():
    # one hidden, one shown -> ticks() returns 1, ticks(include_hidden=True) returns 2

def test_related_contracts_are_not_listed_as_markets():
    # lead "m" and a row with lead_id="m" -> list_markets() ids == ["m"], related(db,"m") has 1

def test_add_market_twice_keeps_the_first():
    # second add_market(id="m", title="other") returns title "t"
```

- [ ] **Step 2:** Run `uv run pytest tests/test_db.py -v`. Expected: FAIL, `terminal.db` not found.
- [ ] **Step 3:** Implement `terminal/db.py` to the interfaces above.
- [ ] **Step 4:** Run the tests. Expected: 5 passed.
- [ ] **Step 5:** Commit.

---

### Task 3: Scoring and the made-up price rule

**Files:**
- Create: `terminal/scoring.py`, `terminal/pricing.py`, `tests/test_scoring.py`, `tests/test_pricing.py`

**Interfaces:**
- Consumes: `tests/fixtures/decision1_response.json` and the Spike results (Task 1).
- Produces:
  - `class Score(NamedTuple): up: float; none: float; down: float; strength: float`. `strength` runs from -1 (down a lot) to 1 (up a lot).
  - `verdict(s: Score) -> tuple[str, float]`: the largest of `"up" | "none" | "down"` and its probability. A tie that includes `none` resolves to `none`; an up/down tie resolves to `none`.
  - `is_hidden(s: Score, kind: str) -> bool`: true when the verdict is `none` with confidence at least `0.85` and `kind` is not `mic` or `typed`. Spoken and typed ticks are always shown, because the judge must see their own sentence scored.
  - `parse_decision1(response: dict) -> Score`: pure. Reads `answers.move` of a five-level `score` answer: `down` is the probability of levels 0 and 1, `none` of level 2, `up` of levels 3 and 4, and `strength` is `(score - 2) / 2`.
  - `async score(title: str, rules: str, text: str) -> Score`: the real scorer. Chooses Decision 1 or the fallback from `SCORER`. Raises `ScoringError` on any API failure or a 20-second timeout.
  - `nudge(price: float, strength: float, k: float = 0.4) -> float`

The question put to the scorer, exactly:

> Market: {title}
> Rules: {rules}
> New item: {text}
> How much does this new item move the price of YES in this market?

The market and rules lines are the request's `input`; the item and the question are the `instructions` of one `score` question with id `move` and these five levels, in order: `Moves the price down a lot`, `Moves the price down a little`, `No effect on the price`, `Moves the price up a little`, `Moves the price up a lot`. Graded scoring replaced the three-way choice after Task 1 (Georg agreed, 13 Nov). `rules` is cut to 1,500 characters and `text` to 2,000.

The fallback asks the model named by `GEMINI_TEXT_MODEL` the same question with structured output of five probabilities, one per level, divides by their sum, and builds the `Score` the same way.

`nudge` is the spec's rule, in percentages:

```python
def nudge(price, strength, k=0.4):
    p = min(max(price, 1.0), 99.0) / 100
    x = math.log(p / (1 - p)) + k * strength
    return min(max(100 / (1 + math.exp(-x)), 1.0), 99.0)
```

- [ ] **Step 1: Write the failing tests**

```python
def test_verdict_picks_the_largest():
    assert verdict(Score(0.84, 0.12, 0.04, 0.8)) == ("up", 0.84)
    assert verdict(Score(0.09, 0.20, 0.71, -0.6)) == ("down", 0.71)

def test_ties_resolve_to_none():
    assert verdict(Score(0.4, 0.4, 0.2, 0.1))[0] == "none"
    assert verdict(Score(0.45, 0.10, 0.45, 0.0))[0] == "none"

def test_confident_no_effect_is_hidden_except_for_spoken_and_typed():
    s = Score(0.05, 0.90, 0.05, 0.0)
    assert is_hidden(s, "article") is True
    assert is_hidden(s, "typed") is False and is_hidden(s, "mic") is False
    assert is_hidden(Score(0.2, 0.7, 0.1, 0.1), "article") is False

def test_parse_decision1_fixture_sums_to_one():
    s = parse_decision1(json.load(open("tests/fixtures/decision1_response.json")))
    assert abs(s.up + s.none + s.down - 1) < 0.01 and -1 <= s.strength <= 1

def test_nudge_moves_a_strong_up_tick_a_few_points():
    assert abs(nudge(20, 0.8) - 25.61) < 0.01

def test_nudge_is_symmetric_and_bounded():
    assert nudge(50, 0) == 50
    assert abs(nudge(50, 0.9) + nudge(50, -0.9) - 100) < 1e-9
    assert nudge(99, 1) <= 99 and nudge(1, -1) >= 1
    assert abs(nudge(150, 0) - 99) < 1e-9
```

- [ ] **Step 2:** Run `uv run pytest tests/test_scoring.py tests/test_pricing.py -v`. Expected: FAIL, modules not found.
- [ ] **Step 3:** Implement both modules. `score` uses the request format recorded in Spike results.
- [ ] **Step 4:** Run the tests. Expected: 6 passed.
- [ ] **Step 5:** Run `uv run --env-file .env python -c "import asyncio; from terminal.scoring import score; print(asyncio.run(score('Will it rain in Helsinki tomorrow?', 'Resolves yes if rain is recorded.', 'Forecast: heavy rain all day tomorrow in Helsinki')))"`. Expected: a `Score` whose `up` is the largest.
- [ ] **Step 6:** Commit.

---

### Task 4: Bus and pipeline

**Files:**
- Create: `terminal/bus.py`, `terminal/pipeline.py`, `tests/test_bus.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 2 `db`, Task 3 `Score`, `verdict`, `is_hidden`, `nudge`, `ScoringError`.
- Produces:
  - `class Bus`: `subscribe() -> asyncio.Queue` (max size 1000), `unsubscribe(q) -> None`, `publish(event: str, data: dict) -> None`. `publish` is synchronous and never blocks or raises; a subscriber whose queue is full is unsubscribed.
  - Queue items are `(event, data)` tuples. Events: `"tick"`, `"price"`, `"market"`.
  - `dedupe_key(kind: str, url: str | None, headline: str, ts: float) -> str`: for `mic` and `typed`, unique per call (includes `ts`). Otherwise the address with scheme, query string, fragment and trailing slash removed and the host lower-cased; with no address, the headline lower-cased with runs of non-alphanumerics collapsed to one space.
  - `async ingest(db, bus, scorer, market: dict, *, kind: str, source: str, headline: str, url: str | None = None, body: str = "", published_ts: float | None = None, backfill: bool = False, now: float | None = None) -> dict | None`

`ingest`, in order: compute the dedupe key and return `None` if that tick already exists; call `scorer(market["title"], market["rules"], headline + "\n" + body)`; on `ScoringError` return `None` without storing; set `verdict`, `confidence`, `hidden`, `test` (kind is `mic` or `typed`), `price_at` (from `db.price_at`); store; if the market's venue is `made_up`, store `nudge(current price, strength)` as a new price and publish `"price"` `{"market_id", "ts", "price"}`; publish `"tick"` unless hidden; return the tick. `scorer` is any `async (title, rules, text) -> Score`.

- [ ] **Step 1: Write the failing tests**

```python
UP = Score(0.84, 0.12, 0.04, 0.8)
async def up(*_): return UP

def test_typed_tick_on_made_up_market_moves_the_price_and_is_published():
    # made-up market "mu" with price 20 at ts 0; ingest kind="typed", now=10
    # -> tick["verdict"] == "up", tick["test"] is True, tick["price_at"] == 20
    # -> db.price_at(db, "mu", 10) is within 0.01 of 25.61
    # -> the subscriber queue holds ("price", ...) then ("tick", ...)

def test_article_on_real_market_does_not_move_the_price():
    # kalshi market with price 40; ingest kind="article" -> price_at still 40, no "price" event

def test_same_article_under_several_addresses_is_one_tick():
    urls = ["https://News.example.com/a/story", "https://news.example.com/a/story/",
            "http://news.example.com/a/story?utm_source=x", "https://news.example.com/a/story#top"]
    # ingest each -> first returns a tick, the other three return None

def test_same_typed_sentence_twice_is_two_ticks():
    # ingest kind="typed", headline="great idea", now=1 and now=2 -> both stored

def test_confident_no_effect_article_is_stored_but_not_published():
    # scorer returns Score(0.05, 0.9, 0.05, 0.0) -> returned tick["hidden"] is True, queue is empty,
    # db.ticks(include_hidden=True) has 1

def test_scorer_failure_stores_nothing_and_can_be_retried():
    # scorer raises ScoringError -> ingest returns None, no tick stored;
    # ingest again with the working scorer and the same address -> returns a tick

def test_publish_drops_a_full_subscriber_without_raising():
    # subscribe, publish 1001 events without reading -> no exception;
    # a later subscribe() + publish delivers to the new queue
```

- [ ] **Step 2:** Run `uv run pytest tests/test_bus.py tests/test_pipeline.py -v`. Expected: FAIL, modules not found.
- [ ] **Step 3:** Implement `bus.py` and `pipeline.py`. Tests drive `ingest` with `asyncio.run`; no pytest plugin.
- [ ] **Step 4:** Run the tests. Expected: 7 passed.
- [ ] **Step 5:** Commit.

---

### Task 5: API, stream, debug page: the demo opener

**Files:**
- Create: `terminal/api.py`, `terminal/seed.py`, `terminal/static/debug.html`, `tests/test_api.py`

**Interfaces:**
- Consumes: Tasks 2 to 4.
- Produces:
  - `seed.DEMO = {"id": "mu-demo", "title": "Will this team win the Context.dev challenge?", "rules": "Resolves yes if this team is announced as the winner of the Context.dev challenge at Junction 2026.", "start": 20.0}`
  - `create_app(db_path: str | None = None, scorer=None, poll: bool = True) -> FastAPI`. Defaults: `DB_PATH`, `scoring.score`. On startup it adds the demo market and its starting price only if `mu-demo` does not exist. `app = create_app()` at module level for uvicorn.
  - `app.state.db`, `app.state.bus`, `app.state.scorer` for later tasks.

Routes (shapes from the spec's "Interface for the frontend"):

| Route | Behaviour |
|---|---|
| `GET /markets` | list of `{id, venue, title, url, price, change_24h, ticks_today, made_up, poll_seconds}`. `change_24h` is the latest price minus the price 24 hours ago, `null` if there is no sample that old. `ticks_today` counts shown ticks in the last 24 hours. |
| `GET /markets/{id}` | the same fields plus `rules`, `queries`, `related` (same fields per related contract), `pages: []`. 404 if unknown. |
| `GET /markets/{id}/ticks?limit=` | shown ticks, newest first, default 100, max 500 |
| `GET /markets/{id}/prices?since=` | `[{ts, price}]` |
| `POST /markets/{id}/ticks` | body `{"text", "kind": "mic" or "typed"}`. `text` is trimmed and must be 1 to 500 characters, else 422. Unknown market 404. Scorer failure 503 with `{"detail": "scoring unavailable, try again"}`. Returns the tick. |
| `GET /stream` | `text/event-stream`. Each bus item as `event: <name>\ndata: <json>\n\n`. A `: keepalive` comment every 15 seconds. Unsubscribes when the client disconnects. |
| `GET /` | serves `static/debug.html` |

`debug.html` is one file of plain HTML and JavaScript, no build step: a market picker, the current price, the tape fed by `EventSource("/stream")`, and a text box that posts a typed tick. It exists so the pipeline can be checked without the real frontend.

- [ ] **Step 1: Write the failing tests** (FastAPI `TestClient`, `create_app(db_path=tmp_path/"t.db", scorer=up, poll=False)`)

```python
def test_demo_market_exists_at_20_percent():
    # GET /markets -> one item, id "mu-demo", made_up True, price 20.0

def test_typed_tick_is_scored_flagged_and_moves_the_demo_price():
    # POST /markets/mu-demo/ticks {"text": "that is clever", "kind": "typed"} -> 200,
    # body verdict "up", test True; GET /markets -> price within 0.01 of 25.61;
    # GET /markets/mu-demo/ticks -> 1 item

def test_bad_tick_input_is_rejected():
    # text "   " -> 422; text of 501 chars -> 422; kind "article" -> 422; market "nope" -> 404

def test_scorer_failure_is_a_503_and_the_service_keeps_working():
    # app with a scorer that raises ScoringError -> POST returns 503; GET /markets still 200

def test_restart_keeps_data_and_one_demo_market():
    # create_app on a path, post a tick, create_app again on the same path
    # -> GET /markets has exactly one "mu-demo", its price is still ~25.61, ticks has 1 item

def test_change_24h_is_null_without_an_old_sample():
    # fresh app -> GET /markets item change_24h is None
```

- [ ] **Step 2:** Run `uv run pytest tests/test_api.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `seed.py`, `api.py`, `static/debug.html`.
- [ ] **Step 4:** Run the tests. Expected: 6 passed.
- [ ] **Step 5:** Run `uv run --env-file .env uvicorn terminal.api:app --port 8000`, open `http://localhost:8000`, type "this is the best project here" and then "I had pasta for lunch". Expected: the first appears as up and the price rises above 20; the second appears as no effect and the price does not move. In a second terminal, `curl -N localhost:8000/stream` shows a `tick` event for each.
- [ ] **Step 6:** Commit. Tell Georg the teammate can now build against a local server.

---

### Task 6: Real markets from a link, and price sampling

**Files:**
- Create: `terminal/venues/__init__.py`, `terminal/venues/kalshi.py`, `terminal/venues/polymarket.py`, `terminal/poller.py`, `tests/test_venues.py`, `tests/test_poller.py`
- Create: `tests/fixtures/kalshi_event.json`, `tests/fixtures/polymarket_event.json` (real responses, saved in Step 1)
- Modify: `terminal/api.py` (add `POST /markets`, start the price loop)

**Interfaces:**
- Consumes: the spec's "Existing venue code to reuse" table. Copy `get` and `paged` from `~/scorer-mm/scorer_mm/kalshi.py` into `venues/kalshi.py`, and `get` plus the `GAMMA`, `CLOB` constants from `~/weather-mm/weather_mm/pm.py` into `venues/polymarket.py`. Both are blocking; call them with `asyncio.to_thread`.
- Produces:
  - A contract is `{"venue", "venue_ref", "title", "rules", "url", "price"}` with `price` a percentage or `None`.
  - `kalshi.parse_link(url) -> str | None`: the last path segment, upper-cased, for a `kalshi.com/markets/...` address.
  - `kalshi.parse_event(event: dict, wanted: str) -> list[dict]`: contracts from `GET /events/{event_ticker}?with_nested_markets=true`, the one whose ticker equals `wanted` first, else the highest-volume one first. Price is the midpoint of the yes bid and ask when both are present and the ask is above the bid, else the last price, else `None`.
  - `polymarket.parse_link(url) -> tuple[str, str | None] | None`: `(event_slug, market_slug)` for a `polymarket.com/event/...` address.
  - `polymarket.parse_event(event: dict, market_slug: str | None) -> list[dict]`: contracts from Gamma `GET /events?slug=`, the one matching `market_slug` first, else the highest-volume one first. `venue_ref` is the YES token id (first of `clobTokenIds`), `rules` is `description`, price is the first of `outcomePrices` times 100. Closed markets are left out.
  - `async venues.resolve(link: str) -> list[dict]`: lead contract first. A Kalshi link's last segment may be an event ticker or a market ticker: try `GET /events/{ticker}` first, and on 404 `GET /markets/{ticker}` to learn its `event_ticker`. Raises `ValueError("not a Kalshi or Polymarket market link")` for anything else and `LookupError("market not found")` when the venue has no such market.
  - `async venues.current_price(market: dict) -> float | None`: Kalshi `GET /markets/{ticker}`; Polymarket CLOB `GET /midpoint?token_id=`. Any failure returns `None`.
  - `async poller.sample_prices(db, bus, now: float | None = None) -> int`: one pass over `db.all_priced`, stores and publishes each price that is not `None`, returns how many were stored.
  - `async poller.price_loop(db, bus, interval: float = 60) -> None`: calls `sample_prices` forever; an exception in one pass is logged and the loop continues.
  - `POST /markets` body `{"query": str, "poll_seconds": int = 900}`. `query` 1 to 500 characters; `poll_seconds` at least 30. A link is resolved; the lead becomes a market with id `pm-<market slug>` or `k-<ticker>`, the rest are stored with `lead_id`. Publishes `"market"` `{"market_id", "status": "tracking"}`. Returns the `GET /markets/{id}` shape. Adding a market that already exists returns it. `ValueError` is 422 with `{"detail": "paste a Kalshi or Polymarket market link"}` (plain words arrive in plan 2); `LookupError` is 404.

- [ ] **Step 1:** Save one real multi-market response from each venue into the two fixture files, using the copied `get` functions.
- [ ] **Step 2: Write the failing tests**

```python
def test_parse_links():
    assert kalshi.parse_link("https://kalshi.com/markets/kxfed/fed-meeting/kxfed-26dec") == "KXFED-26DEC"
    assert polymarket.parse_link("https://polymarket.com/event/fed-decision-in-december") == ("fed-decision-in-december", None)
    assert polymarket.parse_link("https://polymarket.com/event/a-b/c-d?tid=1") == ("a-b", "c-d")
    assert kalshi.parse_link("https://example.com/x") is None and polymarket.parse_link("will it rain") is None

def test_parse_event_fixtures_yield_percent_prices_and_rules():
    # for each fixture: every contract has non-empty title and rules, venue_ref set,
    # price is None or 0 <= price <= 100; the lead is the wanted/highest-volume one

def test_kalshi_price_is_none_without_bids_or_last_price():
    # a market dict with yes_bid 0, yes_ask 1 (or their dollar forms) and no last price -> price None

def test_sample_prices_skips_markets_with_no_price_and_keeps_going():
    # two real markets; current_price patched to return None for the first, 61.0 for the second
    # -> returns 1, db.price_at for the second == 61.0, one "price" event published

def test_post_market_rejects_plain_words_for_now():
    # POST /markets {"query": "will jensen get fired"} -> 422

def test_post_market_tracks_lead_and_related():
    # venues.resolve patched to return 3 contracts -> 200; GET /markets lists 2 (demo + lead);
    # GET /markets/{id} has 2 related; a second identical POST returns the same id, no duplicates
```

- [ ] **Step 3:** Run `uv run pytest tests/test_venues.py tests/test_poller.py -v`. Expected: FAIL.
- [ ] **Step 4:** Implement the venue modules, `poller.sample_prices`, `poller.price_loop`, and `POST /markets`. `create_app(poll=True)` starts `price_loop` as a background task in the app's lifespan and cancels it on shutdown.
- [ ] **Step 5:** Run all tests. Expected: all pass.
- [ ] **Step 6:** With the server running, `curl -X POST localhost:8000/markets -H 'content-type: application/json' -d '{"query": "<a live Polymarket link>"}'`, then the same with a live Kalshi link. Expected: both return a market with a price between 0 and 100, and within 2 minutes `GET /markets/{id}/prices` has at least 2 samples each.
- [ ] **Step 7:** Commit.

---

### Task 7: Articles as ticks, and instant fill

**Files:**
- Create: `terminal/contextdev.py`, `terminal/watch.py`, `tests/test_contextdev.py`, `tests/test_articles.py`
- Modify: `terminal/poller.py`, `terminal/api.py`

**Interfaces:**
- Consumes: `tests/fixtures/search_response.json`, Task 4 `ingest`, Task 6.
- Produces:
  - `contextdev.parse_search(response: dict) -> list[dict]`: `[{"url", "title", "description"}]`, dropping results without a `url` or `title`.
  - `async contextdev.search(query: str, *, freshness: str = "last_24_hours", include_domains: list[str] | None = None, num_results: int = 10) -> list[dict]`: `POST https://api.context.dev/v1/web/search` with `CONTEXT_DEV_API_KEY`. Returns `[]` on any failure, after logging it.
  - `async watch.queries_for(title: str, rules: str) -> list[str]`: asks `GEMINI_TEXT_MODEL` for 3 to 5 short web-search queries that would find news bearing on this market, as a JSON list. On any failure returns `[title]`.
  - `async poller.fetch_articles(db, bus, scorer, market: dict, *, backfill: bool, num_results: int, search=contextdev.search) -> int`: runs every query in `market["queries"]`, ingests each result as `kind="article"`, `source` the address's host without `www.`, `headline` the title, `body` the description, and returns how many ticks were stored. At most 10 ingests run at once.
  - `async poller.article_loop(db, bus, scorer) -> None`: every 15 seconds, calls `fetch_articles(backfill=False, num_results=10)` for each real lead market whose last fetch was at least `poll_seconds` ago. Last-fetch times are kept in memory. An exception for one market is logged and the loop continues.
  - `POST /markets` now also: sets `queries` from `watch.queries_for`, publishes `"market"` `{"market_id", "status": "finding sources"}`, and starts `fetch_articles(backfill=True, num_results=20)` as a background task so the response is not held up.

Search results carry no publish date (checked against docs.context.dev), so `published_ts` stays `null` for articles unless Task 1 found one in scrape metadata. Backfilled ticks are still flagged `backfill: true`.

Credit use, at 1 credit per 10 results: a market on `poll_seconds=60` with 4 queries spends about 5,800 credits a day; one on 900 about 380 a day. One headline market plus 20 others is about 13,500 a day.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_search_fixture():
    rows = parse_search(json.load(open("tests/fixtures/search_response.json")))
    assert rows and all(r["url"].startswith("http") and r["title"] for r in rows)

def test_fetch_articles_ingests_each_result_once_across_queries():
    # market with queries ["a", "b"]; fake search returns the same 2 results for both
    # -> returns 2; ticks have kind "article", backfill True, test False,
    #    source "news.example.com" for url "https://www.news.example.com/x"

def test_fetch_articles_survives_a_failing_search():
    # fake search raises for query "a", returns 1 result for "b" -> returns 1, no exception

def test_queries_fall_back_to_the_title():
    # model call patched to raise -> queries_for("T", "R") == ["T"]
```

- [ ] **Step 2:** Run `uv run pytest tests/test_contextdev.py tests/test_articles.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. `create_app(poll=True)` starts `article_loop` alongside `price_loop`.
- [ ] **Step 4:** Run all tests. Expected: all pass.
- [ ] **Step 5:** With the server running, add a market that is in the news with `"poll_seconds": 60`. Expected: within 30 seconds the debug page's tape shows scored articles for it, and `GET /markets/{id}` shows 3 to 5 queries.
- [ ] **Step 6:** Commit.

---

### Task 8: Weekend record

**Files:**
- Create: `terminal/record.py`, `tests/test_record.py`
- Modify: `terminal/api.py` (add `GET /record`)

**Interfaces:**
- Produces: `record(db, now: float | None = None, window: float = 900, min_move: float = 1.0) -> dict` returning `{"called", "moved", "same_way", "window_seconds", "since"}`.

Eligible ticks: verdict `up` or `down`, `test` false, `backfill` false, market venue not `made_up`, `price_at` not null, and `ts + window <= now`. Hidden ticks cannot be eligible because hiding requires verdict `none`. `called` counts eligible ticks. For each, the later price is `db.price_at(market_id, ts + window)`; it counts in `moved` if the absolute difference from `price_at` is at least `min_move`, and in `same_way` if it also has the verdict's sign. `since` is the earliest tick `ts`, or `null`.

- [ ] **Step 1: Write the failing test**

```python
def test_record_counts_only_eligible_ticks_and_real_moves():
    # kalshi market "m": prices 40 at t=0, 43 at t=600, 39 at t=1500, 39.5 at t=2400
    # ticks on "m": up at t=10 (40 -> 43, same way), up at t=700 (43 -> 39, moved, wrong way),
    #   down at t=1600 (39 -> 39.5, did not move), up at t=5000 (too recent for now=5100),
    #   up at t=20 with backfill, up at t=30 with test
    # made-up market "mu": up at t=10
    assert record(db, now=5100) == {"called": 3, "moved": 2, "same_way": 1,
                                    "window_seconds": 900, "since": 10}
```

- [ ] **Step 2:** Run `uv run pytest tests/test_record.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `record.py` and the route.
- [ ] **Step 4:** Run all tests. Expected: all pass.
- [ ] **Step 5:** Commit.

---

### Task 9: Deploy and start the weekend log

Outward-facing: confirm with Georg before deploying. Use the `use-railway` skill.

**Files:**
- Create: `Dockerfile` (uv image, `uv sync --frozen`, `uvicorn terminal.api:app --host 0.0.0.0 --port $PORT`), `markets.txt` (one market link per line, optional poll seconds after a space)
- Create: `scripts/seed_markets.py`: posts each line of `markets.txt` to `POST /markets` on the address given as its argument and prints the id or the error for each.

- [ ] **Step 1:** Create a Railway service with a volume mounted at `/data`. Set `DB_PATH=/data/terminal.db`, `GEMINI_API_KEY`, `CONTEXT_DEV_API_KEY`, `SCORER`, `GEMINI_TEXT_MODEL`. Deploy and generate a public domain.
- [ ] **Step 2:** `curl https://<domain>/markets`. Expected: the demo market at 20.
- [ ] **Step 3:** Fill `markets.txt`: the Nvidia CEO-exit market with `60`, plus about 20 open markets that move on news (Georg picks, or take the highest 24-hour-volume non-sports events from Polymarket's Gamma API). Run `uv run python scripts/seed_markets.py https://<domain>`. Expected: an id per line.
- [ ] **Step 4:** After 20 minutes: `curl https://<domain>/record` returns a `since` value, and Context.dev's dashboard shows credit use in line with Task 7's estimate. Redeploy once and confirm the markets and ticks are still there.
- [ ] **Step 5:** Commit. Give Georg the public address for the teammate.

---

## Spike results

Filled in by Task 1.

| Question | Answer |
|---|---|
| Decision 1 request format (endpoint, body) | Confirmed 13 Nov with real calls. Not on Vertex AI; on the Gemini API only. `POST https://generativelanguage.googleapis.com/v1beta/decisions`, header `x-goog-api-key`. Body: `{"model": "gemini-decision-1", "input": "<text>", "questions": {"<id>": {"type": "choice", "instructions": "<question>", "criteria": {"<option id>": "<description>"}}}}`. `questions` is a map, not a list. Types: `choice` (2 to 255 options), `score` (`criteria` is a list of ordered levels), `noul` (yes/no, no options). Response: `answers.<id>` with `choice`, `confidence`, `probabilities.<option id>`; for `score`, `score` (expected level) and `probabilities."0".."n"`. Reference: aistudio.google.com/api-reference/decisions/create-decision. Fixture saved in `tests/fixtures/decision1_response.json`. |
| Batching | One call can carry the market as `input` and one question per item. 12 items in one call took 0.28 s and 1,164 tokens; 12 separate calls took 0.23 s each and 2,209 tokens in total. Use one batched call for instant fill. |
| Verdicts matching the label, out of 12 | 12 of 12, both batched and one by one. The headlines were hand-written and easy; real articles will be harder. Confidence was above 0.87 on every one, so a three-way choice says almost nothing about how big a move is. |
| Graded moves | A `score` question with five levels (down a lot, down a little, no effect, up a little, up a lot) separates sizes: "officially announces he has resigned" scored 3.95 of 4, "board calls emergency meeting" 3.74, "analyst says succession is worth watching" 2.42, irrelevant items 1.93 to 2.00, "signs new five-year contract" 0.36. Proposed to Georg as a replacement for the three-way choice; Task 3 is unchanged until he agrees. |
| `SCORER` | `decision1` |
| Credits per search of 10 results; per scrape | |
| Search restricted to reddit.com: results, freshness | |
| Search restricted to x.com: results, freshness | |
| Search restricted to polymarket.com and kalshi.com: finds the market? | |
| Scrape metadata carries a publish date? | |
