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
