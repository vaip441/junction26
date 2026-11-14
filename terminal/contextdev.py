"""Context.dev: web search and page scrape over a pool of API keys.

Each key (account) is limited to a number of requests a minute, so capacity is added by adding keys:
CONTEXT_DEV_API_KEY=key1,key2,key3. Requests are spread evenly, a key the server refuses is rested and
the request goes out on the next one. Failures raise ContextError; callers decide what to do.
"""
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


class Refused(ContextError):
    """The server turned this key away (rate limit, bad key, no credits). Another key may still work."""


REST_SECONDS = 600  # a key that is invalid or out of credits is left alone this long before it is tried again


class Limiter:
    """Sliding one-minute window per API key. Context.dev refuses more than `per_minute` requests a key."""

    def __init__(self, keys: list[str], per_minute: int):
        keys = list(dict.fromkeys(keys))             # the same key twice is still one allowance
        self.per_minute = per_minute
        self.used = {k: deque() for k in keys}       # request times within the last minute
        self.blocked = {k: 0.0 for k in keys}        # do not use a key before this time
        self.credits = {k: None for k in keys}       # credits left, as last reported by the server

    def _free(self, key: str, now: float, reserve: int = 0) -> bool:
        used = self.used[key]
        while used and used[0] <= now - 60:
            used.popleft()
        return now >= self.blocked[key] and len(used) < max(1, self.per_minute - reserve)

    def try_take(self, now: float | None = None, reserve: int = 0) -> str | None:
        """A key with capacity right now (and count the request against it), else None.

        `reserve` leaves that many requests a minute untouched, for callers that must not starve others.
        """
        now = time.monotonic() if now is None else now
        free = [k for k in self.used if self._free(k, now, reserve)]
        if not free:
            return None
        key = min(free, key=lambda k: len(self.used[k]))  # least used this minute: accounts drain evenly
        self.used[key].append(now)
        return key

    def wait_time(self, now: float | None = None, reserve: int = 0) -> float:
        """Seconds until some key has capacity beyond the reserve."""
        now = time.monotonic() if now is None else now
        cap = max(1, self.per_minute - reserve)
        return max(0.0, min(max(self.blocked[k], u[len(u) - cap] + 60 if len(u) >= cap else now) - now
                            for k, u in self.used.items()))

    def refused(self, key: str, retry_after: float, now: float | None = None) -> None:
        self.blocked[key] = (time.monotonic() if now is None else now) + retry_after

    def status(self, now: float | None = None) -> list[dict]:
        """Per key, numbered from 1 (the keys themselves are never shown)."""
        now = time.monotonic() if now is None else now
        out = []
        for i, key in enumerate(self.used, 1):
            self._free(key, now)  # drops requests older than a minute
            out.append({"key": i, "used_last_minute": len(self.used[key]), "per_minute": self.per_minute,
                        "resting_seconds": round(max(0.0, self.blocked[key] - now)),
                        "credits_remaining": self.credits[key]})
        return out

    async def take(self, reserve: int = 0) -> str:
        while (key := self.try_take(reserve=reserve)) is None:
            await asyncio.sleep(self.wait_time(reserve=reserve) + 0.05)
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
    lim = limiter()
    try:
        r = await _client.post(API + path, json=body, headers={"Authorization": f"Bearer {key}"})
        if r.status_code in (401, 402, 403, 429):
            rest = float(r.headers.get("retry-after", 30)) if r.status_code == 429 else REST_SECONDS
            lim.refused(key, rest)
            number = list(lim.used).index(key) + 1
            log.warning("Context.dev key %d refused with HTTP %d; resting it %.0fs", number, r.status_code, rest)
            raise Refused(f"{path}: key {number} refused with HTTP {r.status_code}")
        r.raise_for_status()
        data = r.json()
        lim.credits[key] = (data.get("key_metadata") or {}).get("credits_remaining", lim.credits[key])
        return data
    except (httpx.HTTPError, ValueError) as e:
        raise ContextError(f"{path}: {type(e).__name__}: {str(e)[:150]}") from e


async def _call(path: str, body: dict, *, wait: bool, reserve: int = 0) -> dict | None:
    """Send on a key with capacity; if the server refuses that key, try the others once each.

    wait=True queues until some key has capacity. wait=False returns None when none has any to spare.
    """
    lim, last = limiter(), None
    for _ in range(len(lim.used)):
        key = await lim.take(reserve) if wait else lim.try_take(reserve=reserve)
        if key is None:
            return None
        try:
            return await _post(path, body, key)
        except Refused as e:
            last = e
    raise last


def status() -> dict:
    """Capacity and use across the key pool, for GET /status."""
    try:
        keys = limiter().status()
    except KeyError:  # no key configured
        keys = []
    return {"keys": keys, "per_minute": sum(k["per_minute"] for k in keys),
            "used_last_minute": sum(k["used_last_minute"] for k in keys)}


def parse_search(response: dict) -> list[dict]:
    return [{"url": r["url"], "title": r["title"], "description": r.get("description") or "",
             "text": "\n".join((r.get("highlights") or {}).get("highlights") or [])}  # passages relevant to the query
            for r in response.get("results") or []
            if r.get("title") and str(r.get("url") or "").startswith(("https://", "http://"))]  # shown as links


