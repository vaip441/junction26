import json

from fastapi.testclient import TestClient

from terminal import db as store
from terminal import replay
from terminal.api import create_app
from terminal.record import record

FILE = {"id": "replay-x", "venue": "polymarket", "title": "Will X win?", "rules": "Resolves Yes if X wins.",
        "url": "https://polymarket.com/event/x", "outcome": "yes", "start": 1000.0, "end": 4000.0,
        "prices": [[1000.0, 20.0], [2000.0, 40.0], [4000.0, 99.0]],
        "ticks": [{"ts": 1500.0, "published_ts": 1500.0, "kind": "article", "source": "reuters.com",
                   "url": "https://reuters.com/a", "headline": "X takes the lead", "up": 0.8, "none": 0.1, "down": 0.1,
                   "strength": 0.6, "verdict": "up", "confidence": 0.8, "price_at": 20.0,
                   "rule": {"text": "Resolves Yes if X wins.", "start": 0, "end": 23}}]}


def folder(tmp_path, *files):
    for f in files or (FILE,):
        (tmp_path / f"{f['id']}.json").write_text(json.dumps(f))
    return tmp_path


def test_a_replay_file_becomes_a_market_with_its_prices_and_calls(tmp_path):
    db = store.connect(":memory:")
    assert replay.load(db, folder(tmp_path)) == ["replay-x"]
    m = store.get_market(db, "replay-x")
    assert m["replay"] == {"start": 1000.0, "end": 4000.0, "outcome": "yes"} and m["poll_seconds"] == 0
    assert [p["price"] for p in store.prices(db, "replay-x")] == [20.0, 40.0, 99.0]
    (tick,) = store.ticks(db, "replay-x")
    assert tick["headline"] == "X takes the lead" and tick["rule"]["end"] == 23 and tick["price_at"] == 20.0


def test_loading_again_follows_the_folder(tmp_path):
    db = store.connect(":memory:")
    replay.load(db, folder(tmp_path))
    (tmp_path / "replay-x.json").unlink()
    assert replay.load(db, folder(tmp_path, {**FILE, "id": "replay-y"})) == ["replay-y"]
    assert store.get_market(db, "replay-x") is None and len(store.ticks(db, "replay-y")) == 1


def test_a_broken_file_is_skipped(tmp_path):
    (tmp_path / "bad.json").write_text("{")
    (tmp_path / "half.json").write_text(json.dumps({"id": "replay-half"}))
    assert replay.load(store.connect(":memory:"), folder(tmp_path)) == ["replay-x"]


def test_a_replay_is_not_polled_and_stays_out_of_the_weekend_record(tmp_path):
    db = store.connect(":memory:")
    replay.load(db, folder(tmp_path))
    assert store.all_priced(db) == []
    assert record(db, now=10_000)["called"] == 0


def test_the_api_shows_a_replay_as_of_its_last_minute_and_takes_no_changes(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "t.db"), poll=False, replays=folder(tmp_path))) as c:
        m = next(m for m in c.get("/markets").json() if m["id"] == "replay-x")
        assert m["price"] == 99.0 and m["ticks_today"] == 1 and m["replay"]["outcome"] == "yes"
        assert c.get("/markets/mu-demo").json()["replay"] is None
        assert c.post("/markets/replay-x/ticks", json={"text": "X wins", "kind": "typed"}).status_code == 409
        assert c.delete("/markets/replay-x").status_code == 409
        assert c.post("/markets/replay-x/why").status_code == 409
        assert len(c.get("/markets/replay-x/ticks").json()) == 1
