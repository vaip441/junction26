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
SEARCH = "https://api.elections.kalshi.com/v1/search/series"  # the search box on kalshi.com: v2 has no search by words
RATE = 12  # req/s; public limit is ~20/s and 429 backoff collapses throughput, so stay well under
TICKER = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_lock = threading.Lock()
_next = [0.0]


def get(path, **params):
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")}, doseq=True)
    url = (path if path.startswith("https://") else f"{BASE}{path}") + (f"?{q}" if q else "")
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


def search(words: str, limit: int = 10) -> list[str]:
    """Pages of open events matching plain words, best first: Kalshi's own search. A web search engine
    often knows only the busiest market on a subject ("Ballon d'Or", not "Super Ballon d'Or")."""
    # shortcut: an undocumented endpoint, so an answer in another shape finds nothing; the web search still runs
    found = (get(SEARCH, query=words[:200], page_size=limit) or {}).get("current_page") or []
    pairs = [(str(e.get("series_ticker") or ""), str(e.get("event_ticker") or ""))
             for e in found if isinstance(e, dict) and e.get("active_market_count")]
    return [f"https://kalshi.com/markets/{series.lower()}/e/{event.lower()}"
            for series, event in pairs if TICKER.match(series) and TICKER.match(event)]


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
    # contracts with no trades and no quote are placeholders; keep one only if it was asked for by name
    ms = [m for m in event.get("markets") or []
          if m.get("status") == "active" and (float(m.get("volume_fp") or 0) > 0 or price(m) is not None
                                              or m["ticker"] == wanted)]
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


def parse_history(data: dict | None) -> list[tuple[float, float]]:
    """(unix seconds, percent) from a candlesticks answer, oldest first: each hour's closing price, read
    like price() (the midpoint of a real two-sided quote, else the last trade); hours with neither are left out."""
    out = []
    for candle in (data or {}).get("candlesticks") or []:
        try:
            ts = float(candle["end_period_ts"])
        except (KeyError, TypeError, ValueError):
            continue
        p = price({"yes_bid_dollars": (candle.get("yes_bid") or {}).get("close_dollars"),
                   "yes_ask_dollars": (candle.get("yes_ask") or {}).get("close_dollars"),
                   "last_price_dollars": (candle.get("price") or {}).get("close_dollars")})
        if p is not None:
            out.append((ts, p))
    return sorted(out)


def history(ticker: str, days: int = 7) -> list[tuple[float, float]]:
    """The last week of prices, one an hour, so a market tracked just now has a chart at once."""
    event = get(f"/markets/{ticker}")["market"]["event_ticker"]
    series = get(f"/events/{event}")["event"]["series_ticker"]
    now = int(time.time())
    return parse_history(get(f"/series/{series}/markets/{ticker}/candlesticks",
                             start_ts=now - days * 86400, end_ts=now, period_interval=60))
