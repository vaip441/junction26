from fastapi.testclient import TestClient

from terminal import db as store
from terminal.api import create_app


def tick(market_id, ts, verdict="none", hidden=True, **kw):
    return {"market_id": market_id, "ts": ts, "published_ts": None, "kind": "article", "source": "reuters.com", "url": None,
            "headline": f"h{ts}", "up": 0.1, "none": 0.8, "down": 0.1, "strength": 0.0, "verdict": verdict,
            "confidence": 0.8, "price_at": 40.0, "test": False, "backfill": False, "hidden": hidden,
            "dedupe_key": f"{market_id}-{ts}", **kw}


def build(db):
    store.add_market(db, id="m", venue="kalshi", venue_ref="T", title="Will X win?", rules="r", url=None)
    store.add_market(db, id="old", venue="polymarket", venue_ref=None, title="A replay", rules="r", url=None,
                     replay={"start": 0, "end": 1, "outcome": "yes"})
    ids = [store.add_tick(db, t)["id"] for t in [
        tick("m", 100),                                   # older than the window: listed, not counted
        tick("m", 5000), tick("m", 5010, "up", hidden=False),
        tick("m", 5020, "up", hidden=False, kind="typed", test=True),  # a sentence someone said is not reading
        tick("old", 5030)]]                               # nor is a replay's post
    return ids


def test_reading_counts_the_last_day_and_lists_the_newest_items_shown_or_not():
    db = store.connect(":memory:")
    ids = build(db)
    r = store.reading(db, now=5000 + 86000)
    assert (r["read"], r["shown"], r["window_seconds"]) == (2, 1, 86400)
    assert [(i["id"], i["verdict"], i["hidden"], i["market"]) for i in r["recent"]] == [
        (ids[2], "up", False, "Will X win?"), (ids[1], "none", True, "Will X win?"), (ids[0], "none", True, "Will X win?")]
    assert set(r["recent"][0]) == {"id", "market_id", "market", "ts", "published_ts", "source", "headline", "verdict", "hidden"}
    # the screen asks again with the newest id it has: only what came after is sent
    assert [i["id"] for i in store.reading(db, after=ids[1], now=5000 + 86000)["recent"]] == [ids[2]]
    assert store.reading(db, limit=1, now=6000)["recent"][0]["id"] == ids[2]


def test_staged_articles_from_our_own_newsroom_are_listed_but_not_counted():
    db = store.connect(":memory:")
    build(db)
    staged = store.add_tick(db, tick("m", 5040, "up", hidden=False, test=True))["id"]
    r = store.reading(db, now=5000 + 86000)
    assert (r["read"], r["shown"]) == (2, 1) and r["recent"][0]["id"] == staged


def test_the_counts_are_kept_for_two_seconds_while_the_list_stays_live(monkeypatch):
    import time
    from types import SimpleNamespace

    clock = [1000.0]
    monkeypatch.setattr(store, "time", SimpleNamespace(time=time.time, monotonic=lambda: clock[0]))
    db = store.connect(":memory:")
    build(db)
    assert store.reading(db, now=5000 + 86000)["read"] == 2
    late = store.add_tick(db, tick("m", 5040))["id"]
    clock[0] += 1.9  # every open screen asks every 2 seconds: the counts are not worked out again for each
    r = store.reading(db, now=5000 + 86000)
    assert r["read"] == 2 and r["recent"][0]["id"] == late
    clock[0] += 0.1
    assert store.reading(db, now=5000 + 86000)["read"] == 3


def test_the_api_serves_the_reading(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "t.db"), poll=False)) as c:
        r = c.get("/reading").json()
        assert r["read"] == 0 and r["shown"] == 0 and r["recent"] == []
        assert c.get("/reading", params={"after": 5}).status_code == 200
        assert c.get("/reading", params={"after": "x"}).status_code == 422
