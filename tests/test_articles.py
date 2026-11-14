import asyncio
import time

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
    store.add_market(db, id="mu", venue="made_up", venue_ref=None, title="t", rules="r", url=None, poll_seconds=0)
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


def test_due_markets_are_fetched_side_by_side_not_one_after_another():
    db, bus, m = setup()
    store.add_market(db, id="n", venue="kalshi", venue_ref="N", title="t", rules="r", url=None, queries=["q"])
    started = []

    async def main():
        both = asyncio.Event()

        async def queries_for(title, rules):
            raise AssertionError("queries already exist")

        async def fetch(db_, bus_, scorer, market, *, backfill, num_results):
            started.append(market["id"])
            if len(started) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 1)  # only returns once the other market's fetch has started
            return 0

        await poller.article_pass(db, bus, up, {}, now=1000, queries_for=queries_for, fetch=fetch)

    asyncio.run(main())
    assert sorted(started) == ["m", "n"]
    assert store.get_market(db, "m")["filled"] and store.get_market(db, "n")["filled"]


POSTS = [{"url": "https://x.com/SomeAnalyst/status/2120971125412827486?s=20", "title": 'Some Analyst on X: "Buck is the name"',
          "description": "Buck is the name"},
         {"url": "https://www.reddit.com/r/hardware/comments/abc/ceo_transition/", "title": "r/hardware on Reddit: CEO",
          "description": "a comment"}]


async def unknown(url):
    return None  # X says nothing about this post


def test_posts_are_searched_once_per_market_and_stored_as_posts():
    db, bus, m = setup()
    calls, scraped = [], []

    async def search(query, **kw):
        calls.append((query, kw.get("include_domains")))
        return POSTS if kw.get("include_domains") else RESULTS[:1]

    async def scrape(url):
        scraped.append(url)
        return "full text", None

    n = asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search, scrape=scrape,
                                          lookup=unknown))
    assert sorted(calls, key=str) == sorted([("a", None), ("b", None), ("a", poller.POST_SITES)], key=str)
    assert poller.POST_SITES == ["x.com", "twitter.com", "reddit.com"]
    by_source = {t["source"]: t for t in store.ticks(db, "m")}
    assert n == 3 and set(by_source) == {"news.example.com", "x.com/SomeAnalyst", "reddit.com/r/hardware"}
    post = by_source["x.com/SomeAnalyst"]
    assert post["kind"] == "post" and post["test"] is False
    assert post["backfill"] is True  # its id says it was posted on 12 Nov: days old, so history
    assert by_source["reddit.com/r/hardware"]["backfill"] is False
    assert scraped == ["https://www.news.example.com/x"]  # a post is its own text: never read


def test_a_failing_posts_search_does_not_fail_the_pass():
    db, bus, m = setup()

    async def search(query, **kw):
        if kw.get("include_domains"):
            raise RuntimeError("posts search down")
        return RESULTS

    async def scrape(url):
        return "", None

    assert asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search, scrape=scrape)) == 2


def made_up(db, id="mu-x"):
    return store.add_market(db, id=id, venue="made_up", venue_ref=None, title="Will X?", rules="Resolves yes if X.",
                            url=None, queries=["a"])


def test_made_up_markets_are_polled_but_a_never_polled_one_is_not():
    db, bus, m = setup()
    made_up(db)
    store.add_market(db, id="mu-demo", venue="made_up", venue_ref=None, title="t", rules="r", url=None, poll_seconds=0)
    assert sorted(x["id"] for x in poller.due(db, {}, now=1000)) == ["m", "mu-x"]


def run_made_up_pass(db, bus, last, now, fetch, starting_price):
    async def queries_for(title, rules):
        raise AssertionError("queries already exist")

    asyncio.run(poller.article_pass(db, bus, up, last, now=now, queries_for=queries_for, fetch=fetch,
                                    starting_price=starting_price))


