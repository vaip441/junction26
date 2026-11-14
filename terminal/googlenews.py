"""Google News as a way to find stories early: its search feed lists an article minutes after it is
published, where the web search is hours behind. It gives the headline, the publisher and the time only;
the address is Google's link to the article, not the article's own."""
import logging
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx

log = logging.getLogger(__name__)
FEED = "https://news.google.com/rss/search"
MAX_ITEMS = 20  # a feed holds up to a hundred stories; the newest are what the web search lacks


def parse(xml: str) -> list[dict]:
    """The newest stories of a feed, shaped like search results plus publisher and publish time."""
    out = []
    for item in ElementTree.fromstring(xml).iter("item"):
        source, title, link = item.find("source"), (item.findtext("title") or "").strip(), item.findtext("link") or ""
        host = urlsplit(source.get("url") or "").netloc.lower().removeprefix("www.") if source is not None else ""
        if not (title and host and link.startswith("https://")):
            continue
        title = title.removesuffix(f" - {(source.text or '').strip()}")  # Google appends the publisher's name
        try:
            published = parsedate_to_datetime(item.findtext("pubDate")).timestamp()
        except (TypeError, ValueError):
            published = None
        out.append({"url": link, "title": title, "description": "", "text": "", "source": host, "published": published})
    return sorted(out, key=lambda r: -(r["published"] or 0))[:MAX_ITEMS]


async def _get(params: dict) -> str:
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) terminal/0.1"},
                                 follow_redirects=True) as c:
        r = await c.get(FEED, params=params)
        r.raise_for_status()
        return r.text


MAX_AGE = 2 * 3600


async def search(query: str, now: float | None = None) -> list[dict]:
    """Stories of the last two hours matching a query, newest first. Freshness is this source's whole job:
    asked for a day, it sent 87 stories an hour with a median age near seven hours, each one a scoring call."""
    oldest = (time.time() if now is None else now) - MAX_AGE
    rows = parse(await _get({"q": f"{query} when:2h", "hl": "en-US", "gl": "US", "ceid": "US:en"}))
    return [r for r in rows if r["published"] and r["published"] >= oldest]  # Google's own filter is not exact
