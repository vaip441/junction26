"""Background loops: price sampling, article polling, instant fill."""
import asyncio
import logging
import time
from urllib.parse import urlsplit

from terminal import contextdev, venues, watch
from terminal import db as store
from terminal.pipeline import dedupe_key, ingest

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


async def price_loop(db, bus, interval: float = 60) -> None:
    await forever("price", interval, lambda: sample_prices(db, bus))


# Reference pages and the venues' own pages are not news: an encyclopedia entry or a report of the
# market's odds says nothing the price does not already hold.
NOT_NEWS = ["wikipedia.org", "polymarket.com", "kalshi.com"]


class FetchFailed(Exception):
    """Every search for a market failed, so nothing is known about its coverage."""


async def fetch_articles(db, bus, scorer, market: dict, *, backfill: bool, num_results: int,
                         search=None, scrape=None) -> int:
    """Search every query of a market and ingest results not seen before. Returns how many ticks were stored."""
    search, scrape = search or contextdev.search, scrape or contextdev.scrape
    found = await asyncio.gather(*(search(q, num_results=num_results, exclude_domains=NOT_NEWS)
                                   for q in market["queries"]), return_exceptions=True)
    fresh, failed = {}, 0
    for q, results in zip(market["queries"], found):
        if isinstance(results, BaseException):
            log.warning("search failed for %r on %s: %s", q, market["id"], results)
            failed += 1
            continue
        for r in results:
            key = dedupe_key("article", r["url"], r["title"], 0)
            if key not in fresh and not store.has_tick(db, market["id"], key):
                fresh[key] = r
    if failed and failed == len(market["queries"]):
        raise FetchFailed(f"all {failed} searches failed for {market['id']}")
    limit = asyncio.Semaphore(10)

    async def one(r) -> bool:
        async with limit:
            try:
                text, published = await scrape(r["url"])  # only with spare capacity; it carries the publish date
            except Exception as e:
                log.warning("scrape failed for %s: %s", r["url"], e)
                text, published = "", None
            host = urlsplit(r["url"]).netloc.lower().removeprefix("www.")
            try:
                tick = await ingest(db, bus, scorer, market, kind="article", source=host, headline=r["title"],
                                    url=r["url"], body=(text or r.get("text") or r["description"])[:2000],
                                    published_ts=published, backfill=backfill)
            except Exception:  # one odd page must not cost the market the rest of the batch
                log.exception("could not ingest %s", r["url"])
                return False
            return tick is not None

    return sum(await asyncio.gather(*(one(r) for r in fresh.values())))


RETRY_SECONDS = 60


def due(db, last_fetch: dict, now: float) -> list[dict]:
    """Real lead markets whose polling interval has passed: not-yet-filled ones first, then the fastest."""
    ms = [m for m in store.list_markets(db)
          if m["venue"] != "made_up" and now - last_fetch.get(m["id"], 0) >= m["poll_seconds"]]
    return sorted(ms, key=lambda m: (m["filled"], m["poll_seconds"]))


async def article_pass(db, bus, scorer, last_fetch: dict, now: float | None = None, *,
                       queries_for=None, fetch=None) -> None:
    """One round over the due markets. This is the only place articles are fetched, so a market's
    first completed pass is its backfill and every later pass is live; the two can never race."""
    queries_for, fetch = queries_for or watch.queries_for, fetch or fetch_articles
    for m in due(db, last_fetch, time.time() if now is None else now):
        started = time.time() if now is None else now
        last_fetch[m["id"]] = started
        try:
            if not m["queries"]:
                store.set_queries(db, m["id"], await queries_for(m["title"], m["rules"]))
                m = store.get_market(db, m["id"])
            first = not m["filled"]
            if first:
                bus.publish("market", {"market_id": m["id"], "status": "finding sources"})
            n = await fetch(db, bus, scorer, m, backfill=first, num_results=20 if first else 10)
            if first:
                store.set_filled(db, m["id"])
                bus.publish("market", {"market_id": m["id"], "status": "ready", "ticks": n})
        except Exception as e:
            log.warning("article pass failed for %s, retrying in %ss: %s", m["id"], RETRY_SECONDS, e)
            last_fetch[m["id"]] = started - m["poll_seconds"] + RETRY_SECONDS


async def article_loop(db, bus, scorer, wake: asyncio.Event) -> None:
    """Run article passes forever. `wake` starts the next pass at once, for a newly added market."""
    last_fetch: dict[str, float] = {}
    while True:
        try:
            await article_pass(db, bus, scorer, last_fetch)
        except Exception:
            log.exception("article pass failed")
        try:
            await asyncio.wait_for(wake.wait(), 15)
        except asyncio.TimeoutError:
            pass
        wake.clear()
