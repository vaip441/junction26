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


def test_fetch_articles_raises_when_every_search_fails():
    import pytest

    db, bus, m = setup()

    async def search(query, **kw):
        raise RuntimeError("search down")

    async def scrape(url):
        return "", None

    with pytest.raises(poller.FetchFailed):
        asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=True, num_results=20, search=search, scrape=scrape))


def test_query_writing_failure_raises(monkeypatch):
    import pytest

    async def boom(prompt):
        raise RuntimeError("model down")

    monkeypatch.setattr(watch, "ask_json", boom)
    with pytest.raises(watch.QueryError):
        asyncio.run(watch.queries_for("T", "R"))


def test_queries_are_cleaned_and_capped(monkeypatch):
    import pytest

    async def answer(prompt):
        return ["  nvidia ceo  ", "", 7, "a", "b", "c", "d", "e"]

    monkeypatch.setattr(watch, "ask_json", answer)
    assert asyncio.run(watch.queries_for("T", "R")) == ["nvidia ceo", "a", "b", "c", "d"]

    async def nothing(prompt):
        return []

    monkeypatch.setattr(watch, "ask_json", nothing)
    with pytest.raises(watch.QueryError):
        asyncio.run(watch.queries_for("T", "R"))


def test_due_lists_real_lead_markets_new_and_fast_ones_first():
    db, bus, m = setup()
    store.add_market(db, id="fast", venue="kalshi", venue_ref="F", title="t", rules="r", url=None, poll_seconds=60)
    store.add_market(db, id="new", venue="kalshi", venue_ref="N", title="t", rules="r", url=None)
    store.add_market(db, id="rel", venue="kalshi", venue_ref="R", title="t", rules="r", url=None, lead_id="m")
    store.add_market(db, id="mu", venue="made_up", venue_ref=None, title="t", rules="r", url=None)
    store.set_filled(db, "m")
    store.set_filled(db, "fast")
    last = {}
    assert [x["id"] for x in poller.due(db, last, now=1000)] == ["new", "fast", "m"]
    last.update(m=1000, fast=1000, new=1000)
    assert [x["id"] for x in poller.due(db, last, now=1060)] == ["fast"]
    assert [x["id"] for x in poller.due(db, last, now=1900)] == ["new", "fast", "m"]


def run_pass(db, bus, last, now, queries_for, fetch):
    asyncio.run(poller.article_pass(db, bus, up, last, now=now, queries_for=queries_for, fetch=fetch))


def test_first_pass_writes_queries_and_is_the_backfill_later_passes_are_live():
    db, bus, m = setup(queries=())
    q = bus.subscribe()
    calls = []

    async def queries_for(title, rules):
        return ["q1", "q2"]

    async def fetch(db_, bus_, scorer, market, *, backfill, num_results):
        calls.append((market["queries"], backfill, num_results))
        return 3

    last = {}
    run_pass(db, bus, last, 1000, queries_for, fetch)
    run_pass(db, bus, last, 1000 + 900, queries_for, fetch)
    assert calls == [(["q1", "q2"], True, 20), (["q1", "q2"], False, 10)]
    assert store.get_market(db, "m")["filled"] is True
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert [d["status"] for e, d in events if e == "market"] == ["finding sources", "ready"]


def test_a_failed_fill_stays_a_backfill_and_is_retried_within_a_minute():
    db, bus, m = setup()
    calls = []

    async def queries_for(title, rules):
        raise AssertionError("queries already exist")

    async def fetch(db_, bus_, scorer, market, *, backfill, num_results):
        calls.append(backfill)
        if len(calls) == 1:
            raise poller.FetchFailed("every search failed")
        return 1

    last = {}
    run_pass(db, bus, last, 1000, queries_for, fetch)
    assert store.get_market(db, "m")["filled"] is False
    run_pass(db, bus, last, 1030, queries_for, fetch)   # too soon
    run_pass(db, bus, last, 1061, queries_for, fetch)   # retried
    assert calls == [True, True] and store.get_market(db, "m")["filled"] is True


def test_a_market_whose_queries_cannot_be_written_is_retried_not_fetched():
    db, bus, m = setup(queries=())
    fetched = []

    async def queries_for(title, rules):
        raise watch.QueryError("model down")

    async def fetch(*a, **kw):
        fetched.append(1)
        return 0

    last = {}
    run_pass(db, bus, last, 1000, queries_for, fetch)
    assert fetched == [] and store.get_market(db, "m")["queries"] == []
    assert [x["id"] for x in poller.due(db, last, now=1061)] == ["m"]


def test_articles_are_scored_on_their_passages_and_reference_sites_are_excluded():
    db, bus, m = setup(queries=("a",))
    seen, searched = [], []

    async def spy(context, item, gate):
        seen.append(item)
        return Score(0.84, 0.12, 0.04, 0.8)

    async def search(query, **kw):
        searched.append(kw)
        return [{"url": "https://news.example.com/x", "title": "Story X", "description": "short", "text": "The long passage."}]

    async def scrape(url):
        return "", None

    asyncio.run(poller.fetch_articles(db, bus, spy, m, backfill=False, num_results=10, search=search, scrape=scrape))
    assert "The long passage." in seen[0] and "short" not in seen[0]
    assert set(searched[0]["exclude_domains"]) >= {"wikipedia.org", "polymarket.com", "kalshi.com"}


def test_one_article_that_blows_up_does_not_lose_the_rest():
    db, bus, m = setup(queries=("a",))

    async def touchy(context, item, gate):
        if "Story X" in item:
            raise RuntimeError("unexpected")
        return Score(0.84, 0.12, 0.04, 0.8)

    async def search(query, **kw):
        return RESULTS

    async def scrape(url):
        return "", None

    assert asyncio.run(poller.fetch_articles(db, bus, touchy, m, backfill=False, num_results=10, search=search, scrape=scrape)) == 1
    assert [t["headline"] for t in store.ticks(db, "m")] == ["Story Y"]
