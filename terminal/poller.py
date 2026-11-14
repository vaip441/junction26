"""Background loops: price sampling, article polling, instant fill."""
import asyncio
import logging
import re
import time
from urllib.parse import urlsplit

from terminal import contextdev, googlenews, madeup, moves, posts, venues, watch
from terminal import db as store
from terminal.pipeline import STORY_SECONDS, dedupe_key, ingest, public, title_key
from terminal.scoring import Score

log = logging.getLogger(__name__)


async def sample_prices(db, bus, now: float | None = None) -> int:
    """One pass over every real market and related contract. Returns how many prices were stored."""
    now = time.time() if now is None else now
    markets = store.all_priced(db)
    results = await asyncio.gather(*(venues.current_price(m) for m in markets), return_exceptions=True)
    stored = 0
    for m, price in zip(markets, results):
        if isinstance(price, BaseException):
            log.warning("price sample failed for %s: %s", m["id"], price)
        elif price is not None:
            store.add_price(db, m["id"], now, price)
            bus.publish("price", {"market_id": m["id"], "ts": now, "price": price})
            stored += 1
    return stored


async def forever(name: str, interval: float, step) -> None:
    """Run step() every interval seconds; one failing pass is logged, never fatal."""
    while True:
        try:
            await step()
        except Exception:
            log.exception("%s pass failed", name)
        await asyncio.sleep(interval)


def explain_moves(db, bus, scorer, busy: set, explaining: dict, now: float | None = None) -> None:
    """Start an explanation, in the background, for every fresh price move that is not being explained yet."""
    async def one(move: dict) -> None:
        try:
            await moves.explain(db, bus, move["market"], move, fetch=lambda m: fetch_now(db, bus, scorer, m, busy))
        except Exception:
            log.exception("could not explain the move of %s", move["market"]["id"])

    for move in moves.find(db, time.time() if now is None else now):
        id = move["market"]["id"]
        if id not in explaining:  # it takes a search: the next samples see the same move
            explaining[id] = asyncio.create_task(one(move))
            explaining[id].add_done_callback(lambda _, id=id: explaining.pop(id, None))


async def price_loop(db, bus, scorer, busy: set, interval: float = 60) -> None:
    """Sample prices every minute; a price that jumped gets its cause looked for (see moves.py).
    `busy` is the article loop's: the markets being searched right now."""
    explaining: dict[str, asyncio.Task] = {}

    async def step() -> None:
        await sample_prices(db, bus)
        explain_moves(db, bus, scorer, busy, explaining)

    try:
        await forever("price", interval, step)
    finally:
        for task in explaining.values():
            task.cancel()


# Reference pages and the venues' own pages are not news: an encyclopedia entry or a report of the
# market's odds says nothing the price does not already hold.
# Nor are social media pages: in one day 98 of them were shown as articles (Facebook 57, YouTube 21,
# Instagram 16), each a post or a video with no article behind it.
NOT_NEWS = ["wikipedia.org", "polymarket.com", "kalshi.com",
            "facebook.com", "instagram.com", "threads.com", "threads.net", "tiktok.com", "youtube.com", "youtu.be"]


class FetchFailed(Exception):
    """Every search for a market failed, so nothing is known about its coverage."""


POST_SITES = ["x.com", "twitter.com", "reddit.com"]


def post_source(url: str) -> str:
    """Who posted, as far as the address says: x.com/<handle> or reddit.com/r/<subreddit>."""
    u = urlsplit(url)
    host, parts = u.netloc.lower().removeprefix("www."), [p for p in u.path.split("/") if p]
    if parts[:1] == ["i"]:
        parts = []  # x.com/i/status/<id> names no one
    return "/".join([host] + parts[:2 if host.endswith("reddit.com") else 1])


def posted_at(url: str) -> float | None:
    """When a post on X was made: its id holds the time (ids since late 2010)."""
    u = urlsplit(url)
    m = re.search(r"/status/(\d+)", u.path)
    if u.netloc.lower().removeprefix("www.") not in ("x.com", "twitter.com") or not m or int(m[1]) < 10**15:
        return None
    return ((int(m[1]) >> 22) + 1288834974657) / 1000


# Requests a minute per key that routine polling leaves free, so a person's question, and the first
# fill of the market it creates, are not queued behind it.
BACKGROUND_RESERVE = 2


FEED_WINDOW = 86400  # a feed's posts count for a day, like the searches' "last 24 hours"


