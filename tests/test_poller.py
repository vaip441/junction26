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


def test_resolved_markets_are_dropped_with_everything_they_hold_and_the_rest_are_kept():
    db, bus = store.connect(":memory:"), Bus()
    add = lambda id, venue="kalshi", lead=None: store.add_market(db, id=id, venue=venue, venue_ref=id, title=id, rules="r",
                                                                 url=None, lead_id=lead)
    for id, lead in (("over", None), ("over-side", "over"), ("open", None), ("open-side", "open"), ("unknown", None)):
        add(id, lead=lead)
        store.add_price(db, id, 1.0, 50.0)
    add("mu-x", venue="made_up")
    unwatched, events = [], bus.subscribe()

    async def resolved(m):
        if m["id"] == "unknown":
            raise RuntimeError("venue down")
        return m["id"] in ("over", "open-side")

    async def unwatch(db, id):
        unwatched.append(id)

    gone = asyncio.run(poller.drop_resolved(db, bus, resolved=resolved, unwatch=unwatch))
    # a market goes with its related contracts; a related contract that resolved goes alone; a venue that
    # could not be asked, and a made-up market, change nothing
    assert sorted(gone) == ["open-side", "over"] and unwatched == ["over"]
    assert sorted(m["id"] for m in store.all_priced(db)) == ["open", "unknown"] and store.get_market(db, "mu-x")
    assert store.prices(db, "over") == [] and store.prices(db, "over-side") == []
    assert events.get_nowait() == ("market", {"market_id": "over", "status": "deleted", "resolved": True})
    assert events.empty()


def test_a_resolved_markets_page_stays_until_its_monitor_is_stopped(monkeypatch):
    from terminal import pages

    db, bus = store.connect(":memory:"), Bus()
    for id in ("a", "b"):
        store.add_market(db, id=id, venue="kalshi", venue_ref=id, title=id, rules="r", url=None)
        store.add_page(db, f"page-{id}", id, "https://a.example/", "A", f"mon_{id}", "whsec", 1.0)

    async def delete_monitor(id):
        if id == "mon_b":
            raise pages.contextdev.ContextError("timeout")
        return True

    async def resolved(m):
        return True

    monkeypatch.setattr(pages.contextdev, "delete_monitor", delete_monitor)
    assert sorted(asyncio.run(poller.drop_resolved(db, bus, resolved=resolved))) == ["a", "b"]
    assert store.get_page(db, "page-a") is None and store.get_page(db, "page-b") is not None  # for stop_monitors.py



def test_after_a_restart_the_markets_come_due_one_after_another_not_all_at_once():
    # all at once, the whole list was searched together every interval for ever, and the screen got its
    # reading in a burst every three minutes
    db = store.connect(":memory:")
    for id in ("a", "b", "c"):
        store.add_market(db, id=id, venue="kalshi", venue_ref=id, title=id, rules="r", url=None, queries=["q"], poll_seconds=180)
        store.set_filled(db, id)
    store.add_market(db, id="new", venue="kalshi", venue_ref="new", title="new", rules="r", url=None, poll_seconds=180)
    store.add_market(db, id="still", venue="made_up", venue_ref=None, title="still", rules="r", url=None, poll_seconds=0)
    last = poller.spread(db, now=1000)
    assert last == {"a": 820, "b": 880, "c": 940}
    assert [m["id"] for m in poller.due(db, last, 1000)] == ["new", "a"]  # one not yet filled never waits
    assert [m["id"] for m in poller.due(db, {**last, "new": 1000, "a": 1000}, 1060)] == ["b"]
    assert [m["id"] for m in poller.due(db, {**last, "new": 1000, "a": 1000, "b": 1060}, 1120)] == ["c"]


def test_at_night_the_markets_are_searched_less_often_when_asked_to(monkeypatch):
    db = store.connect(":memory:")
    store.add_market(db, id="a", venue="kalshi", venue_ref="a", title="a", rules="r", url=None, queries=["q"], poll_seconds=180)
    store.set_filled(db, "a")
    store.add_market(db, id="slow", venue="kalshi", venue_ref="slow", title="slow", rules="r", url=None, poll_seconds=3600)
    night, day = 1794700800.0, 1794736800.0  # 15 Nov 2026, 00:00 and 10:00 UTC
    ids = lambda last, now: [m["id"] for m in poller.due(db, last, now)]
    assert ids({"a": night - 200, "slow": night}, night) == ["a"]  # not asked to: night is like day
    monkeypatch.setenv("NIGHT_POLL_SECONDS", "900")
    assert ids({"a": night - 200, "slow": night}, night) == [] and ids({"a": night - 900, "slow": night}, night) == ["a"]
    assert ids({"a": day - 200, "slow": day}, day) == ["a"]
    assert ids({"a": night, "slow": night - 3600}, night) == ["slow"]  # one already slower keeps its own interval
    assert poller.spread(db, night) == {"a": night - 900}
