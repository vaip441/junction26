"""How a tick was found is written down once, truthfully, and carried everywhere a tick goes."""
import asyncio
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from terminal import db as store
from terminal import pages, poller, replay
from terminal.api import create_app
from terminal.bus import Bus
from terminal.pipeline import ingest, public
from terminal.scoring import Score


async def up(*_):
    return Score(0.84, 0.12, 0.04, 0.8)


def setup(queries=("a",)):
    db = store.connect(":memory:")
    m = store.add_market(db, id="m", venue="kalshi", venue_ref="T", title="t", rules="r", url=None, queries=list(queries))
    return db, Bus(), m


def test_a_store_from_before_provenance_is_migrated_and_its_ticks_are_unknown(tmp_path):
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript(store.SCHEMA.replace("    provenance TEXT NOT NULL DEFAULT 'unknown', discovered_ts REAL, scored_ts REAL,\n", ""))
    assert "provenance" not in {r[1] for r in old.execute("PRAGMA table_info(ticks)")}
    old.execute("INSERT INTO markets (id, venue, title, rules) VALUES ('m', 'kalshi', 't', 'r')")
    old.execute("INSERT INTO ticks (market_id, ts, kind, source, headline, up, none, down, strength, verdict, confidence,"
                " test, backfill, hidden, dedupe_key) VALUES ('m', 5, 'article', 'reuters.com', 'h', .8, .1, .1, .5, 'up',"
                " .8, 0, 0, 0, 'k')")
    old.commit()
    old.close()
    db = store.connect(path)
    (tick,) = store.ticks(db, "m")
    assert tick["provenance"] == "unknown" and tick["discovered_ts"] is None and tick["scored_ts"] is None
    assert tick["headline"] == "h" and tick["ts"] == 5  # nothing else about it changed
    db.close()
    store.connect(path).close()  # opening it again changes nothing and does not fail


def test_ingest_stores_how_and_when_an_item_was_found_and_when_it_was_scored():
    db, bus, m = setup()
    q = bus.subscribe()
    tick = asyncio.run(ingest(db, bus, up, m, kind="article", source="reuters.com", headline="A new thing happened today",
                              url="https://reuters.com/a", now=1000.0, published_ts=900.0,
                              provenance="context_web_search", discovered_ts=990.0))
    assert tick["provenance"] == "context_web_search" and tick["ts"] == 1000.0  # ts keeps its meaning
    assert tick["published_ts"] == 900.0 and tick["discovered_ts"] == 990.0
    assert 1000.0 <= tick["scored_ts"] < 1005.0  # the start plus however long scoring took
    event, sent = q.get_nowait()  # what goes down the stream
    assert event == "tick" and sent["provenance"] == "context_web_search" and sent["discovered_ts"] == 990.0
    assert sent["scored_ts"] == tick["scored_ts"] and "dedupe_key" not in sent
    assert public(store.ticks(db, "m")[0])["provenance"] == "context_web_search"  # and what the API reads back


def test_an_item_is_discovered_no_later_than_it_is_ingested_and_by_default_then():
    db, bus, m = setup()
    a = asyncio.run(ingest(db, bus, up, m, kind="post", source="s", headline="one", url="https://x.example/1", now=50.0))
    b = asyncio.run(ingest(db, bus, up, m, kind="post", source="s", headline="two", url="https://x.example/2", now=50.0,
                           discovered_ts=80.0))
    assert a["discovered_ts"] == 50.0 and a["provenance"] == "unknown" and b["discovered_ts"] == 50.0


def test_a_way_of_finding_that_is_not_on_the_list_is_refused():
    db, bus, m = setup()
    with pytest.raises(ValueError):
        asyncio.run(ingest(db, bus, up, m, kind="post", source="s", headline="h", url="https://x.example/1",
                           provenance="context_dev_probably"))


STORY = "Senate passes the bill after a long night"


def found_both_ways(order):
    """One story found by Context.dev's search (under its own address) and by Google News (under Google's)."""
    db, bus, m = setup()

    async def search(query, **kw):
        return [] if kw.get("include_domains") else [
            {"url": "https://reuters.com/senate", "title": f"{STORY} - Reuters", "description": "d"}]

    async def gnews(query):
        return [{"url": "https://news.google.com/rss/articles/abc", "title": STORY, "description": "", "text": "",
                 "source": "apnews.com", "published": 1.0}]

    async def scrape(url):
        return "", None

    real = asyncio.gather

    async def reordered(*aws, **kw):  # the answers come back in another order: the outcome must not depend on it
        return order(await real(*aws, **kw))

    return db, bus, m, search, gnews, scrape, reordered


