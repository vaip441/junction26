"""The weekend record: of the ticks we called up or down, how often did the price then move that way?

A query, not stored state, so the rule can still change on demo day.
"""
import time

from terminal import db as store

ELIGIBLE = """
SELECT t.market_id, t.ts, t.verdict, t.price_at FROM ticks t JOIN markets m ON m.id = t.market_id
WHERE t.verdict IN ('up', 'down') AND t.test = 0 AND t.backfill = 0 AND m.venue != 'made_up' AND m.replay IS NULL
  AND t.price_at IS NOT NULL AND t.ts + ? <= ? AND t.ts >= ?
"""
# 14 Nov 15:53 UTC: from here the scorer is told how old an item is. Before, half its calls were on news over
# 9 hours old that the markets had long priced, which says nothing about calls made knowing that.
START = 1794671613


def record(db, now: float | None = None, window: float = 900, min_move: float = 1.0, since: float = START) -> dict:
    now = time.time() if now is None else now
    called = moved = same_way = 0
    for t in db.execute(ELIGIBLE, (window, now, since)):
        called += 1
        later = store.price_at(db, t["market_id"], t["ts"] + window)
        change = later - t["price_at"]
        if abs(change) >= min_move:
            moved += 1
            same_way += (change > 0) == (t["verdict"] == "up")
    first = db.execute("SELECT MIN(t.ts) FROM ticks t JOIN markets m ON m.id = t.market_id WHERE m.replay IS NULL AND t.ts >= ?",
                       (since,)).fetchone()[0]
    return {"called": called, "moved": moved, "same_way": same_way, "window_seconds": int(window), "since": first}
