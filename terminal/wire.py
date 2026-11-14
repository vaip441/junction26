"""Our own demo newsroom as a source: the article list of a site the team runs, read every couple of seconds,
so an article published during the demo is on the tape at once.

We write those articles ourselves, so each tick is flagged as a test: scored and shown, never counted in the
weekend record, never told to the scorer as already reported.
"""
import asyncio
import logging
import time
from datetime import datetime
from urllib.parse import urljoin, urlsplit

import httpx

from terminal import db as store
from terminal import posts
from terminal.pipeline import ingest
from terminal.poller import forever

log = logging.getLogger(__name__)
_client: httpx.AsyncClient | None = None


def parse(data, feed: str) -> list[dict]:
    """The feed's articles as {"slug", "url", "headline", "body", "published"}. One that cannot be read, or
    whose address is not on the feed's own site, is left out."""
    found = []
    for a in (data.get("articles") if isinstance(data, dict) else None) or []:
        try:
            url, body = urljoin(feed, a["url"]), a.get("body") or []
            if urlsplit(url).netloc != urlsplit(feed).netloc or not isinstance(a["headline"], str):
                continue
            found.append({"slug": str(a["slug"]), "url": url, "headline": a["headline"],
                          "published": datetime.fromisoformat(a["published"]).timestamp(),
                          "body": "\n".join(p for p in [a.get("dek"), *(body if isinstance(body, list) else [body])]
                                            if isinstance(p, str))})
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return found


async def fetch(feed: str) -> list[dict]:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=5, headers={"User-Agent": posts.UA})
    r = await _client.get(feed)
    r.raise_for_status()
    return parse(r.json(), feed)


async def ingest_article(db, bus, scorer, a: dict, source: str, now: float | None = None) -> int:
    """Score an article for every polled market whose queries it shares a word with, all at once: someone is
    watching the tape. Returns the ticks stored; an article already stored for a market is skipped there."""
    now = time.time() if now is None else now
    ticks = await asyncio.gather(*(
        ingest(db, bus, scorer, m, kind="article", source=source, headline=a["headline"], url=a["url"], body=a["body"],
               published_ts=a["published"], test=True, now=now)
        for m in store.list_markets(db)
        if m["poll_seconds"] > 0 and posts.shares_words(f"{a['headline']} {a['body']}", m["queries"])))
    return sum(t is not None for t in ticks)


async def wire_loop(db, bus, scorer, feed: str, interval: float = 2, read=None) -> None:
    """Follow the feed. What is on it when the service starts is not news; everything after is offered on
    every pass, which scores it once (a stored article is skipped) and tries a failed scoring again.

    shortcut: an article published while the service is down counts as one that was already there; score the
    first read as history if that starts to matter.
    """
    there: set[str] | None = None
    source = urlsplit(feed).netloc

    async def step() -> None:
        nonlocal there
        found = await (read or fetch)(feed)
        if there is None:
            there = {a["slug"] for a in found}
            return
        for a in found:
            if a["slug"] not in there:
                await ingest_article(db, bus, scorer, a, source)

    await forever("wire feed", interval, step)
