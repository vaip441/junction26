"""The one path every tick takes: dedupe -> score -> store -> publish."""
import logging
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

from terminal import db as store
from terminal.pricing import nudge
from terminal.scoring import ScoringError, is_hidden, verdict

log = logging.getLogger(__name__)
TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|ref$|ref_src$|tid$|amp$)")


def dedupe_key(kind: str, url: str | None, headline: str, ts: float) -> str:
    if kind in ("mic", "typed"):
        return f"{kind}:{ts}:{headline}"  # a sentence said twice is two ticks
    if url:
        u = urlsplit(url)
        # shortcut: only known tracking parameters are dropped, so ?id=1 and ?id=2 stay distinct;
        # add to TRACKING when a site's own noise parameter shows up as duplicates
        query = urlencode(sorted((k, v) for k, v in parse_qsl(u.query) if not TRACKING.match(k.lower())))
        host = u.netloc.lower().removeprefix("www.")
        return host + u.path.rstrip("/") + (f"?{query}" if query else "")
    return re.sub(r"[^a-z0-9]+", " ", headline.lower()).strip()


async def ingest(db, bus, scorer, market: dict, *, kind: str, source: str, headline: str, url: str | None = None,
                 body: str = "", published_ts: float | None = None, backfill: bool = False,
                 now: float | None = None) -> dict | None:
    """Score and store one item. None if it is a duplicate or scoring failed (so it can be retried)."""
    now = time.time() if now is None else now
    key = dedupe_key(kind, url, headline, now)
    if store.has_tick(db, market["id"], key):
        return None
    try:
        s = await scorer(market["title"], market["rules"], f"{headline}\n{body}".strip())
    except ScoringError as e:
        log.warning("scoring failed for %r on %s: %s", headline[:60], market["id"], e)
        return None
    v, confidence = verdict(s)
    made_up, latest = market["venue"] == "made_up", store.latest_price(db, market["id"])
    # A made-up price is ours alone, so it always moves from the newest value: two sentences scored
    # out of order must both count. A real market's tick records the venue price at detection time.
    price = (latest and latest[1]) if made_up else store.price_at(db, market["id"], now)
    tick = store.add_tick(db, {
        "market_id": market["id"], "ts": now, "published_ts": published_ts, "kind": kind, "source": source,
        "url": url, "headline": headline, "up": s.up, "none": s.none, "down": s.down, "strength": s.strength,
        "verdict": v, "confidence": confidence, "price_at": price, "test": kind in ("mic", "typed"),
        "backfill": backfill, "hidden": is_hidden(s, kind), "dedupe_key": key})
    if tick is None:  # lost a race with a concurrent ingest of the same item
        return None
    if made_up and latest is not None:
        new, at = nudge(price, s.strength), max(now, latest[0] + 0.001)
        store.add_price(db, market["id"], at, new)
        bus.publish("price", {"market_id": market["id"], "ts": at, "price": new})
    if not tick["hidden"]:
        bus.publish("tick", public(tick))
    return tick


def public(tick: dict) -> dict:
    """A tick as the frontend sees it."""
    return {k: v for k, v in tick.items() if k not in ("dedupe_key", "hidden")}
