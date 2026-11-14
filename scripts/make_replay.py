"""Build the replays: a finished market's real prices and what people posted in those hours, each post scored
the way a live one is. The model is told only what was known when the post appeared: the date, the price
at that minute and the posts before it.

    PYTHONPATH=. uv run --env-file .env python scripts/make_replay.py [id ...]

Prices are Polymarket's history, one a minute. Posts are from Bluesky, whose search takes a time window
and whose posts cannot be edited afterwards: a news site's headline is rewritten once the result is known,
which would hand the model the ending. Of each half hour the most-liked posts are kept, by the rule the
live service uses (posts.bluesky_worth); how many likes a post ended up with is the one thing used here
that was not known at the time, and the model never sees it.
The result is written to replays/<id>.json, which the service loads when it starts.
"""
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from terminal import db as store
from terminal import posts, scoring
from terminal.bus import Bus
from terminal.pipeline import ingest
from terminal.record import record

ROOT = Path(__file__).parent.parent
OUT, CACHE = ROOT / "replays", ROOT / "data" / "replay-posts"  # the posts found are kept, so a re-run only scores
GAMMA, CLOB = "https://gamma-api.polymarket.com", "https://clob.polymarket.com"
SLICE = 1800
# The markets, hardcoded. Each finished between 25 Oct and 4 Nov 2026, which is assumed (not verified) to be
# later than anything the scoring model was trained on, so that it cannot know how they ended.
REPLAYS = [
    {"id": "replay-lula", "slug": "brazil-presidential-election", "contract": "Lula",
     "start": "2026-10-25T19:00", "end": "2026-10-26T00:30", "per_slice": 20, "queries": ["lula", "bolsonaro"]},
    {"id": "replay-senate", "slug": "which-party-will-win-the-senate-in-2026", "contract": "Democratic Party",
     "start": "2026-11-03T22:30", "end": "2026-11-04T03:15", "per_slice": 20, "queries": ["senate"]},
    {"id": "replay-texas", "slug": "texas-senate-election-winner", "contract": "Democrats",
     "start": "2026-11-03T22:30", "end": "2026-11-04T02:30", "per_slice": 20, "queries": ["texas"]},
]


def stamp(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=UTC).timestamp()


def contract(c: httpx.Client, slug: str, words: str) -> dict:
    """The contract of a Polymarket event whose question names `words`."""
    event = c.get(GAMMA + "/events", params={"slug": slug}).raise_for_status().json()[0]
    m = next(m for m in event["markets"] if words in m["question"])
    return {"title": m["question"], "rules": m.get("description") or event.get("description") or "",
            "url": f"https://polymarket.com/event/{slug}", "token": json.loads(m["clobTokenIds"])[0],
            "outcome": "yes" if json.loads(m["outcomePrices"])[0] == "1" else "no"}


def prices(c: httpx.Client, token: str, start: float, end: float) -> list[tuple[float, float]]:
    history = c.get(CLOB + "/prices-history", params={"market": token, "startTs": int(start), "endTs": int(end),
                                                      "fidelity": 1}).raise_for_status().json()["history"]
    return [(float(p["t"]), round(float(p["p"]) * 100, 1)) for p in history]


async def found_posts(conf: dict, start: float, end: float) -> list[dict]:
    """The most-liked posts of every half hour that match one of the replay's search words."""
    cached = CACHE / f"{conf['id']}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    out, at = [], start
    while at < end:
        found = {}
        for q in conf["queries"]:
            found.update({p["url"]: p for p in await posts.bluesky(q, at, min(at + SLICE, end), limit=100)
                          if posts.bluesky_worth(p)})
        best = sorted(found.values(), key=lambda p: -p["likes"])[:conf["per_slice"]]
        out += [{"ts": p["published"], "source": f"bsky.app/{p['handle']}", "url": p["url"], "headline": p["text"][:280],
                 "body": p["text"], "likes": p["likes"], "replies": p["replies"]} for p in best]
        print(f"  {datetime.fromtimestamp(at, UTC):%d %H:%M}: {len(found)} posts worth reading, kept {len(best)}", flush=True)
        at += SLICE
    out.sort(key=lambda p: p["ts"])
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(out))
    return out


async def build(conf: dict) -> None:
    start, end = stamp(conf["start"]), stamp(conf["end"])
    with httpx.Client(timeout=40, headers={"User-Agent": posts.UA}) as c:
        found = contract(c, conf["slug"], conf["contract"])
        points = prices(c, found["token"], start, end)
    said = await found_posts(conf, start, end)
    print(f"{conf['id']}: {found['title']} ({len(points)} prices, {len(said)} posts)", flush=True)
    db = store.connect(":memory:")
    store.add_market(db, id=conf["id"], venue="polymarket", venue_ref=None, title=found["title"], rules=found["rules"],
                     url=found["url"], poll_seconds=0)
    market, bus, shown = store.get_market(db, conf["id"]), Bus(), 0
    for s in said:
        while shown < len(points) and points[shown][0] <= s["ts"]:  # the scorer sees no price from the future
            store.add_price(db, conf["id"], *points[shown])
            shown += 1
        if shown == 0:
            continue  # before the first price: nothing to judge the call against
        tick = await ingest(db, bus, scoring.score, market, kind="post", source=s["source"], headline=s["headline"],
                            url=s["url"], body=s["body"], published_ts=s["ts"], now=s["ts"], likes=s["likes"],
                            replies=s["replies"])
        if tick and not tick["hidden"]:
            print(f"  {datetime.fromtimestamp(s['ts'], UTC):%d %H:%M} {tick['price_at']:5.1f}% {tick['verdict']:5s}"
                  f" {tick['strength']:+.2f}  {s['headline'][:100]}", flush=True)
    store.add_history(db, conf["id"], points[shown:])
    keep = ("ts", "published_ts", "kind", "source", "url", "headline", "up", "none", "down", "strength", "verdict",
            "confidence", "price_at", "likes", "replies", "rule")
    ticks = [{k: t[k] for k in keep} for t in reversed(store.ticks(db, conf["id"], 500))]
    OUT.mkdir(exist_ok=True)
    (OUT / f"{conf['id']}.json").write_text(json.dumps({
        "id": conf["id"], "venue": "polymarket", "title": found["title"], "rules": found["rules"], "url": found["url"],
        "outcome": found["outcome"], "start": points[0][0], "end": points[-1][0], "prices": points, "ticks": ticks},
        ensure_ascii=False, separators=(",", ":")))
    print(f"{conf['id']}: {len(ticks)} ticks shown, record {record(db, now=end + 3600, since=0)}", flush=True)


async def main(ids: list[str]) -> None:
    for conf in REPLAYS:
        if not ids or conf["id"] in ids:
            await build(conf)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