async def unscored(*_) -> Score:
    """Trash is kept as a hidden no-effect tick without asking the model: stored, it is never looked at again."""
    return Score(0.0, 1.0, 0.0, 0.0)


async def fetch_articles(db, bus, scorer, market: dict, *, backfill: bool, num_results: int,
                         search=None, scrape=None, lookup=None, feed=None, news=None, gnews=None) -> int:
    """Search every query of a market, plus X and Reddit once, read the newest posts of the subreddits
    that were relevant to it before, and ingest what was not seen before. Returns how many ticks were stored.

    Every query runs on every pass: measured on 14 Nov, a market's four queries returned 25 to 28
    different results between them, so dropping or rotating them would lose coverage, not waste.
    """
    search, scrape = search or contextdev.search, scrape or contextdev.scrape
    lookup, feed, news = lookup or posts.x_post, feed or posts.subreddit_new, news or contextdev.news
    gnews = gnews or googlenews.search
    queries, reserve = market["queries"], 0 if backfill else BACKGROUND_RESERVE
    # X and Reddit are left to the posts search: found here too, one post would be two ticks, one unfiltered
    searches = [("article", q, {"exclude_domains": NOT_NEWS + POST_SITES}) for q in queries]
    searches.append(("post", queries[0], {"include_domains": POST_SITES}))  # posts: the first query only
    # the news index is minutes behind the publishers where the web search is hours, but knows companies only
    companies = market.get("companies") or []
    found = await asyncio.gather(*(search(q, num_results=num_results, reserve=reserve, **kw) for _, q, kw in searches),
                                 *(news(c, since=time.time() - FEED_WINDOW, reserve=reserve) for c in companies),
                                 *(gnews(q) for q in queries),  # last: a story also found above keeps its own address
                                 return_exceptions=True)
    fresh, failed, stories = {}, [], set()
    sources = searches + [("news", c, None) for c in companies] + [("Google News", q, None) for q in queries]
    for (kind, q, _), results in zip(sources, found):
        if isinstance(results, BaseException):
            log.warning("%s search failed for %r on %s: %s", kind, q, market["id"], results)
            failed.append(kind)
            continue
        kind = "article" if kind in ("news", "Google News") else kind
        for r in results:
            try:
                key = dedupe_key(kind, r["url"], r["title"], 0)
            except ValueError:  # an address that cannot be parsed
                continue
            story = title_key(r["title"]) if kind == "article" else None  # one story, many outlets and addresses
            if key in fresh or store.has_tick(db, market["id"], key):
                continue
            # the web search is told which sites are not news; the news index and Google News are held to the same list
            host = r.get("source") or urlsplit(r["url"]).netloc.lower().removeprefix("www.")
            if kind == "article" and any(host == site or host.endswith("." + site) for site in NOT_NEWS + POST_SITES):
                continue
            if story and (story in stories or store.has_title(db, market["id"], story, time.time() - STORY_SECONDS)):
                continue
            fresh[key] = (kind, r)
            stories.add(story)
    # a failed posts search alone does not fail the pass; one whose article searches all failed does
    if failed.count("article") == len(queries) > 0:
        raise FetchFailed(f"{len(failed)} of {len(searches)} searches failed for {market['id']}")
    for sub in store.subreddits(db, market["id"]):
        for r in await feed(sub):  # off-topic posts and recurring threads are passed over at no cost
            if (posts.reddit_trash(r["url"], r["title"]) or (r["published"] or 0) < time.time() - FEED_WINDOW
                    or not posts.shares_words(f"{r['title']} {r['description']}", queries)):
                continue
            key = dedupe_key("post", r["url"], r["title"], 0)
            if key not in fresh and not store.has_tick(db, market["id"], key):
                fresh[key] = ("post", r)
    if backfill:  # for the frontend: how much the first fill found, before the scoring that takes most of its time
        bus.publish("market", {"market_id": market["id"], "status": "scoring", "found": len(fresh)})
    limit = asyncio.Semaphore(10)

    async def one(kind: str, r: dict) -> bool:
        async with limit:
            text, published, read, known, trash = "", None, None, None, False
            source = (post_source(r["url"]) if kind == "post"
                      else r.get("source") or urlsplit(r["url"]).netloc.lower().removeprefix("www."))  # Google names the publisher
            if kind == "post" and (published := posted_at(r["url"])):  # on X: the id holds the time
                if known := await lookup(r["url"]):
                    source, text = f"x.com/{known['handle']}", known["text"]
                    trash = posts.x_trash(known, time.time() - published)
            elif kind == "post":  # Reddit: a feed gives the time; a search result does not, nor does the page
                published = r.get("published")
                trash = source.split("/")[0].endswith("reddit.com") and posts.reddit_trash(r["url"], r["title"])
            elif r.get("published"):
                published = r["published"]  # the news index and Google News state the time: no page to read
                read = (published,)
            elif (read := store.date_known(db, r["url"])) is not None:
                published = read[0]  # this address was read before, under this or another market
            else:
                try:  # the page carries the publish time; read now only with spare capacity
                    text, published = await scrape(r["url"])
                    read = (published,) if text or published else None  # else left for the batch fill
                except Exception as e:
                    log.warning("scrape failed for %s: %s", r["url"], e)
            # search is asked for the last day but also returns older pages: those are history, not live ticks
            old = published is not None and published < time.time() - FEED_WINDOW
            try:
                tick = await ingest(db, bus, unscored if trash else scorer, market, kind=kind, source=source,
                                    headline=r["title"], url=r["url"],
                                    body=(text or r.get("text") or r["description"])[:2000], published_ts=published,
                                    backfill=backfill or old, likes=known and known["likes"],
                                    replies=known and known["replies"],
                                    # the search's own excerpt of the page, for the frontend; a post is its own passage
                                    passage=(contextdev.passage([r.get("text") or ""]) or None) if kind == "article" else None)
            except Exception:  # one odd page must not cost the market the rest of the batch
                log.exception("could not ingest %s", r["url"])
                return False
            if tick is not None and read is not None:
                store.set_published(db, r["url"], published)  # remembered, so no market reads it again
            return tick is not None

    return sum(await asyncio.gather(*(one(kind, r) for kind, r in fresh.values())))


