import asyncio

from terminal import db as store
from terminal.bus import Bus
from terminal.pipeline import ingest
from terminal.scoring import Score, ScoringError

UP = Score(0.84, 0.12, 0.04, 0.8)


async def up(*_):
    return UP


async def no_effect(*_):
    return Score(0.05, 0.9, 0.05, 0.0)


async def broken(*_):
    raise ScoringError("api down")


def setup(venue="made_up", price=20.0):
    db = store.connect(":memory:")
    m = store.add_market(db, id="m", venue=venue, venue_ref=None, title="t", rules="r", url=None)
    store.add_price(db, "m", 0, price)
    bus = Bus()
    return db, bus, bus.subscribe(), m


def run(db, bus, scorer, m, **kw):
    return asyncio.run(ingest(db, bus, scorer, m, **{"kind": "article", "source": "s", "headline": "h", **kw}))


def drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_typed_tick_on_made_up_market_moves_the_price_and_is_published():
    db, bus, q, m = setup()
    tick = run(db, bus, up, m, kind="typed", headline="that is clever", now=10)
    assert tick["verdict"] == "up" and tick["test"] is True and tick["price_at"] == 20
    assert abs(store.price_at(db, "m", 10) - 25.61) < 0.01
    events = drain(q)
    assert [e for e, _ in events] == ["price", "tick"]
    assert events[0][1]["market_id"] == "m" and abs(events[0][1]["price"] - 25.61) < 0.01


def test_article_on_real_market_does_not_move_the_price():
    db, bus, q, m = setup(venue="kalshi", price=40.0)
    tick = run(db, bus, up, m, url="https://a.example/x", now=10)
    assert tick["test"] is False and tick["price_at"] == 40
    assert store.price_at(db, "m", 10) == 40
    assert [e for e, _ in drain(q)] == ["tick"]


def test_same_article_under_several_addresses_is_one_tick():
    db, bus, q, m = setup(venue="kalshi")
    urls = ["https://News.example.com/a/story", "https://news.example.com/a/story/",
            "http://www.news.example.com/a/story?utm_source=x", "https://news.example.com/a/story#top"]
    results = [run(db, bus, up, m, url=u, headline=f"h{i}", now=i) for i, u in enumerate(urls)]
    assert results[0] is not None and results[1:] == [None, None, None]


def test_same_headline_without_an_address_is_one_tick():
    db, bus, q, m = setup(venue="kalshi")
    assert run(db, bus, up, m, headline="Board  backs CEO!", now=1) is not None
    assert run(db, bus, up, m, headline="board backs ceo", now=2) is None


def test_same_typed_sentence_twice_is_two_ticks():
    db, bus, q, m = setup()
    assert run(db, bus, up, m, kind="typed", headline="great idea", now=1) is not None
    assert run(db, bus, up, m, kind="typed", headline="great idea", now=2) is not None


def test_confident_no_effect_article_is_stored_but_not_published():
    db, bus, q, m = setup(venue="kalshi")
    tick = run(db, bus, no_effect, m, url="https://a.example/x", now=1)
    assert tick["hidden"] is True and drain(q) == []
    assert len(store.ticks(db, "m", include_hidden=True)) == 1 and store.ticks(db, "m") == []


def test_scorer_failure_stores_nothing_and_can_be_retried():
    db, bus, q, m = setup(venue="kalshi")
    assert run(db, bus, broken, m, url="https://a.example/x", now=1) is None
    assert store.ticks(db, "m", include_hidden=True) == []
    assert run(db, bus, up, m, url="https://a.example/x", now=2) is not None
