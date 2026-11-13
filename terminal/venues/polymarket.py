"""Polymarket public (no-login) endpoints. get() is copied from ~/weather-mm/weather_mm/pm.py."""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

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


def parse_event(event: dict, market_slug: str | None) -> list[dict]:
    """Open contracts of an event: the named market first, then the most undecided (nearest 50%)."""
    out = []
    ms = [m for m in event.get("markets") or [] if not m.get("closed")]
    for m in ms:
        try:
            token = json.loads(m["clobTokenIds"])[0]
            price = round(float(json.loads(m["outcomePrices"])[0]) * 100, 4)
        except (KeyError, IndexError, TypeError, ValueError):
            continue  # a market without an order book yet
        out.append({"venue": "polymarket", "venue_ref": token, "title": m.get("question") or event["title"],
                    "rules": m.get("description") or event.get("description") or "",
                    "url": f"https://polymarket.com/event/{event['slug']}/{m['slug']}", "price": price,
                    "slug": m["slug"]})
    out.sort(key=lambda c: (c["slug"] != market_slug, abs(c["price"] - 50)))
    return out


def lookup(event_slug: str, market_slug: str | None) -> list[dict]:
    events = get(GAMMA + "/events", slug=event_slug)
    if not events:
        raise LookupError("market not found")
    return parse_event(events[0], market_slug)


def current_price(token: str) -> float | None:
    return round(float(get(CLOB + "/midpoint", token_id=token)["mid"]) * 100, 4)