def test_first_pass_gives_a_made_up_market_its_starting_price_from_the_coverage():
    db, bus = store.connect(":memory:"), Bus()
    made_up(db)
    q, given = bus.subscribe(), []

    async def fetch(db_, bus_, scorer, market, *, backfill, num_results):
        for i, strength in enumerate((0.2, -0.9)):
            store.add_tick(db_, {"market_id": market["id"], "ts": 1.0, "published_ts": None, "kind": "article",
                                 "source": "s", "url": None, "headline": f"h{i}", "up": 0.1, "none": 0.9, "down": 0.0,
                                 "strength": strength, "verdict": "none", "confidence": 0.9, "price_at": None,
                                 "test": False, "backfill": True, "hidden": i == 1, "dedupe_key": str(i)})
        return 2

    async def starting_price(title, rules, headlines):
        given.append((title, headlines))
        return 37.0

    run_made_up_pass(db, bus, {}, 1000, fetch, starting_price)
    assert given == [("Will X?", ["h1", "h0"])]  # strongest first, hidden ones included
    assert store.latest_price(db, "mu-x") == (1000, 37.0) and store.get_market(db, "mu-x")["filled"] is True
    events = [q.get_nowait() for _ in range(q.qsize())]
    assert ("price", {"market_id": "mu-x", "ts": 1000, "price": 37.0}) in events


def test_a_fetch_that_finds_nothing_still_sets_a_starting_price():
    db, bus = store.connect(":memory:"), Bus()
    made_up(db)

    async def fetch(*a, **kw):
        return 0

    async def starting_price(title, rules, headlines):
        assert headlines == []
        return 12.0

    run_made_up_pass(db, bus, {}, 1000, fetch, starting_price)
    assert store.latest_price(db, "mu-x")[1] == 12.0 and store.get_market(db, "mu-x")["filled"] is True


def test_a_failed_starting_price_leaves_the_market_unfilled_and_is_retried():
    from terminal.scoring import ScoringError

    db, bus = store.connect(":memory:"), Bus()
    made_up(db)
    calls = []

    async def fetch(*a, **kw):
        return 0

    async def starting_price(title, rules, headlines):
        calls.append(1)
        if len(calls) == 1:
            raise ScoringError("down")
        return 50.0

    last = {}
    run_made_up_pass(db, bus, last, 1000, fetch, starting_price)
    assert store.latest_price(db, "mu-x") is None and store.get_market(db, "mu-x")["filled"] is False
    run_made_up_pass(db, bus, last, 1061, fetch, starting_price)
    assert store.latest_price(db, "mu-x")[1] == 50.0 and store.get_market(db, "mu-x")["filled"] is True


def test_background_searches_keep_a_reserve_for_people():
    db, bus, m = setup()
    reserves = []

    async def search(query, **kw):
        reserves.append(kw.get("reserve"))
        return []

    async def scrape(url):
        return "", None

    asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search, scrape=scrape))
    assert reserves == [2, 2, 2]


def test_a_post_on_x_carries_the_time_it_was_posted():
    assert poller.posted_at("https://x.com/IanCutress/status/2120971125412827486") == 1794513896.693
    assert poller.posted_at("https://www.reddit.com/r/hardware/comments/abc/x/") is None
    assert poller.posted_at("https://x.com/IanCutress") is None
    assert poller.posted_at("https://x.com/a/status/12345") is None  # ids from before 2010 are not timestamps


def test_x_posts_are_stored_with_their_post_time_and_no_post_costs_a_page_read():
    db, bus, m = setup()
    scraped = []

    async def search(query, **kw):
        return [{**POSTS[0], "url": "https://x.com/IanCutress/status/2120971125412827486"}, POSTS[1]] \
            if kw.get("include_domains") else []

    async def scrape(url):
        scraped.append(url)
        return "the whole thread, not wanted", 1700000000.0

    asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search, scrape=scrape,
                                      lookup=unknown))
    when = {t["source"]: t["published_ts"] for t in store.ticks(db, "m")}
    # an X post's id holds its time; Reddit pages carry none, so reading them was a credit for nothing
    assert when == {"x.com/IanCutress": 1794513896.693, "reddit.com/r/hardware": None} and scraped == []


def blocking_fetch(release, calls):
    async def fetch(db_, bus_, scorer, market, *, backfill, num_results):
        calls.append(market["id"])
        if market["id"] != "new":
            await release.wait()
        return 0
    return fetch


