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


async def no_rule(market, item, closest=False):
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
    store.add_move(db, "m", NOW, NOW - 60, 41.5, 44.5, None, None, None, False, [])
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
    tick(db, "old", ago=100, published_ago=5 * 3600)           # found just now, but hours old
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
    assert out["explained"] is True and out["closest"] is None and out["related"] == []
    assert out["summary"] == "Up 6.0 points in 5 minutes. Likely cause: found.example: headline found"
    assert "dedupe_key" not in out["cause"]  # a tick as the frontend sees it
    assert q.get_nowait() == ("move", out) and shown(db) == [out]
    assert near["rule"] is None


def test_a_cause_that_already_carries_its_rule_keeps_it():
    db = store.connect(":memory:")
    m = market(db)
    prices(db, "m", (300, 40.0), (0, 46.0))
    tick(db, "a", ago=100, verdict="up", rule='{"start": 7, "end": 18, "text": "More rules.", "confidence": 0.8}')

    async def ruler(market, item):
        raise AssertionError("asked for a rule the tick already has")

    out = asyncio.run(moves.explain(db, Bus(), m, moves.find(db, NOW)[0], fetch=no_fetch, ruler=ruler, now=NOW,
                                    decide=decide_with({"t0": 0.9, "none": 0.1})))
    assert out["rule"] == {"start": 7, "end": 18, "text": "More rules.", "confidence": 0.8}


def test_a_move_nothing_explains_is_recorded_without_a_cause_but_with_the_closest_item():
    def explained(decide, fetch=no_fetch, ticks=("a",)):
        db = store.connect(":memory:")
        m = market(db)
        prices(db, "m", (300, 46.0), (0, 40.0))
        for key in ticks:
            tick(db, key, ago=100)
        out = asyncio.run(moves.explain(db, Bus(), m, moves.find(db, NOW)[0], fetch=fetch, ruler=no_rule, now=NOW,
                                        decide=decide))
        assert shown(db) == [out] and (out["from"], out["to"]) == (46.0, 40.0) and out["rule"] is None
        return out["cause"] and out["cause"]["headline"], out["closest"] and out["closest"]["headline"], out["confidence"]

    async def never(input, questions):
        raise AssertionError("asked with nothing to choose from")

    async def down(input, questions):
        raise ScoringError("api down")

    async def broken(market):
        raise RuntimeError("search exploded")

    nothing = (None, None, None)
    assert explained(never, ticks=()) == nothing                           # nothing was published around it
    assert explained(decide_with({"t0": 0.2, "none": 0.8})) == (None, "headline a", 0.2)   # the model says none of them
    assert explained(decide_with({"t0": 0.3, "t1": 0.3, "none": 0.3}), ticks=("a", "b")) == (None, "headline b", 0.3)
    # a dozen items split the vote (seen live: best 0.35, none 0.12): the best is the cause once it beats "none"
    assert explained(decide_with({"t0": 0.3, "t1": 0.35, "none": 0.1}), ticks=("a", "b")) == ("headline a", None, 0.35)
    assert explained(decide_with({"t7": 0.9})) == nothing                  # an odd answer
    assert explained(down) == nothing                                      # the model cannot be reached
    # a failed search still leaves what was stored
    assert explained(decide_with({"t0": 0.9, "none": 0.1}), fetch=broken) == ("headline a", None, 0.9)


def test_a_move_says_which_related_contracts_moved_with_it_and_reads_as_one_sentence():
    db = store.connect(":memory:")
    m = market(db)
    for id, title in (("rival", "Will the rival win?"), ("flat", "Will nobody win?"), ("new", "Listed a minute ago")):
        store.add_market(db, id=id, venue="kalshi", venue_ref=id, title=title, rules="r", url=None, lead_id="m")
    prices(db, "m", (300, 46.0), (0, 40.0))
    prices(db, "rival", (400, 20.0), (60, 25.5))
    prices(db, "flat", (400, 10.0), (60, 10.5))
    prices(db, "new", (60, 3.0))
    out = asyncio.run(moves.explain(db, Bus(), m, moves.find(db, NOW)[0], fetch=no_fetch, ruler=no_rule, now=NOW,
                                    decide=decide_with({})))
    assert out["related"] == [{"id": "rival", "title": "Will the rival win?", "from": 20.0, "to": 25.5}]
    assert out["summary"] == "Down 6.0 points in 5 minutes. No news explains it. Will the rival win? went up 5.5 at the same time."
    assert shown(db) == [out]
    quiet = {**out, "related": []}
    assert moves.summary(quiet) == "Down 6.0 points in 5 minutes. No news explains it."
    assert moves.summary({**quiet, "since": NOW - 86400, "from": 40.0, "to": 41.0}).startswith("Up 1.0 point in the last day.")
    assert moves.summary({**quiet, "since": NOW - 47880}).startswith("Down 6.0 points in 13 hours.")  # not "798 minutes"
    weak = {**quiet, "explained": True, "confidence": 0.17, "cause": {"source": "a.example", "headline": "A headline"}}
    assert moves.summary(weak) == "Down 6.0 points in 5 minutes. Possible cause: a.example: A headline"
    assert moves.summary({**weak, "confidence": 0.4}) == "Down 6.0 points in 5 minutes. Likely cause: a.example: A headline"


