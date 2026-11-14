"""X and Reddit posts: what is known about one beyond its search result, and which ones are trash."""
import html
import logging
import re
import time
from datetime import datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx

log = logging.getLogger(__name__)
UA = "Mozilla/5.0 (X11; Linux x86_64) terminal/0.1"


def parse_x(data: dict) -> dict | None:
    if data.get("__typename") != "Tweet":
        return None  # deleted or withheld
    return {"handle": data["user"]["screen_name"], "text": data.get("text") or "",
            "likes": data.get("favorite_count") or 0, "replies": data.get("conversation_count") or 0,
            "is_reply": bool(data.get("in_reply_to_status_id_str"))}


async def x_post(url: str) -> dict | None:
    """Author, text, likes and replies of a post on X; None when they cannot be had, and the post is then
    judged as before, on its search result alone.

    shortcut: this is the endpoint X serves embedded posts from, with no key and no stated limit;
    move to X's paid API if it starts refusing or live X becomes the point of the product.
    """
    m = re.search(r"/status/(\d+)", url)
    if not m:
        return None
    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": UA}) as c:
            r = await c.get("https://cdn.syndication.twimg.com/tweet-result", params={"id": m[1], "token": "a"})
            r.raise_for_status()
            return parse_x(r.json())
    except Exception as e:
        log.warning("X lookup failed for %s: %s: %s", url, type(e).__name__, str(e)[:100])
        return None


# Measured on 14 Nov over the last 40 posts found: the 5 worth showing had 158 to 13,084 likes; the trash
# was two replies (7 and 12 likes), a bare link (3) and a thread fragment (0).
MIN_LIKES, YOUNG_SECONDS = 20, 3600


def x_trash(post: dict, age: float | None) -> bool:
    """A reply, a post that is only links and mentions, or one that is past its first hour with few likes."""
    said = re.sub(r"https?://\S+|@\w+", " ", post["text"]).split()
    young = age is not None and age <= YOUNG_SECONDS  # too new to have been liked yet
    return post["is_reply"] or len(said) < 3 or (post["likes"] < MIN_LIKES and not young)


NOT_A_POST = re.compile(r"\b(daily|weekly|monthly)\b.*\b(thread|discussion|chat)\b|megathread"
                        r"|^\W*(removed|deleted)\b", re.I)


def reddit_trash(url: str, title: str) -> bool:
    """A listing page, a recurring discussion thread, or a post that was removed."""
    return "/comments/" not in urlsplit(url).path or bool(NOT_A_POST.search(title))


ATOM = {"a": "http://www.w3.org/2005/Atom"}


def parse_feed(xml: str) -> list[dict]:
    """Posts of a subreddit's Atom feed, shaped like search results plus the time each was posted."""
    out = []
    for e in ElementTree.fromstring(xml).findall("a:entry", ATOM):
        body = re.sub(r"<[^>]+>", " ", e.findtext("a:content", "", ATOM))
        body = html.unescape(re.split(r"submitted by\s", body)[0])  # the rest is the author and link footer
        when = e.findtext("a:published", None, ATOM)
        out.append({"url": e.find("a:link", ATOM).get("href"), "title": e.findtext("a:title", "", ATOM).strip(),
                    "description": " ".join(body.split())[:2000],
                    "published": datetime.fromisoformat(when).timestamp() if when else None})
    return out


async def _get_feed(sub: str) -> str:
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": UA}, follow_redirects=True) as c:
        r = await c.get(f"https://www.reddit.com/r/{sub}/new/.rss", params={"limit": 25})
        r.raise_for_status()
        return r.text


# Measured on 14 Nov: Reddit answers a client that is not logged in once every 30 seconds or so and
# refuses the rest. So reads are spaced, and each feed is kept for five minutes.
FEED_SPACING, FEED_FRESH = 32, 300
_feeds: dict[str, tuple[float, list[dict]]] = {}
_next_feed = 0.0


async def subreddit_new(sub: str, *, fetch=None, now: float | None = None) -> list[dict]:
    """The newest posts of a subreddit. Never waits: when it is not this feed's turn to be read, the
    caller gets what was read last (nothing, the first time) and the feed is read on a later call."""
    global _next_feed
    now = time.time() if now is None else now
    at, found = _feeds.get(sub, (0.0, []))
    if now - at < FEED_FRESH or now < _next_feed or not re.fullmatch(r"\w{2,21}", sub):
        return found
    _next_feed = now + FEED_SPACING  # taken before the read, so calls made meanwhile do not read too
    try:
        found = parse_feed(await (fetch or _get_feed)(sub))
    except Exception as e:
        log.warning("could not read r/%s: %s: %s", sub, type(e).__name__, str(e)[:100])
    _feeds[sub] = (now, found)  # also after a failure: a feed that is gone is tried again in five minutes
    return found


FILLER = set("the and for with from that this will who what when how are was has have not but its "
             "news latest update updates new next before after about into over than you your".split())


def _words(text: str) -> set[str]:
    return {w.removesuffix("s") for w in re.findall(r"[^\W_]{3,}", text.casefold()) if not w.isdigit()} - FILLER


def shares_words(text: str, queries: list[str]) -> bool:
    """Whether a post from a feed is worth a scoring call: it names something the market's queries name."""
    return bool(_words(text) & _words(" ".join(queries)))