def test_a_market_added_mid_pass_is_fetched_at_once_and_routine_ones_stay_capped():
    db, bus, m = setup()
    store.add_market(db, id="n", venue="kalshi", venue_ref="N", title="t", rules="r", url=None, queries=["q"])
    store.set_filled(db, "m")
    store.set_filled(db, "n")

    async def go():
        release, calls, last = asyncio.Event(), [], {}
        shared = {"limit": asyncio.Semaphore(1), "busy": set(), "fetch": blocking_fetch(release, calls)}
        first = asyncio.create_task(poller.article_pass(db, bus, up, last, now=1000, **shared))
        await asyncio.sleep(0.01)  # one routine market is being fetched, the other waits its turn
        store.add_market(db, id="new", venue="kalshi", venue_ref="X", title="t", rules="r", url=None, queries=["q"])
        await poller.article_pass(db, bus, up, last, now=1001, **shared)  # a first fill does not queue
        seen = list(calls)
        release.set()
        await first
        return seen, calls, shared["busy"]

    seen, calls, busy = asyncio.run(go())
    assert seen == ["m", "new"] and sorted(calls) == ["m", "n", "new"] and busy == set()


def test_a_market_still_being_fetched_is_not_fetched_again_when_it_falls_due():
    db, bus, m = setup()

    async def go():
        release, calls, last = asyncio.Event(), [], {}
        shared = {"limit": asyncio.Semaphore(4), "busy": set(), "fetch": blocking_fetch(release, calls)}
        first = asyncio.create_task(poller.article_pass(db, bus, up, last, now=1000, **shared))
        await asyncio.sleep(0.01)
        await poller.article_pass(db, bus, up, last, now=5000, **shared)  # due again by the clock, but in flight
        release.set()
        await first
        await poller.article_pass(db, bus, up, last, now=9000, **shared)  # free again
        return calls

    assert asyncio.run(go()) == ["m", "m"]


def test_a_new_markets_first_fill_does_not_wait_behind_the_reserve():
    db, bus, m = setup()
    reserves = []

    async def search(query, **kw):
        reserves.append(kw.get("reserve"))
        return []

    async def scrape(url):
        return "", None

    asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=True, num_results=20, search=search, scrape=scrape))
    assert reserves == [0, 0, 0]


def test_a_malformed_address_in_the_results_costs_only_that_result():
    db, bus, m = setup(queries=("a",))

    async def search(query, **kw):
        if kw.get("include_domains"):
            return [{"url": "https://[x.com/a/status/1", "title": "odd post", "description": ""}]
        return [{"url": "https://[bad/x", "title": "odd page", "description": ""}, RESULTS[0]]

    async def scrape(url):
        return "", None

    assert asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search, scrape=scrape)) == 1


def test_an_address_whose_publish_time_is_already_known_is_not_read_again():
    db, bus, m = setup(queries=("a",))
    store.add_market(db, id="n", venue="kalshi", venue_ref="N", title="t", rules="r", url=None, queries=["a"])
    scraped = []

    async def search(query, **kw):
        return [] if kw.get("include_domains") else RESULTS[:1]

    async def scrape(url):
        scraped.append(url)
        return "full text", 1000.0

    for id in ("m", "n"):
        asyncio.run(poller.fetch_articles(db, bus, up, store.get_market(db, id), backfill=True, num_results=20,
                                          search=search, scrape=scrape))
    assert len(scraped) == 1 and store.ticks(db, "n")[0]["published_ts"] == 1000.0
    assert store.undated_urls(db, 10) == []


def test_missing_publish_times_are_filled_in_afterwards_in_one_batch():
    db, bus, m = setup()
    q = bus.subscribe()
    for i in range(3):
        store.add_tick(db, {"market_id": "m", "ts": float(i), "published_ts": None, "kind": "article", "source": "s",
                            "url": f"https://a.example/{i}", "headline": f"h{i}", "up": 0.8, "none": 0.1, "down": 0.1,
                            "strength": 0.5, "verdict": "up", "confidence": 0.8, "price_at": None, "test": False,
                            "backfill": True, "hidden": False, "dedupe_key": str(i)})
    asked = []

    async def published_times(urls):
        asked.append(urls)
        return {"https://a.example/2": 500.0, "https://a.example/1": None}  # /0 could not be read

    assert asyncio.run(poller.fill_dates(db, bus, published_times=published_times)) == 3
    assert asked == [["https://a.example/2", "https://a.example/1", "https://a.example/0"]]
    events = [q.get_nowait() for _ in range(q.qsize())]
    assert [(e, d["url"], d["published_ts"]) for e, d in events] == [("tick_update", "https://a.example/2", 500.0)]
    assert asyncio.run(poller.fill_dates(db, bus, published_times=published_times)) == 0 and len(asked) == 1


