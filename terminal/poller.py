"""Background loops: price sampling, article polling, instant fill."""
import asyncio
import logging
import time

from terminal import db as store
from terminal import venues

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
