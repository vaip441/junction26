"""Kalshi and Polymarket behind one interface. The clients block, so they run in worker threads."""
import asyncio
import logging

from terminal.venues import kalshi, polymarket
from terminal.venues.errors import MarketNotFound, NotAVenueLink, VenueError

__all__ = ["MarketNotFound", "NotAVenueLink", "VenueError", "current_price", "history", "market_id", "resolve", "resolved"]

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


async def resolved(market: dict) -> bool:
    """Whether the venue has resolved the market. Raises on a venue failure: not knowing is not a yes."""
    client = polymarket if market["venue"] == "polymarket" else kalshi
    return await asyncio.to_thread(client.resolved, market["venue_ref"])


async def history(market: dict) -> list[tuple[float, float]]:
    """(unix seconds, percent) for the last week, oldest first. Empty when the venue has none or fails:
    history only fills in the chart, so a market is tracked with or without it."""
    client = polymarket if market["venue"] == "polymarket" else kalshi
    try:
        return await asyncio.to_thread(client.history, market["venue_ref"])
    except Exception as e:
        log.warning("no price history for %s: %s: %s", market.get("id"), type(e).__name__, str(e)[:150])
        return []