def test_a_failed_batch_leaves_the_ticks_to_be_tried_again():
    from terminal.contextdev import ContextError

    db, bus, m = setup()
    store.add_tick(db, {"market_id": "m", "ts": 1.0, "published_ts": None, "kind": "article", "source": "s",
                        "url": "https://a.example/0", "headline": "h", "up": 0.8, "none": 0.1, "down": 0.1,
                        "strength": 0.5, "verdict": "up", "confidence": 0.8, "price_at": None, "test": False,
                        "backfill": True, "hidden": False, "dedupe_key": "0"})

    async def published_times(urls):
        raise ContextError("batch refused")

    import pytest
    with pytest.raises(ContextError):
        asyncio.run(poller.fill_dates(db, bus, published_times=published_times))
    assert store.undated_urls(db, 10) == ["https://a.example/0"]


X_URL = "https://x.com/i/status/2120971125412827486"  # posted at 1794513896.693


def fetch_posts(db, bus, m, found, lookup, scorer=up, feed=None, backfill=False):
    async def search(query, **kw):
        return found if kw.get("include_domains") else []

    async def scrape(url):
        raise AssertionError("posts are never read")

    return asyncio.run(poller.fetch_articles(db, bus, scorer, m, backfill=backfill, num_results=10, search=search,
                                             scrape=scrape, lookup=lookup, feed=feed))


def test_a_post_on_x_carries_its_author_likes_and_replies():
    db, bus, m = setup()

    async def lookup(url):
        return {"handle": "KobeissiLetter", "text": "BREAKING: the board has met", "likes": 13084, "replies": 302,
                "is_reply": False}

    fetch_posts(db, bus, m, [{"url": X_URL, "title": "Post on X", "description": "cut off te"}], lookup)
    [t] = store.ticks(db, "m")
    assert (t["source"], t["likes"], t["replies"]) == ("x.com/KobeissiLetter", 13084, 302)  # not "x.com/i"
    assert poller.post_source(X_URL) == "x.com"  # and without a lookup, no made-up handle


def test_trash_is_stored_hidden_without_being_scored_so_it_is_looked_at_once():
    db, bus, m = setup()
    scored, looked = [], []

    async def spy(context, item, gate):
        scored.append(item)
        return await up()

    async def lookup(url):
        looked.append(url)
        return {"handle": "someone", "text": "@other lol", "likes": 3, "replies": 0, "is_reply": True}

    found = [{"url": X_URL, "title": "a reply", "description": ""},
             {"url": "https://www.reddit.com/r/stocks/comments/1/daily/", "title": "Daily Discussion Thread", "description": ""},
             {"url": "https://www.reddit.com/r/stocks/comments/2/fed/", "title": "Fed hikes", "description": "it did"}]
    assert fetch_posts(db, bus, m, found, lookup, scorer=spy) == 3
    assert [t["headline"] for t in store.ticks(db, "m")] == ["Fed hikes"] and len(scored) == 1
    hidden = [t for t in store.ticks(db, "m", include_hidden=True) if t["hidden"]]
    assert {t["headline"] for t in hidden} == {"a reply", "Daily Discussion Thread"}
    assert all(t["verdict"] == "none" and t["strength"] == 0 for t in hidden)
    assert fetch_posts(db, bus, m, found, lookup, scorer=spy) == 0 and len(looked) == 1 and len(scored) == 1