def test_an_item_found_two_ways_is_one_tick_credited_by_priority_not_by_arrival(monkeypatch):
    db, bus, m, search, gnews, scrape, _ = found_both_ways(None)
    assert asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search,
                                             scrape=scrape, gnews=gnews)) == 1
    (tick,) = store.ticks(db, "m", include_hidden=True)
    assert tick["provenance"] == "context_web_search" and tick["url"] == "https://reuters.com/senate"

    # the same two finds offered the other way round: Google News first, then the search
    db, bus, m = setup()
    held = {}
    original = poller.title_key
    seen = []
    monkeypatch.setattr(poller, "title_key", lambda t: seen.append(t) or original(t))

    async def search_last(query, **kw):
        return []

    async def gnews_first(query):
        return [{"url": "https://reuters.com/senate", "title": f"{STORY} - Reuters", "description": "", "text": "",
                 "source": "reuters.com", "published": 1.0}]

    assert asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search_last,
                                             scrape=scrape, gnews=gnews_first)) == 1
    (tick,) = store.ticks(db, "m", include_hidden=True)
    assert tick["provenance"] == "google_news"  # found by Google News alone: Context.dev is not credited


def test_the_first_recorded_way_stays_when_another_way_finds_the_item_later():
    db, bus, m, search, gnews, scrape, _ = found_both_ways(None)

    async def nothing(query, **kw):
        return []

    asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=nothing, scrape=scrape,
                                      gnews=gnews))
    asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search, scrape=scrape,
                                      gnews=gnews))
    (tick,) = store.ticks(db, "m", include_hidden=True)
    assert tick["provenance"] == "google_news"  # the search found it on a later pass: one tick, its first finder


def test_priority_is_the_order_of_the_list():
    assert store.PROVENANCE.index("context_web_search") < store.PROVENANCE.index("context_news_search") \
        < store.PROVENANCE.index("google_news") < store.PROVENANCE.index("bluesky")
    assert set(store.CONTEXT_DEV) <= set(store.PROVENANCE)
    assert not {"google_news", "bluesky", "reddit", "microphone", "typed", "replay", "truth_social"} & set(store.CONTEXT_DEV)


def test_bluesky_posts_and_news_index_articles_are_credited_to_themselves():
    db, bus, m = setup()
    store.set_companies(db, "m", ["Nvidia"])
    m = store.get_market(db, "m")

    async def search(query, **kw):
        return []

    async def news(company, **kw):
        return [{"url": "https://cnbc.com/n", "title": "Nvidia names a new finance chief today", "description": "",
                 "text": "", "published": 5.0}]

    async def bluesky(query, since):
        return [{"url": "https://bsky.app/profile/a/post/1", "text": "Nvidia just named a new finance chief, big news",
                 "published": 6.0, "handle": "a.bsky.social", "likes": 500, "replies": 3, "is_reply": False}]

    async def gnews(query):
        return []

    asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search, news=news,
                                      bluesky=bluesky, gnews=gnews))
    by = {t["url"]: t["provenance"] for t in store.ticks(db, "m", include_hidden=True)}
    assert by == {"https://cnbc.com/n": "context_news_search", "https://bsky.app/profile/a/post/1": "bluesky"}
    assert {r["provenance"]: r["items"] for r in store.found_by(db, "m")} == {"bluesky": 1, "context_news_search": 1}


def test_typed_and_spoken_ticks_a_monitored_page_and_a_replay_each_say_what_they_are(tmp_path):
    files = tmp_path / "replays"
    files.mkdir()
    (files / "replay-x.json").write_text(json.dumps({
        "id": "replay-x", "venue": "polymarket", "title": "Will X win?", "rules": "Resolves Yes if X wins.",
        "url": None, "outcome": "yes", "start": 1000.0, "end": 4000.0, "prices": [[1000.0, 20.0], [4000.0, 99.0]],
        "ticks": [{"ts": 1500.0, "published_ts": 1500.0, "kind": "post", "source": "bsky.app/a", "url": "https://bsky.app/1",
                   "headline": "X takes the lead", "up": 0.8, "none": 0.1, "down": 0.1, "strength": 0.6, "verdict": "up",
                   "confidence": 0.8, "price_at": 20.0, "rule": None}]}))
    with TestClient(create_app(db_path=str(tmp_path / "t.db"), scorer=up, poll=False, replays=files)) as c:
        typed = c.post("/markets/mu-demo/ticks", json={"text": "that is clever", "kind": "typed"}).json()
        said = c.post("/markets/mu-demo/ticks", json={"text": "that is very clever", "kind": "mic"}).json()
        assert (typed["provenance"], said["provenance"]) == ("typed", "microphone")
        assert [t["provenance"] for t in c.get("/markets/mu-demo/ticks").json()] == ["microphone", "typed"]
        (played,) = c.get("/markets/replay-x/ticks").json()
        assert played["provenance"] == "replay" and played["discovered_ts"] is None and played["scored_ts"] is None
        assert c.get("/markets/replay-x").json()["found_by"] == [{"provenance": "replay", "items": 1, "shown": 1}]
        assert {f["provenance"] for f in c.get("/markets/mu-demo").json()["found_by"]} == {"typed", "microphone"}

    db, bus, m = setup()
    page = store.add_page(db, "p1", "m", "https://sec.gov/filing", "Filing", "mon1", "secret", 1.0)
    event = {"data": {"change": {"id": "c1", "summary": "A new filing was posted", "detected_at": "2026-11-14T10:00:00Z"}}}
    assert asyncio.run(pages.delivered(db, bus, up, page, event, now=1794650500.0)) is True
    (tick,) = store.ticks(db, "m")
    assert tick["provenance"] == "context_monitor" and tick["discovered_ts"] == 1794650500.0
