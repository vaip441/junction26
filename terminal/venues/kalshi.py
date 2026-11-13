"""Kalshi public (no-login) Trade API v2. get() is copied from ~/scorer-mm/scorer_mm/kalshi.py."""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from terminal.venues.errors import MarketNotFound

BASE = "https://api.elections.kalshi.com/trade-api/v2"
RATE = 12  # req/s; public limit is ~20/s and 429 backoff collapses throughput, so stay well under
TICKER = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_lock = threading.Lock()
_next = [0.0]


def get(path, **params):
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")}, doseq=True)
    url = f"{BASE}{path}" + (f"?{q}" if q else "")
    for attempt in range(4):
        with _lock:
            t = max(time.monotonic(), _next[0])
            _next[0] = t + 1 / RATE
        time.sleep(max(0.0, t - time.monotonic()))
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            # Kalshi sometimes signals rate limiting as a 400 with code too_many_requests
            if e.code not in (429, 500, 502, 503, 504) and b"too_many_requests" not in e.read():
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(min(30, 2**attempt))
    raise RuntimeError(f"giving up on {url}")


def canonical(url: str) -> str | None:
    """A kalshi.com/markets/... link rebuilt from its validated parts; None for anything else.

    The pasted text is never stored or echoed: the frontend renders this address as a link.
    """
    u = urllib.parse.urlsplit(url.strip())
    parts = [p for p in u.path.split("/") if p]
    if (u.scheme.lower() not in ("http", "https") or u.netloc.lower().removeprefix("www.") != "kalshi.com"
            or len(parts) < 2 or parts[0] != "markets" or not all(TICKER.match(p) for p in parts)):
        return None
    return "https://kalshi.com/" + "/".join(parts)


def parse_link(url: str) -> str | None:
    """The ticker at the end of a kalshi.com/markets/... address, upper-cased."""
    link = canonical(url)
    return link and link.rsplit("/", 1)[1].upper()


def price(m: dict) -> float | None:
    """Percent. Midpoint of a real two-sided quote, else the last trade, else None."""
    def num(k):
        try:
            return float(m.get(k) or 0)
        except ValueError:
            return 0.0
    bid, ask, last = num("yes_bid_dollars"), num("yes_ask_dollars"), num("last_price_dollars")
    if 0 < bid < ask < 1:
        return round((bid + ask) / 2 * 100, 4)
    return round(last * 100, 4) if 0 < last < 1 else None


def parse_event(event: dict, wanted: str, url: str | None = None) -> list[dict]:
    """Open contracts of an event: the wanted ticker first, then the most undecided (nearest 50%).

    Total volume is a poor guide: in a many-candidate event the busiest contract is often a 0.1% longshot.
    """
    slug = event["event_ticker"].lower()
    url = url or f"https://kalshi.com/markets/{event.get('series_ticker', slug).lower()}/e/{slug}"
    # untraded contracts are placeholders; keep one only if it was asked for by name
    ms = [m for m in event.get("markets") or []
          if m.get("status") == "active" and (float(m.get("volume_fp") or 0) > 0 or m["ticker"] == wanted)]
    ms.sort(key=lambda m: (m["ticker"] != wanted, abs((price(m) if price(m) is not None else 1000) - 50)))
    def title(m):
        t, sub = m.get("title") or event["title"], m.get("yes_sub_title") or ""
        return t if not sub or sub.lower() in t.lower() else f"{t} ({sub})"  # outcomes of one event share a title

    return [{"venue": "kalshi", "venue_ref": m["ticker"], "title": title(m),
             "rules": (m.get("rules_primary") or "") + " " + (m.get("rules_secondary") or ""), "url": url,
             "price": price(m), "event": event["title"]} for m in ms]


def lookup(ticker: str, url: str | None = None) -> list[dict]:
    """Contracts for an event ticker or a market ticker. LookupError if Kalshi has neither."""
    try:
        try:
            event = get(f"/events/{ticker}", with_nested_markets="true")["event"]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            event_ticker = get(f"/markets/{ticker}")["market"]["event_ticker"]
            event = get(f"/events/{event_ticker}", with_nested_markets="true")["event"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise MarketNotFound("market not found") from e
        raise
    return parse_event(event, ticker, url)


def current_price(ticker: str) -> float | None:
    return price(get(f"/markets/{ticker}")["market"])