def test_what_the_search_behind_a_move_finds_counts_even_though_it_arrives_after_the_move_was_seen(monkeypatch):
    db = store.connect(":memory:")
    m = market(db)
    prices(db, "m", (300, 40.0), (0, 46.0))
    clock = iter([NOW, NOW + 8])  # when the move is seen; when the search is done
    monkeypatch.setattr(moves.time, "time", lambda: next(clock))

    async def fetch(market):
        tick(db, "found", ago=-5)  # stored five seconds into the search, with no publish time

    out = asyncio.run(moves.explain(db, Bus(), m, moves.find(db, NOW)[0], fetch=fetch, ruler=no_rule,
                                    decide=decide_with({"t0": 0.9, "none": 0.1})))
    assert out["cause"]["headline"] == "headline found" and out["ts"] == NOW


def test_why_a_market_moved_today_is_answered_on_request_from_its_strongest_items():
    db, bus, seen = store.connect(":memory:"), Bus(), []
    m = market(db)
    prices(db, "m", (90000, 30.0), (86000, 31.0), (40000, 38.0), (0, 44.0))
    tick(db, "weak", ago=1000, strength=0.1)
    tick(db, "strong", ago=50000, strength=-0.9)
    tick(db, "yesterday", ago=100000, strength=1.0)
    ask = lambda **kw: asyncio.run(moves.why(db, bus, m, ruler=no_rule, now=NOW, **kw))
    out = ask(decide=decide_with({"t0": 0.8, "none": 0.1}, seen))
    assert (out["since"], out["from"], out["to"]) == (NOW - 86400, 30.0, 44.0)
    criteria = seen[0][1]["cause"]["criteria"]
    assert list(criteria) == ["t0", "t1", "none"] and "headline strong" in criteria["t0"]  # strongest first, not newest
    assert "over the last day" in seen[0][0]
    assert out["cause"]["headline"] == "headline strong" and out["summary"].startswith("Up 14.0 points in the last day. Likely cause")

    async def never(input, questions):
        raise AssertionError("asked again within minutes")

    assert ask(decide=never) == out and len(shown(db)) == 1  # asked twice in a row: the same answer, no second call
    assert moves.find(db, NOW) == []
    prices(db, "m", (-60, 48.0))  # a jump right after: the answer given on request does not hide it
    assert len(moves.find(db, NOW + 60)) == 1


def test_a_market_that_did_not_move_today_or_has_no_prices_has_nothing_to_explain():
    db = store.connect(":memory:")
    m = market(db)

    async def never(*a, **kw):
        raise AssertionError("asked the model about a flat market")

    ask = lambda: asyncio.run(moves.why(db, Bus(), m, decide=never, ruler=no_rule, now=NOW))
    assert ask() is None
    prices(db, "m", (5000, 40.0), (0, 40.6))
    assert ask() is None and shown(db) == []
    young = market(db, "young")  # tracked for an hour: its first price stands in for yesterday's
    prices(db, "young", (3600, 20.0), (0, 26.0))
    out = asyncio.run(moves.why(db, Bus(), young, decide=decide_with({}), ruler=no_rule, now=NOW))
    assert (out["since"], out["from"], out["to"]) == (NOW - 3600, 20.0, 26.0)


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
        store.add_move(db, id, NOW, NOW - 60, 40.0, 45.0, None, None, None, False, [])
    store.delete_market(db, "m")
    assert store.moves(db, "m") == [] and len(store.moves(db, "n")) == 1


def test_an_item_scored_as_pushing_the_other_way_is_never_offered_as_the_cause():
    db, seen = store.connect(":memory:"), []
    m = market(db)
    prices(db, "m", (300, 40.0), (0, 46.0))  # up
    tick(db, "bearish", ago=100, verdict="down")
    tick(db, "bullish", ago=120, verdict="up")
    tick(db, "unclear", ago=140, verdict="none")
    out = asyncio.run(moves.explain(db, Bus(), m, moves.find(db, NOW)[0], fetch=no_fetch, ruler=no_rule, now=NOW,
                                    decide=decide_with({"t0": 0.6, "t1": 0.2, "none": 0.2}, seen)))
    input, questions = seen[0]
    criteria = questions["cause"]["criteria"]
    assert list(criteria) == ["t0", "t1", "none"] and "headline bullish" in criteria["t0"] and "headline unclear" in criteria["t1"]
    assert "go up" in questions["cause"]["instructions"] and "other way" in questions["cause"]["instructions"]
    assert out["cause"]["headline"] == "headline bullish"