async def fetch_now(db, bus, scorer, market: dict, busy: set, fetch=None) -> None:
    """Search for one market right away, outside its polling interval. If an article pass is on it
    already, wait for that instead: searched twice at once, every new item would be scored twice."""
    id = market["id"]
    if id in busy:
        for _ in range(120):  # a pass over one market takes well under two minutes
            if id not in busy:
                break
            await asyncio.sleep(1)
        return
    busy.add(id)
    try:
        await (fetch or fetch_articles)(db, bus, scorer, market, backfill=False, num_results=10)
    finally:
        busy.discard(id)


DATE_BATCH = 100


async def fill_dates(db, bus, *, published_times=None) -> int:
    """Look up the publish times still missing on shown articles, in one batch. Returns how many addresses
    were looked up. Each is looked up once: a page that cannot be read or carries no time is not retried."""
    urls = store.undated_urls(db, DATE_BATCH)
    if not urls:
        return 0
    times = await (published_times or contextdev.published_times)(urls)
    for url in urls:
        for tick in store.set_published(db, url, times.get(url)):
            bus.publish("tick_update", public(tick))
    return len(urls)


async def date_loop(db, bus, interval: float = 60) -> None:
    await forever("dates", interval, lambda: fill_dates(db, bus))


RETRY_SECONDS = 60


def retry_delay(fails: int) -> float:
    """A market that failed is tried again in a minute, then 2, 4, ... up to an hour: one whose queries
    the model will not write, or whose searches all fail, must not cost a call a minute forever."""
    return min(RETRY_SECONDS * 2 ** min(fails - 1, 10), 3600)


def due(db, last_fetch: dict, now: float) -> list[dict]:
    """Lead markets whose polling interval has passed: not-yet-filled ones first, then the fastest.
    A poll interval of 0 means never (the demo market moves only by what is said to it)."""
    ms = [m for m in store.list_markets(db)
          if m["poll_seconds"] > 0 and now - last_fetch.get(m["id"], 0) >= m["poll_seconds"]]
    return sorted(ms, key=lambda m: (m["filled"], m["poll_seconds"]))


MARKETS_AT_ONCE = 4
PAGE_RETRY = 6 * 3600


