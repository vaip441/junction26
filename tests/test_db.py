from terminal.db import (add_history, add_market, add_price, add_tick, connect, list_markets, price_at, prices, related,
                         ticks)


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


def test_publish_times_are_kept_per_address_across_markets():
    from terminal.db import date_known, set_published, undated_urls

    db = connect(":memory:")
    market(db)
    market(db, "n")
    add_tick(db, tick(key="a", url="https://a.example/1", ts=1.0))
    add_tick(db, tick("n", key="a", url="https://a.example/1", ts=2.0, hidden=True))
    add_tick(db, tick(key="b", url="https://a.example/2", ts=3.0))
    add_tick(db, tick(key="c", url="https://a.example/3", ts=4.0, published_ts=50.0))
    add_tick(db, tick(key="d", url="https://x.com/a/status/1", ts=5.0, kind="post"))
    add_tick(db, tick(key="e", url="https://a.example/hidden", ts=6.0, hidden=True))
    # shown articles without a time, newest first; posts, hidden and dated ones are left alone
    assert undated_urls(db, 10) == ["https://a.example/2", "https://a.example/1"]
    assert date_known(db, "https://a.example/1") is None and date_known(db, "https://a.example/3") == (50.0,)
    changed = set_published(db, "https://a.example/1", 99.0)
    assert [(t["market_id"], t["published_ts"]) for t in changed] == [("m", 99.0)]  # only shown ticks are announced
    assert {t["published_ts"] for t in ticks(db, "n", include_hidden=True)} == {99.0}
    assert set_published(db, "https://a.example/2", None) == [] and date_known(db, "https://a.example/2") == (None,)
    assert undated_urls(db, 10) == []  # looked at once, with or without a result
    set_published(db, "https://a.example/3", 7.0)
    assert date_known(db, "https://a.example/3") == (50.0,)  # a time already known is kept


def test_deleting_a_market_takes_its_contracts_ticks_and_prices_with_it():
    from terminal.db import delete_market, get_market, prices

    db = connect(":memory:")
    market(db)
    market(db, "rel", lead_id="m")
    market(db, "other")
    for id in ("m", "rel", "other"):
        add_price(db, id, 1, 50.0)
        add_tick(db, tick(id, key="k"))
    delete_market(db, "m")
    assert get_market(db, "m") is None and get_market(db, "rel") is None and get_market(db, "other") is not None
    assert ticks(db, "m") == [] and prices(db, "rel") == [] and len(ticks(db, "other")) == 1


def test_a_markets_subreddits_are_those_whose_posts_were_shown_most():
    from terminal.db import subreddits

    db = connect(":memory:")
    market(db)
    for i, (source, hidden) in enumerate([("reddit.com/r/nvidia", False), ("reddit.com/r/nvidia", False),
                                          ("reddit.com/r/hardware", False), ("reddit.com/r/asksg", True),
                                          ("x.com/someone", False)]):
        add_tick(db, tick(key=str(i), kind="post", source=source, hidden=hidden))
    add_tick(db, tick("n", key="z", kind="post", source="reddit.com/r/elsewhere"))
    assert subreddits(db, "m") == ["nvidia", "hardware"] and subreddits(db, "m", limit=1) == ["nvidia"]


def test_a_tick_whose_page_turns_out_to_be_days_old_becomes_history():
    from terminal.db import set_published

    db = connect(":memory:")
    market(db)
    found = 1_000_000.0
    add_tick(db, tick(key="a", url="https://a.example/old", ts=found))
    add_tick(db, tick(key="b", url="https://a.example/fresh", ts=found))
    add_tick(db, tick(key="c", url="https://a.example/unknown", ts=found))
    [old] = set_published(db, "https://a.example/old", found - 3 * 86400)  # learned later, from the batch lookup
    assert old["backfill"] is True  # and the frontend is told with the same update
    assert set_published(db, "https://a.example/fresh", found - 3600)[0]["backfill"] is False
    set_published(db, "https://a.example/unknown", None)
    assert {t["dedupe_key"]: t["backfill"] for t in ticks(db, "m")} == {"a": True, "b": False, "c": False}


def test_history_fills_in_only_what_is_older_than_our_own_samples():
    db = connect(":memory:")
    market(db)
    add_price(db, "m", 1000.0, 40.0)
    # the venue's 1000 and 1500 would rewrite or follow what we sampled ourselves: left out
    assert add_history(db, "m", [(400.0, 30.0), (700.0, 35.0), (1000.0, 99.0), (1500.0, 99.0)]) == 2
    assert [(p["ts"], p["price"]) for p in prices(db, "m")] == [(400.0, 30.0), (700.0, 35.0), (1000.0, 40.0)]
    assert add_history(db, "m", [(400.0, 31.0), (700.0, 36.0)]) == 0  # asked twice: nothing changes
    assert price_at(db, "m", 800.0) == 35.0
