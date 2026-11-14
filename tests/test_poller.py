import asyncio

from terminal import db as store
from terminal import poller
from terminal.bus import Bus


def test_sample_prices_skips_markets_with_no_price_and_keeps_going(monkeypatch):
    db = store.connect(":memory:")
    for id in ("a", "b", "c"):
        store.add_market(db, id=id, venue="kalshi", venue_ref=id, title="t", rules="r", url=None)
    store.add_market(db, id="mu", venue="made_up", venue_ref=None, title="t", rules="r", url=None)

    async def fake_price(m):
        if m["id"] == "a":
            return None
        if m["id"] == "b":
            raise RuntimeError("venue exploded")
        return 61.0

    monkeypatch.setattr(poller.venues, "current_price", fake_price)
    bus = Bus()
    q = bus.subscribe()
    assert asyncio.run(poller.sample_prices(db, bus, now=100)) == 1
    assert store.price_at(db, "c", 100) == 61.0 and store.price_at(db, "a", 100) is None
    assert q.get_nowait() == ("price", {"market_id": "c", "ts": 100, "price": 61.0}) and q.empty()


def moved_market(db):
    store.add_market(db, id="m", venue="kalshi", venue_ref="m", title="t", rules="r", url=None, queries=["q"])
    store.set_filled(db, "m")
    store.add_price(db, "m", 700, 40.0)
    store.add_price(db, "m", 1000, 46.0)
    return store.get_market(db, "m")


def test_a_price_move_is_explained_once_however_many_samples_see_it(monkeypatch):
    db, calls = store.connect(":memory:"), []
    moved_market(db)

    async def run():
        release, explaining = asyncio.Event(), {}

        async def explain(db, bus, market, move, *, fetch):
            calls.append((market["id"], move["from"], move["to"]))
            await release.wait()
            raise RuntimeError("an explanation that blows up is logged, not left unretrieved")

        monkeypatch.setattr(poller.moves, "explain", explain)
        poller.explain_moves(db, Bus(), None, set(), explaining, now=1000)
        await asyncio.sleep(0)
        poller.explain_moves(db, Bus(), None, set(), explaining, now=1060)  # the next sample: still being explained
        release.set()
        await asyncio.gather(*explaining.values())
        await asyncio.sleep(0)
        return explaining

    assert asyncio.run(run()) == {} and calls == [("m", 40.0, 46.0)]


def test_the_search_behind_a_move_never_doubles_an_article_pass(monkeypatch):
    db, busy, fetched = store.connect(":memory:"), set(), []
    m = moved_market(db)

    async def fetch(db, bus, scorer, market, *, backfill, num_results):
        fetched.append((market["id"], backfill, set(busy)))  # held while searching, so no pass starts on it

    asyncio.run(poller.fetch_now(db, Bus(), None, m, busy, fetch=fetch))
    assert fetched == [("m", False, {"m"})] and busy == set()

    async def sleep(seconds):
        busy.discard("m")  # the article pass finishes

    monkeypatch.setattr(poller.asyncio, "sleep", sleep)
    busy.add("m")
    asyncio.run(poller.fetch_now(db, Bus(), None, m, busy, fetch=fetch))
    assert len(fetched) == 1  # the pass already searched: its ticks are what gets looked at


def test_a_market_with_no_queries_or_no_first_fill_is_not_searched_on_request():
    db, fetched = store.connect(":memory:"), []
    store.add_market(db, id="bare", venue="made_up", venue_ref=None, title="t", rules="r", url=None)
    store.add_market(db, id="new", venue="kalshi", venue_ref="n", title="t", rules="r", url=None, queries=["q"])

    async def fetch(db, bus, scorer, market, *, backfill, num_results):
        fetched.append(market["id"])

    for id in ("bare", "new"):  # its first fill is the article loop's: fetched here, history would count as live
        asyncio.run(poller.fetch_now(db, Bus(), None, store.get_market(db, id), set(), fetch=fetch))
    assert fetched == []
