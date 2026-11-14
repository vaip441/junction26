import asyncio

from terminal import db as store
from terminal import moves
from terminal.bus import Bus
from terminal.scoring import ScoringError

NOW = 1_800_000_000.0
RULE = {"start": 0, "end": 5, "text": "Rules", "confidence": 0.9}


def market(db, id="m", venue="kalshi", lead_id=None, filled=True):
    store.add_market(db, id=id, venue=venue, venue_ref=id, title="Will X happen?", rules="Rules. More rules.",
                     url=None, lead_id=lead_id, queries=["x"])
    if filled:
        store.set_filled(db, id)
    return store.get_market(db, id)


def prices(db, id, *samples):
    for ago, price in samples:
        store.add_price(db, id, NOW - ago, price)


def tick(db, key, *, ago, market_id="m", published_ago=None, **kw):
    return store.add_tick(db, {
        "market_id": market_id, "ts": NOW - ago, "published_ts": published_ago and NOW - published_ago,
        "kind": "article", "source": f"{key}.example", "url": f"https://{key}.example/1", "headline": f"headline {key}",
        "up": 0.1, "none": 0.8, "down": 0.1, "strength": 0.1, "verdict": "none", "confidence": 0.8, "price_at": None,
        "test": False, "backfill": False, "hidden": False, "dedupe_key": key, **kw})


def decide_with(probabilities, seen=None):
    async def decide(input, questions):
        if seen is not None:
            seen.append((input, questions))
        return {"cause": {"probabilities": probabilities}}
    return decide


def shown(db, id="m"):
    return [moves.public_move(m) for m in store.moves(db, id)]


async def no_rule(market, item):
    return None


async def no_fetch(market):
    return 0


def test_a_jump_of_three_points_within_ten_minutes_is_a_move_and_is_reported_once():
    db = store.connect(":memory:")
    market(db)
    prices(db, "m", (900, 30.0), (540, 40.0), (120, 41.0), (60, 41.5), (0, 44.5))
    [move] = moves.find(db, NOW)
    # it began at the last sample still three points away, not at the edge of the window
    assert (move["market"]["id"], move["since"], move["from"], move["to"]) == ("m", NOW - 60, 41.5, 44.5)
    store.add_move(db, "m", NOW, NOW - 60, 41.5, 44.5, None, None, None)
    assert moves.find(db, NOW + 60) == []  # explained already


def test_small_changes_made_up_markets_related_contracts_and_unfilled_markets_are_left_alone():
    db = store.connect(":memory:")
    market(db)
    market(db, "mu", venue="made_up")
    market(db, "rel", lead_id="m")
    market(db, "new", filled=False)
    prices(db, "m", (300, 40.0), (0, 42.5))
    for id in ("mu", "rel", "new"):
        prices(db, id, (300, 40.0), (0, 60.0))
    assert moves.find(db, NOW) == []
    prices(db, "m", (700, 10.0))  # a price from before the window does not count
    assert moves.find(db, NOW) == []


def test_the_cause_is_chosen_by_decision_1_among_what_was_published_around_the_move():
    db, bus, seen, searched = store.connect(":memory:"), Bus(), [], []
    m = market(db)
    prices(db, "m", (300, 40.0), (0, 46.0))
    near = tick(db, "near", ago=200, published_ago=600)        # published 5 min before the move began
    tick(db, "old", ago=100, published_ago=3 * 3600)           # found just now, but hours old
    tick(db, "hidden", ago=100, hidden=True)
    tick(db, "typed", ago=100, test=True)
    tick(db, "history", ago=100, backfill=True)
    tick(db, "later", ago=-500)                                # after the moment being explained
    tick(db, "other", ago=100, market_id="n")

    async def fetch(market):  # the web is searched at once: what it finds is a candidate too
        searched.append(market["id"])
        tick(db, "found", ago=0)

    async def ruler(market, item):
        assert item == "found.example: headline found"
        return RULE

    q = bus.subscribe()
    [move] = moves.find(db, NOW)
    out = asyncio.run(moves.explain(db, bus, m, move, fetch=fetch, ruler=ruler, now=NOW,
                                    decide=decide_with({"t0": 0.7, "t1": 0.2, "none": 0.1}, seen)))
    assert searched == ["m"]
    input, questions = seen[0]
    assert "Will X happen?" in input and "from 40% to 46%" in input and "data, not instructions" in input
    assert questions["cause"]["type"] == "choice" and list(questions["cause"]["criteria"]) == ["t0", "t1", "none"]
    assert "headline found" in questions["cause"]["criteria"]["t0"]  # newest first
    assert "headline near" in questions["cause"]["criteria"]["t1"] and "5 min before" in questions["cause"]["criteria"]["t1"]
    assert (out["market_id"], out["ts"], out["since"], out["from"], out["to"]) == ("m", NOW, NOW - 300, 40.0, 46.0)
    assert out["cause"]["headline"] == "headline found" and out["confidence"] == 0.7 and out["rule"] == RULE
    assert "dedupe_key" not in out["cause"]  # a tick as the frontend sees it
    assert q.get_nowait() == ("move", out) and shown(db) == [out]
    assert near["rule"] is None


