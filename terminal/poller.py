"""Background loops: price sampling, article polling, instant fill."""
import asyncio
import logging
import time
from urllib.parse import urlsplit

from terminal import contextdev, venues
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


async def fetch_articles(db, bus, scorer, market: dict, *, backfill: bool, num_results: int,
                         search=None, scrape=None) -> int:
    """Search every query of a market and ingest results not seen before. Returns how many ticks were stored."""
    search, scrape = search or contextdev.search, scrape or contextdev.scrape
    found = await asyncio.gather(*(search(q, num_results=num_results) for q in market["queries"]),
                                 return_exceptions=True)
    fresh = {}
    for q, results in zip(market["queries"], found):
        if isinstance(results, BaseException):
            log.warning("search failed for %r on %s: %s", q, market["id"], results)
            continue
        for r in results:
            key = dedupe_key("article", r["url"], r["title"], 0)
            if key not in fresh and not store.has_tick(db, market["id"], key):
                fresh[key] = r
    limit = asyncio.Semaphore(10)

    async def one(r) -> bool:
        async with limit:
            try:
                text, published = await scrape(r["url"])  # 1 credit: full text scores better and carries the date
            except Exception as e:
                log.warning("scrape failed for %s: %s", r["url"], e)
                text, published = "", None
            host = urlsplit(r["url"]).netloc.lower().removeprefix("www.")
            tick = await ingest(db, bus, scorer, market, kind="article", source=host, headline=r["title"],
                                url=r["url"], body=text or r["description"], published_ts=published, backfill=backfill)
            return tick is not None

    return sum(await asyncio.gather(*(one(r) for r in fresh.values())))


def due(db, last_fetch: dict, now: float) -> list[dict]:
    """Lead markets with search queries whose polling interval has passed."""
    return [m for m in store.list_markets(db)
            if m["queries"] and now - last_fetch.get(m["id"], 0) >= m["poll_seconds"]]


async def article_loop(db, bus, scorer) -> None:
    last_fetch: dict[str, float] = {}

    async def step():
        for m in due(db, last_fetch, time.time()):
            last_fetch[m["id"]] = time.time()
            try:
                await fetch_articles(db, bus, scorer, m, backfill=False, num_results=10)
            except Exception:
                log.exception("article fetch failed for %s", m["id"])

    await forever("article", 15, step)
