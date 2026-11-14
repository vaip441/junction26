"""Polymarket public (no-login) endpoints. get() is copied from ~/weather-mm/weather_mm/pm.py."""
import json
import re
import time
from datetime import datetime
import urllib.error
import urllib.parse
import urllib.request

from terminal.venues.errors import MarketNotFound

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
UA = {"User-Agent": "terminal"}  # urllib's default agent gets blocked by some Cloudflare setups
SLUG = re.compile(r"^[a-z0-9-]{1,200}$")


def get(url, **params):
    """GET JSON with retries on rate limits, 5xx and network errors."""
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url += f"?{q}" if q else ""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                body = r.read()
                return json.loads(body) if body.strip() else None
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(min(30, 2**attempt))
    raise RuntimeError(f"giving up on {url}")


def parse_link(url: str) -> tuple[str, str | None] | None:
    """(event slug, market slug or None) from a polymarket.com/event/... address."""
    u = urllib.parse.urlsplit(url.strip())
    parts = [p for p in u.path.split("/") if p]
    if (u.scheme.lower() not in ("http", "https") or u.netloc.lower().removeprefix("www.") != "polymarket.com"
            or len(parts) < 2 or parts[0] != "event"):
        return None
    if not all(SLUG.match(p) for p in parts[1:3]):
        return None
    return parts[1], parts[2] if len(parts) > 2 else None


def search(words: str, limit: int = 10) -> list[str]:
    """Slugs of open events matching plain words, best first: Polymarket's own search. It knows markets
    listed today, which a web search engine has not indexed yet."""
    data = get(GAMMA + "/public-search", q=words[:200], events_status="active", limit_per_type=limit) or {}
    return [e["slug"] for e in data.get("events") or []
            if not e.get("closed") and SLUG.match(str(e.get("slug") or ""))]


WALLET = re.compile(r"0x[0-9a-fA-F]{40}")
_event_ids: dict[str, str] = {}  # event slug -> its number, which its comments are filed under


def comments(slug: str, limit: int = 40) -> list[dict]:
    """The newest comments under an event, newest first: what its traders are saying. Rows without text or a
    time are left out; an event Polymarket does not know has none."""
    if slug not in _event_ids:
        events = get(GAMMA + "/events", slug=slug) or []
        if not events:
            return []
        _event_ids[slug] = str(events[0]["id"])
    rows = get(GAMMA + "/comments", parent_entity_type="Event", parent_entity_id=_event_ids[slug], limit=limit,
               order="createdAt", ascending="false") or []
    out = []
    for c in rows:
        try:
            profile = c.get("profile") or {}
            name = str(profile.get("name") or "")
            if not name or WALLET.match(name):  # an account that chose no name is shown by its wallet address
                name = str(profile.get("pseudonym") or "trader")
            out.append({"id": str(c["id"]), "text": c["body"] + "", "is_reply": bool(c.get("parentCommentID")),
                        "author": name,
                        "likes": int(c.get("reactionCount") or 0), "reports": int(c.get("reportCount") or 0),
                        "published": datetime.fromisoformat(c["createdAt"].replace("Z", "+00:00")).timestamp()})
        except (AttributeError, KeyError, TypeError, ValueError):
            continue  # not a comment, or one with no text or time
    return out


def parse_event(event: dict, market_slug: str | None) -> list[dict]:
    """Open contracts of an event: the named market first, then the most undecided (nearest 50%)."""
    out = []
    # contracts that take no orders and never traded are placeholders ("Candidate S"): keep one only if
    # it was asked for by name. A market listed today has no trades yet but does take orders.
    ms = [m for m in event.get("markets") or []
          if not m.get("closed") and ((m.get("volumeNum") or 0) > 0 or m.get("acceptingOrders")
                                      or m.get("slug") == market_slug)]
    for m in ms:
        try:
            token = json.loads(m["clobTokenIds"])[0]
            price = round(float(json.loads(m["outcomePrices"])[0]) * 100, 4)
        except (KeyError, IndexError, TypeError, ValueError):
            continue  # a market without an order book yet
        out.append({"venue": "polymarket", "venue_ref": token, "title": m.get("question") or event["title"],
                    "rules": m.get("description") or event.get("description") or "",
                    "url": f"https://polymarket.com/event/{event['slug']}/{m['slug']}", "price": price,
                    "slug": m["slug"], "event": event["title"]})
    out.sort(key=lambda c: (c["slug"] != market_slug, abs(c["price"] - 50)))
    return out


def lookup(event_slug: str, market_slug: str | None) -> list[dict]:
    events = get(GAMMA + "/events", slug=event_slug)
    if not events:
        raise MarketNotFound("market not found")
    return parse_event(events[0], market_slug)


def current_price(token: str) -> float | None:
    return round(float(get(CLOB + "/midpoint", token_id=token)["mid"]) * 100, 4)


def resolved(token: str) -> bool:
    """Whether the market behind a token is closed for good. Asked for closed markets only: an open one is not listed."""
    return any(m.get("closed") is True for m in get(GAMMA + "/markets", clob_token_ids=token, closed="true") or [])


def parse_history(data: dict | None) -> list[tuple[float, float]]:
    """(unix seconds, percent) from a prices-history answer, oldest first; odd points are left out."""
    out = []
    for point in (data or {}).get("history") or []:
        try:
            ts, price = float(point["t"]), round(float(point["p"]) * 100, 4)
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= price <= 100:
            out.append((ts, price))
    return sorted(out)


def history(token: str) -> list[tuple[float, float]]:
    """The last week of prices, about one an hour, so a market tracked just now has a chart at once."""
    return parse_history(get(CLOB + "/prices-history", market=token, interval="1w", fidelity=60))
