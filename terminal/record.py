"""The weekend record: directional follow-through. Of the ticks the model called up or down, how often did
the market's price then move, and which way?

What this measures: association between a call and the price a quarter of an hour later. A call counts as
followed when the price is at least `min_move` points away from where it stood at the call, in the called
direction. It does not show that the item caused the move (the same news reaches traders by other roads, and
prices move for reasons we never saw), and it is not accuracy, a win rate or a trading result: nothing was
bought or sold, and a market that drifts one way flatters every call made that way.

Counted: calls on real, live markets whose window is over. Left out: made-up markets, replays, spoken and
typed ticks, backfill, and calls made when the market had no price to stand on.

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
    calls = same = opposite = 0
    markets = set()
    for t in db.execute(ELIGIBLE, (window, now, since)):
        calls += 1
        markets.add(t["market_id"])
        later = store.price_at(db, t["market_id"], t["ts"] + window)
        change = later - t["price_at"]
        if abs(change) >= min_move:
            if (change > 0) == (t["verdict"] == "up"):
                same += 1
            else:
                opposite += 1
    first = db.execute("SELECT MIN(t.ts) FROM ticks t JOIN markets m ON m.id = t.market_id WHERE m.replay IS NULL AND t.ts >= ?",
                       (since,)).fetchone()[0]
    return {"calls": calls,                             # directional calls whose window is over
            "evaluable": same + opposite,               # of those, followed by a move of min_move or more
            "same_direction": same, "opposite_direction": opposite,
            "no_qualifying_move": calls - same - opposite,
            "window_seconds": int(window), "min_move_points": min_move,
            "markets": len(markets),                    # distinct real markets the calls were made on
            "start": since,                             # calls are counted from here (see START)
            "since": first}                             # the first tick stored after that, or None
