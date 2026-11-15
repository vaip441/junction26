"""The httpx client each outside service is reached through."""
import asyncio

import httpx


def client(timeout: float, **options):
    """A function returning one shared client, made again on a new event loop or once closed.

    `options` go to httpx.AsyncClient as they are: headers, follow_redirects, limits.
    """
    made: tuple[httpx.AsyncClient, asyncio.AbstractEventLoop] | None = None

    def get() -> httpx.AsyncClient:
        nonlocal made
        loop = asyncio.get_running_loop()
        if made is None or made[1] is not loop or made[0].is_closed:
            made = (httpx.AsyncClient(timeout=timeout, **options), loop)
        return made[0]

    return get