def test_new_posts_in_subreddits_that_were_relevant_before_are_scored_with_their_post_time():
    db, bus, m = setup(queries=("Ian Buck Nvidia CEO",))
    asked, posted = [], time.time() - 600

    async def feed(sub):
        asked.append(sub)
        return [{"url": f"https://www.reddit.com/r/{sub}/comments/9/buck/", "title": "Buck named", "description": "",
                 "published": posted},
                {"url": f"https://www.reddit.com/r/{sub}/comments/8/fans/", "title": "My fans are loud", "description": "",
                 "published": posted},
                {"url": f"https://www.reddit.com/r/{sub}/comments/7/daily/", "title": "Daily Discussion on the CEO",
                 "description": "", "published": posted},
                {"url": f"https://www.reddit.com/r/{sub}/comments/6/old/", "title": "Buck rumoured for CEO", "description": "",
                 "published": posted - 2 * 86400}]  # a quiet subreddit's feed reaches back days: only the last day counts

    found = [{"url": "https://www.reddit.com/r/nvidia/comments/1/first/", "title": "CEO search begins", "description": ""}]
    assert fetch_posts(db, bus, m, found, unknown, feed=feed) == 1 and asked == []  # no subreddit known yet
    assert fetch_posts(db, bus, m, found, unknown, feed=feed) == 1 and asked == ["nvidia"]
    new = store.ticks(db, "m")[0]
    assert (new["headline"], new["source"], new["kind"]) == ("Buck named", "reddit.com/r/nvidia", "post")
    assert new["published_ts"] == posted
    # the off-topic post, the recurring thread and the old post cost nothing and are not stored
    assert len(store.ticks(db, "m", include_hidden=True)) == 2


def test_a_link_on_x_that_is_not_a_post_is_not_judged_by_reddits_rules():
    db, bus, m = setup()
    fetch_posts(db, bus, m, [{"url": "https://x.com/SomeAnalyst", "title": "Some Analyst (@SomeAnalyst)", "description": "bio"}],
                unknown)
    assert [t["source"] for t in store.ticks(db, "m")] == ["x.com/SomeAnalyst"]  # scored and shown, as before


def test_news_searches_leave_x_and_reddit_to_the_posts_search():
    db, bus, m = setup(queries=("a",))
    searched = []

    async def search(query, **kw):
        searched.append(kw)
        return []

    async def scrape(url):
        return "", None

    asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search, scrape=scrape))
    news = next(kw for kw in searched if not kw.get("include_domains"))
    assert set(news["exclude_domains"]) >= set(poller.POST_SITES)  # else one post is two ticks, one of them unfiltered


def test_an_article_found_live_but_published_days_ago_is_history_not_a_live_tick():
    db, bus, m = setup(queries=("a",))

    async def search(query, **kw):
        return RESULTS

    async def scrape(url):
        return "text", time.time() - (3 * 86400 if url.endswith("/x") else 3600)

    asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search, scrape=scrape))
    assert {t["headline"]: t["backfill"] for t in store.ticks(db, "m")} == {"Story X": True, "Story Y": False}


def test_a_market_that_keeps_failing_is_retried_less_and_less_often():
    db, bus, m = setup()
    calls, last, fails = [], {}, {}

    async def queries_for(title, rules):
        raise AssertionError("queries already exist")

    async def fetch(db_, bus_, scorer, market, *, backfill, num_results):
        calls.append(len(calls))
        if len(calls) <= 3:
            raise poller.FetchFailed("every search failed")
        return 0

    go = lambda now: asyncio.run(poller.article_pass(db, bus, up, last, now=now, queries_for=queries_for, fetch=fetch,
                                                     fails=fails))
    go(1000)                    # fails: again in 1 minute
    go(1061)                    # fails: again in 2 minutes
    go(1125)                    # too soon
    assert len(calls) == 2
    go(1182)                    # fails: again in 4 minutes
    go(1300)                    # too soon
    assert len(calls) == 3
    go(1423)                    # works
    assert len(calls) == 4 and fails == {} and store.get_market(db, "m")["filled"] is True
    for n in range(1, 30):      # however long it has failed, it is tried again within the hour
        fails["m"] = n
        assert poller.retry_delay(n) <= 3600
    assert poller.retry_delay(1) == 60 and poller.retry_delay(3) == 240


