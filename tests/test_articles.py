import asyncio

from terminal import db as store
from terminal import poller, watch
from terminal.bus import Bus
from terminal.scoring import Score


async def up(*_):
    return Score(0.84, 0.12, 0.04, 0.8)


RESULTS = [{"url": "https://www.news.example.com/x", "title": "Story X", "description": "about x"},
           {"url": "https://other.example.org/y?utm_source=feed", "title": "Story Y", "description": "about y"}]


def setup(queries=("a", "b")):
    db = store.connect(":memory:")
    m = store.add_market(db, id="m", venue="kalshi", venue_ref="T", title="t", rules="r", url=None, queries=list(queries))
    return db, Bus(), m


def test_fetch_articles_ingests_each_result_once_across_queries():
    db, bus, m = setup()
    scraped = []

    async def search(query, **kw):
        return RESULTS

    async def scrape(url):
        scraped.append(url)
        return "full text", 1000.0

    n = asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=True, num_results=20, search=search, scrape=scrape))
    ticks = store.ticks(db, "m")
    assert n == 2 and len(ticks) == 2 and len(scraped) == 2
    by_url = {t["url"]: t for t in ticks}
    t = by_url["https://www.news.example.com/x"]
    assert t["kind"] == "article" and t["backfill"] is True and t["test"] is False
    assert t["source"] == "news.example.com" and t["headline"] == "Story X" and t["published_ts"] == 1000.0
    # a second pass finds nothing new and pays for no scrapes
    assert asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search, scrape=scrape)) == 0
    assert len(scraped) == 2


def test_fetch_articles_survives_a_failing_search_and_a_failing_scrape():
    db, bus, m = setup()

    async def search(query, **kw):
        if query == "a":
            raise RuntimeError("search down")
        return RESULTS[:1]

    async def scrape(url):
        raise RuntimeError("scrape down")

    assert asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search, scrape=scrape)) == 1
    assert store.ticks(db, "m")[0]["published_ts"] is None


def test_queries_fall_back_to_the_title(monkeypatch):
    async def boom(prompt):
        raise RuntimeError("model down")

    monkeypatch.setattr(watch, "ask_json", boom)
    assert asyncio.run(watch.queries_for("T", "R")) == ["T"]


def test_queries_are_cleaned_and_capped(monkeypatch):
    async def answer(prompt):
        return ["  nvidia ceo  ", "", 7, "a", "b", "c", "d", "e"]

    monkeypatch.setattr(watch, "ask_json", answer)
    assert asyncio.run(watch.queries_for("T", "R")) == ["nvidia ceo", "a", "b", "c", "d"]


def test_due_markets_are_those_with_queries_whose_interval_has_passed():
    db, bus, m = setup()
    store.add_market(db, id="noq", venue="kalshi", venue_ref="T2", title="t", rules="r", url=None)
    last = {}
    assert [x["id"] for x in poller.due(db, last, now=1000)] == ["m"]
    last["m"] = 1000
    assert poller.due(db, last, now=1000 + 899) == []
    assert [x["id"] for x in poller.due(db, last, now=1000 + 900)] == ["m"]
