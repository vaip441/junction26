"""X, Reddit and Bluesky posts: what is known about one beyond its search result, and which ones are trash."""
import html
import logging
import re
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx

import asyncio

log = logging.getLogger(__name__)
UA = "Mozilla/5.0 (X11; Linux x86_64) terminal/0.1"
_client: tuple[httpx.AsyncClient, asyncio.AbstractEventLoop] | None = None


def _http() -> httpx.AsyncClient:
    global _client
    loop = asyncio.get_running_loop()
    if _client is None or _client[1] is not loop or _client[0].is_closed:
        _client = (httpx.AsyncClient(timeout=10, headers={"User-Agent": UA}, follow_redirects=True,
                                     limits=httpx.Limits(max_connections=100, max_keepalive_connections=30)), loop)
    return _client[0]


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
        r = await _http().get("https://cdn.syndication.twimg.com/tweet-result", params={"id": m[1], "token": "a"})
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


MIN_WORDS = 8
ADVERT = re.compile(r"\d[\d.,]*\s*USD\b|https?://", re.I)


def comment_trash(comment: dict) -> bool:
    """A comment under a venue's market that is a reply, was reported, is too short to say anything, or is an
    advert: the bots that track positions quote a sum in USD, the rest carry a link.
    Measured on 14 Nov over 291 Polymarket comments: 70 were left for the scorer."""
    return (comment["is_reply"] or bool(comment["reports"]) or len(comment["text"].split()) < MIN_WORDS
            or bool(ADVERT.search(comment["text"])))


BLUESKY = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
CLOCK_SLACK = 300  # seconds a post's own time may differ from the time the network received it


def _utc(text: str) -> float:
    d = datetime.fromisoformat(text)
    return (d if d.tzinfo else d.replace(tzinfo=UTC)).timestamp()


def parse_bluesky(data: dict) -> list[dict]:
    """The posts of a Bluesky search, each whole: who, when, the text, how many liked and answered it.
    A post states its own time, so one that arrived at another time than it claims is left out."""
    out = []
    for p in data.get("posts") or []:
        try:
            handle, record = p["author"]["handle"], p["record"]
            published = _utc(record["createdAt"])
            if abs(_utc(p["indexedAt"]) - published) > CLOCK_SLACK:
                continue
            out.append({"url": f"https://bsky.app/profile/{handle}/post/{p['uri'].rsplit('/', 1)[1]}", "handle": handle,
                        "text": " ".join(record["text"].split()), "is_reply": "reply" in record,
                        "likes": int(p.get("likeCount") or 0), "replies": int(p.get("replyCount") or 0),
                        "published": published})
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            continue
    return out


def bluesky_worth(post: dict) -> bool:
    """Not a reply, liked by a few people, and long enough to say something. One that fails is passed
    over, not stored as trash: an hour later people may have liked it."""
    said = re.sub(r"https?://\S+|@[\w.]+", " ", post["text"]).split()
    return not post["is_reply"] and post["likes"] >= MIN_LIKES and len(said) >= MIN_WORDS


async def bluesky(query: str, since: float, until: float | None = None, limit: int = 25) -> list[dict]:
    """The most-liked Bluesky posts of a stretch of time that hold every word of a query. Its search
    needs no login, takes a time window, and a post cannot be edited afterwards."""
    iso = lambda ts: datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {"q": query[:200], "since": iso(since), "sort": "top", "limit": limit, "lang": "en"}
    if until is not None:
        params["until"] = iso(until)
    r = await _http().get(BLUESKY, params=params)
    r.raise_for_status()
    return parse_bluesky(r.json())


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
    r = await _http().get(f"https://www.reddit.com/r/{sub}/new/.rss", params={"limit": 25})
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