async def article_pass(db, bus, scorer, last_fetch: dict, now: float | None = None, *, queries_for=None,
                       companies_for=None, fetch=None, starting_price=None, limit: asyncio.Semaphore | None = None,
                       busy: set | None = None, fails: dict | None = None, watch_page=None) -> None:
    """One round over the due markets. This is the only place articles are fetched, so a market's first
    completed pass is its backfill and every later pass is live; the two never race.

    Passes may overlap (see article_loop), sharing `limit` and `busy`: a market being fetched is never
    fetched a second time, and routine fetches stay capped across passes. A first fill does not queue.
    """
    queries_for, fetch = queries_for or watch.queries_for, fetch or fetch_articles
    companies_for = companies_for or watch.companies_for
    starting_price = starting_price or madeup.starting_price
    limit = limit or asyncio.Semaphore(MARKETS_AT_ONCE)
    busy = set() if busy is None else busy
    fails = {} if fails is None else fails  # market id -> failed passes in a row
    started = time.time() if now is None else now
    markets = [m for m in due(db, last_fetch, started) if m["id"] not in busy]
    last_fetch.update({m["id"]: started for m in markets})
    busy.update(m["id"] for m in markets)

    async def work(m: dict) -> None:
        id, poll = m["id"], m["poll_seconds"]
        try:
            if not m["queries"]:
                store.set_queries(db, id, await queries_for(m["title"], m["rules"]))
                if (m := store.get_market(db, id)) is None:
                    return  # deleted meanwhile
            if m["companies"] is None:  # asked once; the pass goes on without them if the model cannot be reached
                try:
                    store.set_companies(db, id, await companies_for(m["title"], m["rules"]))
                    if (m := store.get_market(db, id)) is None:
                        return
                except Exception as e:
                    log.warning("could not name the companies of %s, asking again next pass: %s", id, e)
            # once per market; one that had no page worth watching is looked at again after PAGE_RETRY, since
            # the search and the model answer differently on another try. None without a public address.
            if watch_page and not any(p["url"] or p["created_ts"] > started - PAGE_RETRY for p in store.pages(db, id)):
                try:
                    await watch_page(db, m)
                except Exception as e:
                    log.warning("could not set up the page watch of %s, trying again next pass: %s: %s",
                                id, type(e).__name__, e)
            first = not m["filled"]
            if first:
                bus.publish("market", {"market_id": m["id"], "status": "finding sources", "queries": m["queries"]})
            n = await fetch(db, bus, scorer, m, backfill=first, num_results=20 if first else 10)
            if first and m["venue"] == "made_up" and store.latest_price(db, m["id"]) is None:
                # a made-up market opens at the model's odds given the coverage just found
                price = await starting_price(m["title"], m["rules"], store.headlines(db, m["id"]))
                store.add_price(db, m["id"], started, price)
                bus.publish("price", {"market_id": m["id"], "ts": started, "price": price})
            if first:
                store.set_filled(db, m["id"])
                bus.publish("market", {"market_id": m["id"], "status": "ready", "ticks": n})
            fails.pop(id, None)
        except Exception as e:
            fails[id] = fails.get(id, 0) + 1
            delay = retry_delay(fails[id])
            log.warning("article pass failed for %s, retrying in %ss: %s: %s", id, delay, type(e).__name__, e)
            last_fetch[id] = started - poll + delay

    async def one(m: dict) -> None:
        try:
            if m["filled"]:
                async with limit:
                    await work(m)
            else:  # someone just asked for this market: do not queue it behind routine polling
                await work(m)
        finally:
            busy.discard(m["id"])

    await asyncio.gather(*(one(m) for m in markets))


async def article_loop(db, bus, scorer, wake: asyncio.Event, busy: set | None = None, watch_page=None) -> None:
    """Run article passes forever. `wake` starts the next pass at once, for a newly added market.
    `busy` holds the markets being searched; the price loop adds one while it looks behind a move."""
    last_fetch: dict[str, float] = {}
    running: set[asyncio.Task] = set()
    busy = set() if busy is None else busy
    limit = asyncio.Semaphore(MARKETS_AT_ONCE)  # shared, so overlapping passes cannot exceed the cap
    fails: dict[str, int] = {}

    async def one_pass() -> None:
        try:
            await article_pass(db, bus, scorer, last_fetch, limit=limit, busy=busy, fails=fails, watch_page=watch_page)
        except Exception:
            log.exception("article pass failed")

    try:
        while True:
            # a pass over a dozen markets takes minutes; a market added meanwhile gets its own pass now
            task = asyncio.create_task(one_pass())
            running.add(task)
            task.add_done_callback(running.discard)
            try:
                await asyncio.wait_for(wake.wait(), 15)
            except asyncio.TimeoutError:
                pass
            wake.clear()
    finally:
        for task in running:
            task.cancel()