def test_a_markets_companies_are_followed_through_the_news_index_without_page_reads():
    db, bus, m = setup(queries=("a",))
    store.set_companies(db, "m", ["Nvidia"])
    m, asked, scraped, posted = store.get_market(db, "m"), [], [], time.time() - 300

    async def search(query, **kw):
        return [RESULTS[0]] if not kw.get("include_domains") else []

    async def news(company, **kw):
        asked.append((company, kw["reserve"], round(time.time() - kw["since"])))
        return [{"url": "https://wire.example.com/ceo", "title": "Board names a CEO", "description": "It did.", "text": "",
                 "published": posted},
                {**RESULTS[0], "text": "", "published": posted}]  # also found by the web search: one tick

    async def scrape(url):
        scraped.append(url)
        return "text", None

    n = asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search, scrape=scrape,
                                          news=news))
    assert n == 2 and asked == [("Nvidia", poller.BACKGROUND_RESERVE, 86400)]
    wire = next(t for t in store.ticks(db, "m") if t["source"] == "wire.example.com")
    assert (wire["kind"], wire["published_ts"], wire["backfill"]) == ("article", posted, False)
    assert "https://wire.example.com/ceo" not in scraped  # the index states the time: nothing to read
    assert store.date_known(db, "https://wire.example.com/ceo") == (posted,)  # nor to look up later


def test_a_news_index_that_fails_does_not_fail_the_pass():
    db, bus, m = setup(queries=("a",))
    store.set_companies(db, "m", ["Nvidia"])

    async def search(query, **kw):
        return RESULTS if not kw.get("include_domains") else []

    async def news(company, **kw):
        raise RuntimeError("news index down")

    async def scrape(url):
        return "", None

    assert asyncio.run(poller.fetch_articles(db, bus, up, store.get_market(db, "m"), backfill=False, num_results=10,
                                             search=search, scrape=scrape, news=news)) == 2


def test_a_markets_companies_are_named_once_and_a_failure_is_tried_again_next_pass():
    db, bus, m = setup()
    assert m["companies"] is None
    seen, answers = [], [RuntimeError("model down"), ["Nvidia"]]

    async def queries_for(title, rules):
        raise AssertionError("queries already exist")

    async def companies_for(title, rules):
        seen.append("asked")
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def fetch(db_, bus_, scorer, market, *, backfill, num_results):
        seen.append(market["companies"])
        return 0

    last = {}
    for now in (1000, 2000, 3000):
        asyncio.run(poller.article_pass(db, bus, up, last, now=now, queries_for=queries_for, fetch=fetch,
                                        companies_for=companies_for))
    # the pass goes on without them, they are asked for once more, and then never again
    assert seen == ["asked", None, "asked", ["Nvidia"], ["Nvidia"]]


def test_company_names_are_cleaned_and_capped(monkeypatch):
    async def answer(prompt):
        return ["  Nvidia ", "", 7, "OpenAI", "Anthropic"]

    monkeypatch.setattr(watch, "ask_json", answer)
    assert asyncio.run(watch.companies_for("T", "R")) == ["Nvidia", "OpenAI"]

    async def none(prompt):
        return []

    monkeypatch.setattr(watch, "ask_json", none)
    assert asyncio.run(watch.companies_for("T", "R")) == []  # a market about no company is a fine answer


def test_google_news_adds_fresh_stories_and_one_found_twice_is_one_tick():
    db, bus, m = setup(queries=("a",))
    asked, scraped, posted = [], [], time.time() - 240

    async def search(query, **kw):
        return [RESULTS[0]] if not kw.get("include_domains") else []  # "Story X" from news.example.com

    async def gnews(query):
        asked.append(query)
        return [{"url": "https://news.google.com/rss/articles/CBMi1?oc=5", "title": "Board names a new chief executive",
                 "description": "", "text": "", "source": "reuters.com", "published": posted},
                {"url": "https://news.google.com/rss/articles/CBMi2?oc=5", "title": "Board names a new chief executive",
                 "description": "", "text": "", "source": "local10.com", "published": posted},  # the same wire story
                {"url": "https://news.google.com/rss/articles/CBMi3?oc=5", "title": "Story X of the day, told again",
                 "description": "", "text": "", "source": "other.example.com", "published": posted}]

    async def scrape(url):
        scraped.append(url)
        return "text", None

    go = lambda: asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search,
                                                   scrape=scrape, gnews=gnews))
    assert go() == 3 and asked == ["a"]
    by_source = {t["source"]: t for t in store.ticks(db, "m")}
    assert set(by_source) == {"news.example.com", "reuters.com", "other.example.com"}  # the wire story once
    fresh = by_source["reuters.com"]
    assert (fresh["kind"], fresh["published_ts"], fresh["headline"]) == ("article", posted, "Board names a new chief executive")
    assert scraped == ["https://www.news.example.com/x"]  # Google states the time; its links are not read
    assert go() == 0  # and nothing is stored twice on the next pass


