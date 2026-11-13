"""Kalshi and Polymarket behind one interface. The clients block, so they run in worker threads."""
import asyncio
import logging

from terminal.venues import kalshi, polymarket
from terminal.venues.errors import MarketNotFound, NotAVenueLink, VenueError

__all__ = ["MarketNotFound", "NotAVenueLink", "VenueError", "current_price", "market_id", "resolve"]

log = logging.getLogger(__name__)


async def resolve(link: str) -> list[dict]:
    """Contracts behind a market link, lead first.

    NotAVenueLink, MarketNotFound, or VenueError when the venue is down or answers unexpectedly.
    """
    try:
        if (ticker := kalshi.parse_link(link)) is not None:
            contracts = await asyncio.to_thread(kalshi.lookup, ticker, kalshi.canonical(link))
        elif (slugs := polymarket.parse_link(link)) is not None:
            contracts = await asyncio.to_thread(polymarket.lookup, *slugs)
        else:
            raise NotAVenueLink("not a Kalshi or Polymarket market link")
    except (NotAVenueLink, MarketNotFound):
        raise
    except Exception as e:
        raise VenueError(f"{type(e).__name__}: {str(e)[:150]}") from e
    if not contracts:
        raise MarketNotFound("market not found or already closed")
    return contracts


def market_id(contract: dict) -> str:
    return f"pm-{contract['slug']}" if contract["venue"] == "polymarket" else f"k-{contract['venue_ref']}"


async def current_price(market: dict) -> float | None:
    """Latest price in percent; None when the venue has no usable price. Raises on a venue failure."""
    client = polymarket if market["venue"] == "polymarket" else kalshi
    return await asyncio.to_thread(client.current_price, market["venue_ref"])
