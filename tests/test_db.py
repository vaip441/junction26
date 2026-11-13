from terminal.db import (add_market, add_price, add_tick, connect, list_markets, price_at, related, ticks)


def market(db, id="m", **kw):
    return add_market(db, **{"id": id, "venue": "kalshi", "venue_ref": "T", "title": "t", "rules": "r", "url": None, **kw})


def tick(market_id="m", key="k", **kw):
    return {"market_id": market_id, "ts": 1.0, "published_ts": None, "kind": "article", "source": "s", "url": None,
            "headline": "h", "up": 0.8, "none": 0.1, "down": 0.1, "strength": 0.5, "verdict": "up", "confidence": 0.8,
            "price_at": None, "test": False, "backfill": False, "hidden": False, "dedupe_key": key, **kw}


def test_price_at_returns_latest_sample_at_or_before():
    db = connect(":memory:")
    market(db)
    add_price(db, "m", 100, 40.0)
    add_price(db, "m", 200, 55.0)
    assert price_at(db, "m", 99) is None
    assert price_at(db, "m", 150) == 40.0
    assert price_at(db, "m", 200) == 55.0


def test_duplicate_tick_is_rejected_per_market():
    db = connect(":memory:")
    market(db)
    market(db, "n")
    first = add_tick(db, tick())
    assert first["id"] and first["test"] is False
    assert add_tick(db, tick()) is None
    assert len(ticks(db, "m")) == 1
    assert add_tick(db, tick("n")) is not None


def test_hidden_ticks_are_excluded_by_default():
    db = connect(":memory:")
    market(db)
    add_tick(db, tick(key="a", hidden=True))
    add_tick(db, tick(key="b"))
    assert [t["dedupe_key"] for t in ticks(db, "m")] == ["b"]
    assert len(ticks(db, "m", include_hidden=True)) == 2


def test_related_contracts_are_not_listed_as_markets():
    db = connect(":memory:")
    market(db)
    market(db, "m2", lead_id="m")
    assert [m["id"] for m in list_markets(db)] == ["m"]
    assert [m["id"] for m in related(db, "m")] == ["m2"]


def test_add_market_twice_keeps_the_first():
    db = connect(":memory:")
    market(db, queries=["a", "b"])
    again = market(db, title="other")
    assert again["title"] == "t" and again["queries"] == ["a", "b"]


def test_sources_count_shown_ticks_and_how_many_moved():
    from terminal.db import sources

    db = connect(":memory:")
    market(db)
    add_tick(db, tick(key="a", source="a.example"))
    add_tick(db, tick(key="b", source="a.example", verdict="none"))
    add_tick(db, tick(key="c", source="a.example", verdict="none", hidden=True))
    add_tick(db, tick(key="d", source="b.example", verdict="down"))
    add_tick(db, tick("n", key="e", source="c.example"))
    assert sources(db, "m") == [{"source": "a.example", "ticks": 2, "moved": 1},
                                {"source": "b.example", "ticks": 1, "moved": 1}]


def test_headlines_leave_out_what_people_said_or_typed():
    from terminal.db import headlines

    db = connect(":memory:")
    market(db)
    add_tick(db, tick(key="a", headline="from the web", strength=0.1))
    add_tick(db, tick(key="b", headline="typed by a judge", strength=0.9, test=True))
    assert headlines(db, "m") == ["from the web"]
