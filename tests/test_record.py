from fastapi.testclient import TestClient

from terminal import db as store
from terminal.record import record


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
    assert record(db, now=5100) == {"called": 3, "moved": 2, "same_way": 1, "window_seconds": 900, "since": 10}


def test_record_is_empty_on_a_fresh_store():
    db = store.connect(":memory:")
    assert record(db, now=100) == {"called": 0, "moved": 0, "same_way": 0, "window_seconds": 900, "since": None}


def test_record_route(tmp_path):
    from terminal.api import create_app

    with TestClient(create_app(db_path=str(tmp_path / "t.db"), poll=False)) as c:
        r = c.get("/record")
        assert r.status_code == 200 and r.json()["called"] == 0 and r.json()["window_seconds"] == 900