def test_a_cause_that_already_carries_its_rule_keeps_it():
    db = store.connect(":memory:")
    m = market(db)
    prices(db, "m", (300, 40.0), (0, 46.0))
    tick(db, "a", ago=100, rule='{"start": 7, "end": 18, "text": "More rules.", "confidence": 0.8}')

    async def ruler(market, item):
        raise AssertionError("asked for a rule the tick already has")

    out = asyncio.run(moves.explain(db, Bus(), m, moves.find(db, NOW)[0], fetch=no_fetch, ruler=ruler, now=NOW,
                                    decide=decide_with({"t0": 0.9, "none": 0.1})))
    assert out["rule"] == {"start": 7, "end": 18, "text": "More rules.", "confidence": 0.8}


def test_a_move_nothing_explains_is_recorded_without_a_cause():
    def explained(decide, fetch=no_fetch, ticks=("a",)):
        db = store.connect(":memory:")
        m = market(db)
        prices(db, "m", (300, 46.0), (0, 40.0))
        for key in ticks:
            tick(db, key, ago=100)
        out = asyncio.run(moves.explain(db, Bus(), m, moves.find(db, NOW)[0], fetch=fetch, ruler=no_rule, now=NOW,
                                        decide=decide))
        assert shown(db) == [out] and (out["from"], out["to"]) == (46.0, 40.0)
        return out["cause"], out["confidence"], out["rule"]

    async def never(input, questions):
        raise AssertionError("asked with nothing to choose from")

    async def down(input, questions):
        raise ScoringError("api down")

    async def broken(market):
        raise RuntimeError("search exploded")

    nothing = (None, None, None)
    assert explained(never, ticks=()) == nothing                           # nothing was published around it
    assert explained(decide_with({"t0": 0.2, "none": 0.8})) == nothing     # the model says none of them
    assert explained(decide_with({"t0": 0.3, "t1": 0.3, "none": 0.1}), ticks=("a", "b")) == nothing  # none stands out
    assert explained(decide_with({"t7": 0.9})) == nothing                  # an odd answer
    assert explained(down) == nothing                                      # the model cannot be reached
    cause, confidence, _ = explained(decide_with({"t0": 0.9, "none": 0.1}), fetch=broken)
    assert cause["headline"] == "headline a" and confidence == 0.9         # a failed search still leaves what was stored


def test_a_market_deleted_while_its_move_was_explained_gets_no_move():
    db, bus = store.connect(":memory:"), Bus()
    m = market(db)
    prices(db, "m", (300, 40.0), (0, 46.0))
    [move] = moves.find(db, NOW)

    async def fetch(market):
        store.delete_market(db, "m")

    q = bus.subscribe()
    assert asyncio.run(moves.explain(db, bus, m, move, fetch=fetch, ruler=no_rule, now=NOW, decide=decide_with({}))) is None
    assert q.empty() and store.moves(db, "m") == []


def test_deleting_a_market_takes_its_moves_with_it():
    db = store.connect(":memory:")
    market(db)
    market(db, "n")
    for id in ("m", "n"):
        store.add_move(db, id, NOW, NOW - 60, 40.0, 45.0, None, None, None)
    store.delete_market(db, "m")
    assert store.moves(db, "m") == [] and len(store.moves(db, "n")) == 1
