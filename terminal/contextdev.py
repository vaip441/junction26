"""Context.dev: web search and page scrape. Failures raise ContextError; callers decide what to do."""
import asyncio
import logging
import os
import time
from collections import deque
from datetime import UTC, datetime

import httpx

API = "https://api.context.dev/v1"
log = logging.getLogger(__name__)
_client: httpx.AsyncClient | None = None
_limiter = None


class ContextError(Exception):
    pass


class Limiter:
    """Sliding one-minute window per API key. Context.dev refuses more than `per_minute` requests a key."""

    def __init__(self, keys: list[str], per_minute: int):
        self.per_minute = per_minute
        self.used = {k: deque() for k in keys}       # request times within the last minute
        self.blocked = {k: 0.0 for k in keys}        # do not use a key before this time

    def _free(self, key: str, now: float, reserve: int = 0) -> bool:
        used = self.used[key]
        while used and used[0] <= now - 60:
            used.popleft()
        return now >= self.blocked[key] and len(used) < self.per_minute - reserve

    def try_take(self, now: float | None = None, reserve: int = 0) -> str | None:
        """A key with capacity right now (and count the request against it), else None.

        `reserve` leaves that many requests a minute untouched, for callers that must not starve others.
        """
        now = time.monotonic() if now is None else now
        for key in self.used:
            if self._free(key, now, reserve):
                self.used[key].append(now)
                return key
        return None

    def wait_time(self, now: float | None = None) -> float:
        """Seconds until some key has capacity."""
        now = time.monotonic() if now is None else now
        return max(0.0, min(max(self.blocked[k], u[0] + 60 if len(u) >= self.per_minute else now) - now
                            for k, u in self.used.items()))

    def refused(self, key: str, retry_after: float, now: float | None = None) -> None:
        self.blocked[key] = (time.monotonic() if now is None else now) + retry_after

    async def take(self) -> str:
        while (key := self.try_take()) is None:
            await asyncio.sleep(self.wait_time() + 0.05)
        return key


def limiter() -> Limiter:
    """CONTEXT_DEV_API_KEY may hold several comma-separated keys; each has its own per-minute allowance."""
    global _limiter
    if _limiter is None:
        keys = [k.strip() for k in os.environ["CONTEXT_DEV_API_KEY"].split(",") if k.strip()]
        _limiter = Limiter(keys, int(os.environ.get("CONTEXT_DEV_RPM", "10")))
    return _limiter


async def _post(path: str, body: dict, key: str) -> dict:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=60)
    try:
        r = await _client.post(API + path, json=body, headers={"Authorization": f"Bearer {key}"})
        if r.status_code == 429:
            limiter().refused(key, float(r.headers.get("retry-after", 30)))
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise ContextError(f"{path}: {type(e).__name__}: {str(e)[:150]}") from e


def parse_search(response: dict) -> list[dict]:
    return [{"url": r["url"], "title": r["title"], "description": r.get("description") or ""}
            for r in response.get("results") or []
            if r.get("title") and str(r.get("url") or "").startswith(("https://", "http://"))]  # shown as links


def parse_scrape(response: dict) -> tuple[str, float | None]:
    """(main text as markdown, publish time as unix seconds or None)."""
    text = (response.get("markdown") or {}).get("data") or ""
    try:
        d = datetime.fromisoformat((response.get("metadata") or {})["publishedTime"])
        published = (d if d.tzinfo else d.replace(tzinfo=UTC)).timestamp()  # a bare date is taken as UTC
    except (KeyError, TypeError, ValueError):
        published = None
    return text, published


async def search(query: str, *, freshness: str = "last_24_hours", include_domains: list[str] | None = None,
                 num_results: int = 10) -> list[dict]:
    body = {"query": query[:500], "freshness": freshness, "numResults": num_results}
    if include_domains:
        body["includeDomains"] = include_domains
    return parse_search(await _post("/web/search", body, await limiter().take()))  # searches queue for capacity


async def scrape(url: str) -> tuple[str, float | None]:
    """Text and publish time of a page, or nothing when there is no spare capacity: searches come first."""
    key = limiter().try_take(reserve=limiter().per_minute // 2)
    if key is None:
        return "", None
    return parse_scrape(await _post("/web/scrape", {"url": url, "formats": {"markdown": True},
                                                    "sharedParams": {"mainContentOnly": True}}, key))
