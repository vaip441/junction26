"""Kalshi and Polymarket behind one interface. The clients block, so they run in worker threads."""
import asyncio
import logging

from terminal.venues import kalshi, polymarket

log = logging.getLogger(__name__)


async def resolve(link: str) -> list[dict]:
    """Contracts behind a market link, lead first.

    ValueError if it is not a venue link, LookupError if the venue has no open market there.
    """
    if (ticker := kalshi.parse_link(link)) is not None:
        contracts = await asyncio.to_thread(kalshi.lookup, ticker, link.strip())
    elif (slugs := polymarket.parse_link(link)) is not None:
        contracts = await asyncio.to_thread(polymarket.lookup, *slugs)
    else:
        raise ValueError("not a Kalshi or Polymarket market link")
    if not contracts:
        raise LookupError("market not found or already closed")
    return contracts


def market_id(contract: dict) -> str:
    return f"pm-{contract['slug']}" if contract["venue"] == "polymarket" else f"k-{contract['venue_ref']}"


async def current_price(market: dict) -> float | None:
    """Latest price in percent, or None on any failure."""
    client = polymarket if market["venue"] == "polymarket" else kalshi
    try:
        return await asyncio.to_thread(client.current_price, market["venue_ref"])
    except Exception as e:  # a venue hiccup must never stop the sampling loop
        log.warning("no price for %s: %s", market["id"], e)
        return None