def test_google_news_being_down_does_not_fail_the_pass():
    db, bus, m = setup(queries=("a",))

    async def search(query, **kw):
        return RESULTS if not kw.get("include_domains") else []

    async def gnews(query):
        raise RuntimeError("HTTP 503")

    async def scrape(url):
        return "", None

    assert asyncio.run(poller.fetch_articles(db, bus, up, m, backfill=False, num_results=10, search=search, scrape=scrape,
                                             gnews=gnews)) == 2


def test_sites_kept_out_of_the_news_search_are_kept_out_of_every_news_source():
    db, bus, m = setup(queries=("a",))
    store.set_companies(db, "m", ["Nvidia"])
    item = lambda url, title, **kw: {"url": url, "title": title, "description": "", "text": "", "published": time.time() - 60, **kw}

    async def search(query, **kw):
        return []

    async def gnews(query):
        return [item("https://news.google.com/rss/articles/C1", "Odds shift on the next chief executive", source="polymarket.com"),
                item("https://news.google.com/rss/articles/C2", "Thread about the next chief executive", source="old.reddit.com"),
                item("https://news.google.com/rss/articles/C3", "Board names a new chief executive", source="reuters.com")]

    async def news(company, **kw):
        return [item("https://en.wikipedia.org/wiki/Nvidia", "Nvidia, the free encyclopedia entry"),
                item("https://x.com/someone/status/2120971125412827486", "Someone on X about the chief executive")]

    async def scrape(url):
        return "", None

    asyncio.run(poller.fetch_articles(db, bus, up, store.get_market(db, "m"), backfill=False, num_results=10,
                                      search=search, scrape=scrape, gnews=gnews, news=news))
    assert [t["source"] for t in store.ticks(db, "m", include_hidden=True)] == ["reuters.com"]


def test_a_first_fill_scores_only_the_most_relevant_items_and_hides_the_rest_unscored(monkeypatch):
    monkeypatch.setattr(poller, "FILL_SCORED", 2)
    db, bus, m = setup(queries=("fed rates",))
    q = bus.subscribe()
    scored = []

    async def spy(context, item, gate):
        scored.append(item.split(": ", 1)[1].split("\n")[0])
        return await up()

    found = [{"url": "https://a.example.com/1", "title": "Weather in Paris", "description": "sunny"},
             {"url": "https://a.example.com/2", "title": "Fed holds rates", "description": "the fed kept rates"},
             {"url": "https://a.example.com/3", "title": "Football scores", "description": "a draw"},
             {"url": "https://a.example.com/4", "title": "Rates outlook", "description": "analysts on rates"}]

    async def search(query, **kw):
        return [] if kw.get("include_domains") else found

    async def scrape(url):
        return "", None

    fetch = lambda backfill: asyncio.run(poller.fetch_articles(db, bus, spy, m, backfill=backfill, num_results=20,
                                                               search=search, scrape=scrape))
    assert fetch(True) == 4  # all four are stored, so none is searched up and scored on a later pass
    # the two sharing the most words with the market's queries cost a model call; the others cost none
    assert sorted(scored) == ["Fed holds rates", "Rates outlook"]
    shown = {t["headline"] for t in store.ticks(db, "m")}
    hidden = {t["headline"] for t in store.ticks(db, "m", include_hidden=True)} - shown
    assert shown == {"Fed holds rates", "Rates outlook"} and hidden == {"Weather in Paris", "Football scores"}
    events = [d for e, d in (q.get_nowait() for _ in range(q.qsize())) if e == "market"]
    assert events == [{"market_id": "m", "status": "scoring", "found": 4, "scored": 2}]
    assert fetch(False) == 0 and len(scored) == 2


def test_a_live_pass_scores_everything_new_however_much_there_is(monkeypatch):
    monkeypatch.setattr(poller, "FILL_SCORED", 1)
    db, bus, m = setup(queries=("fed rates",))
    scored = []

    async def spy(context, item, gate):
        scored.append(item)
        return await up()

    async def search(query, **kw):
        return [] if kw.get("include_domains") else RESULTS

    async def scrape(url):
        return "", None

    asyncio.run(poller.fetch_articles(db, bus, spy, m, backfill=False, num_results=10, search=search, scrape=scrape))
    assert len(scored) == 2
