from fastapi.testclient import TestClient

from terminal import db as store
from terminal.record import START, record


def tick(market_id, ts, verdict, price_at, **kw):
    return {"market_id": market_id, "ts": ts, "published_ts": None, "kind": "article", "source": "s", "url": None,
            "headline": "h", "up": 0.8, "none": 0.1, "down": 0.1, "strength": 0.5, "verdict": verdict,
            "confidence": 0.8, "price_at": price_at, "test": False, "backfill": False, "hidden": False,
            "dedupe_key": f"{market_id}-{ts}-{verdict}-{sorted(kw.items())}", **kw}


def build(db):
    store.add_market(db, id="m", venue="kalshi", venue_ref="T", title="t", rules="r", url=None)
    store.add_market(db, id="mu", venue="made_up", venue_ref=None, title="t", rules="r", url=None)
    for ts, p in [(0, 40.0), (600, 43.0), (1500, 39.0), (2400, 39.5)]:
        store.add_price(db, "m", ts, p)
    store.add_price(db, "mu", 0, 20.0)
    store.add_price(db, "mu", 500, 30.0)
    for t in [tick("m", 10, "up", 40.0),                    # 40 -> 43: moved, same way
              tick("m", 700, "up", 43.0),                   # 43 -> 39: moved, wrong way
              tick("m", 1600, "down", 39.0),                # 39 -> 39.5: did not move
              tick("m", 5000, "up", 39.5),                  # window not over at now=5100
              tick("m", 20, "up", 40.0, backfill=True),
              tick("m", 30, "up", 40.0, test=True),
              tick("m", 40, "none", 40.0),
              tick("m", 50, "up", None),                    # no price when it landed
              tick("mu", 10, "up", 20.0)]:
        assert store.add_tick(db, t) is not None


def test_record_counts_only_eligible_ticks_and_real_moves():
    db = store.connect(":memory:")
    build(db)
    assert record(db, now=5100, since=0) == {
        "calls": 3, "evaluable": 2, "same_direction": 1, "opposite_direction": 1, "no_qualifying_move": 1,
        "window_seconds": 900, "min_move_points": 1.0, "markets": 1, "start": 0, "since": 10}


def test_every_call_is_followed_opposed_or_unmoved_and_markets_are_counted_once_each():
    db = store.connect(":memory:")
    build(db)
    store.add_market(db, id="n", venue="polymarket", venue_ref="T", title="t", rules="r", url=None)
    store.add_market(db, id="rp", venue="polymarket", venue_ref=None, title="t", rules="r", url=None,
                     replay={"start": 0, "end": 3000, "outcome": "yes"})
    for id in ("n", "rp"):
        store.add_price(db, id, 0, 50.0)
        store.add_price(db, id, 900, 48.0)
    store.add_tick(db, tick("n", 5, "down", 50.0))   # 50 -> 48: moved, same way
    store.add_tick(db, tick("n", 6, "down", 50.0, url="again"))
    store.add_tick(db, tick("rp", 5, "down", 50.0))  # a replay: prerecorded, never in the live record
    r = record(db, now=5100, since=0)
    assert r["calls"] == 5 and r["markets"] == 2
    assert (r["same_direction"], r["opposite_direction"], r["no_qualifying_move"]) == (3, 1, 1)
    assert r["evaluable"] == r["same_direction"] + r["opposite_direction"]
    assert r["calls"] == r["evaluable"] + r["no_qualifying_move"]


def test_the_move_that_qualifies_can_be_set():
    db = store.connect(":memory:")
    build(db)
    r = record(db, now=5100, since=0, min_move=0.5)   # 39 -> 39.5 now counts, against a call of down
    assert (r["evaluable"], r["opposite_direction"], r["no_qualifying_move"], r["min_move_points"]) == (3, 2, 0, 0.5)


def test_the_record_counts_from_its_start_and_names_its_first_tick():
    db = store.connect(":memory:")
    build(db)
    r = record(db, now=5100, since=600)
    assert (r["calls"], r["evaluable"], r["same_direction"], r["since"], r["start"]) == (2, 1, 0, 700, 600)


def test_the_weekend_record_starts_when_the_model_was_first_told_an_items_age():
    db = store.connect(":memory:")
    build(db)
    assert record(db, now=START + 5100)["calls"] == 0  # everything in the store is older


def test_record_is_empty_on_a_fresh_store():
    db = store.connect(":memory:")
    assert record(db, now=100, since=0) == {
        "calls": 0, "evaluable": 0, "same_direction": 0, "opposite_direction": 0, "no_qualifying_move": 0,
        "window_seconds": 900, "min_move_points": 1.0, "markets": 0, "start": 0, "since": None}


def test_record_route(tmp_path):
    from terminal.api import create_app

    with TestClient(create_app(db_path=str(tmp_path / "t.db"), poll=False)) as c:
        r = c.get("/record")
        assert r.status_code == 200 and r.json()["calls"] == 0 and r.json()["window_seconds"] == 900
        assert r.json()["min_move_points"] == 1.0 and r.json()["start"] == START