def _published(metadata: dict | None) -> float | None:
    """A page's publish time as unix seconds, or None."""
    try:
        d = datetime.fromisoformat((metadata or {})["publishedTime"])
        published = (d if d.tzinfo else d.replace(tzinfo=UTC)).timestamp()  # a bare date is taken as UTC
        if not 946684800 <= published <= time.time() + 86400:  # pages can claim any date: keep 2000..tomorrow
            published = None
    except (KeyError, TypeError, ValueError, OverflowError):
        published = None
    return published


def parse_scrape(response: dict) -> tuple[str, float | None]:
    """(main text as markdown, publish time as unix seconds or None)."""
    return (response.get("markdown") or {}).get("data") or "", _published(response.get("metadata"))


BATCH_POLL_SECONDS, BATCH_WAIT_SECONDS = 5, 600
_batch_turn = 0


async def published_times(urls: list[str]) -> dict[str, float | None]:
    """Publish time (or None) of each page that could be read, through one batch scrape.

    A batch takes about a minute, costs 1 credit per page read, and has its own rate limit, so it takes
    nothing from the searches. Keys take turns.
    """
    global _client, _batch_turn
    if _client is None:
        _client = httpx.AsyncClient(timeout=60)
    keys = list(limiter().used)
    headers = {"Authorization": f"Bearer {keys[_batch_turn % len(keys)]}"}
    _batch_turn += 1
    try:
        r = await _client.post(API + "/batch/submit", headers=headers, json={
            "input": {"mode": "scrape", "data": {"format": "markdown", "urls": [{"url": u} for u in urls]}}})
        r.raise_for_status()
        id, deadline = r.json()["id"], time.monotonic() + BATCH_WAIT_SECONDS
        while True:
            r = await _client.get(f"{API}/batch/{id}", headers=headers)
            r.raise_for_status()
            status = r.json().get("status")
            if status not in ("pending", "queued", "running"):
                break
            if time.monotonic() > deadline:
                raise ContextError(f"batch {id} did not finish in {BATCH_WAIT_SECONDS}s")
            await asyncio.sleep(BATCH_POLL_SECONDS)
        if status != "completed":
            raise ContextError(f"batch {id} ended as {status}")
        out, cursor = {}, None
        while True:
            r = await _client.get(f"{API}/batch/{id}/results", headers=headers,
                                  params={"limit": 100, **({"cursor": cursor} if cursor else {})})
            r.raise_for_status()
            page = r.json()
            for d in page.get("data") or []:
                if d.get("status") == "ok" and d.get("url"):
                    out[d["url"]] = _published(d.get("metadata"))
            cursor = page.get("next_cursor")
            if not page.get("has_more") or not cursor:
                return out
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
        raise ContextError(f"batch: {type(e).__name__}: {str(e)[:150]}") from e


async def search(query: str, *, freshness: str | None = "last_24_hours", include_domains: list[str] | None = None,
                 exclude_domains: list[str] | None = None, num_results: int = 10, reserve: int = 0) -> list[dict]:
    """Search results with the passages of each page that are relevant to the query (one request, 2 credits).

    Background callers pass `reserve` to leave that many requests a minute per key for a person asking.
    """
    body = {"query": query[:500], "numResults": num_results, "highlightsOptions": {"enabled": True}}
    if freshness:
        body["freshness"] = freshness
    if include_domains:
        body["includeDomains"] = include_domains
    if exclude_domains:
        body["excludeDomains"] = exclude_domains
    return parse_search(await _call("/web/search", body, wait=True, reserve=reserve))  # searches queue for capacity


def parse_news(response: dict) -> list[dict]:
    """Articles of the news index, shaped like search results plus the time each was published."""
    out = []
    for a in response.get("data") or []:
        if a.get("title") and str(a.get("url") or "").startswith(("https://", "http://")):
            published = _published({"publishedTime": a.get("published_at")})
            out.append({"url": a["url"], "title": a["title"], "description": a.get("description") or "", "text": "",
                        # some publishers' clocks run an hour ahead: nothing was published after now
                        "published": published and min(published, time.time())})
    return out


async def news(company: str, *, since: float, limit: int = 25, reserve: int = 0) -> list[dict]:
    """The newest articles about a company since a time, newest first (one request, 3 credits).

    Measured on 14 Nov: for Nvidia the newest was 5 minutes old and all 25 under 90 minutes, where the web
    search returns pages from anywhere in the last day. The index knows companies only: for people, countries
    and public bodies it was weeks behind.
    """
    body = {"searchBy": {"type": "entity", "entity": {"type": "name", "name": company}}, "limit": limit,
            "filterBy": {"articleLanguage": ["en"], "date": {"from": int(since * 1000)}}}
    return parse_news(await _call("/news/search", body, wait=True, reserve=reserve))


async def scrape(url: str) -> tuple[str, float | None]:
    """Text and publish time of a page, or nothing when there is no spare capacity: searches come first."""
    data = await _call("/web/scrape", {"url": url, "formats": {"markdown": True},
                                       "sharedParams": {"mainContentOnly": True}},
                       wait=False, reserve=limiter().per_minute // 2)
    return ("", None) if data is None else parse_scrape(data)
