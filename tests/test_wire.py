import asyncio
import time

import pytest

from terminal import db as store
from terminal import wire
from terminal.bus import Bus
from terminal.record import record
from terminal.scoring import Score, ScoringError

FEED = "https://news.example/api/articles"
PUBLISHED = 1794676916.0  # 2026-11-14T17:21:56+00:00


def article(slug="fed-hold", **more):
    return {"slug": slug, "headline": "Fed officials signal extended hold", "dek": "Two voting members said the committee can wait.",
            "published": "2026-11-14T17:21:56+00:00", "url": f"/article/{slug}", "body": ["First paragraph.", "Second one."],
            **more}


async def up(context, item, gate):
    return Score(0.84, 0.12, 0.04, 0.8)


def markets(db):
    add = lambda id, queries, **kw: store.add_market(db, id=id, venue="kalshi", venue_ref=id, title=id, rules="r", url=None,
                                                     queries=queries, **kw)
    add("fed", ["Fed rate decision"])
    add("iran", ["Iran ceasefire talks"])
    for id in ("fed", "iran"):
        store.add_price(db, id, PUBLISHED - 60, 40.0)
        store.add_price(db, id, PUBLISHED + 2000, 45.0)


def test_the_feed_becomes_articles_and_what_cannot_be_read_is_left_out():
    found = wire.parse({"site": "x", "articles": [
        article(), {"slug": "no-headline"}, article("elsewhere", url="https://evil.example/a"), "not an article",
        article("odd-date", published="yesterday")]}, FEED)
    assert found == [{"slug": "fed-hold", "url": "https://news.example/article/fed-hold",
                      "headline": "Fed officials signal extended hold", "published": PUBLISHED,
                      "body": "Two voting members said the committee can wait.\nFirst paragraph.\nSecond one."}]
    assert wire.parse(["not", "a", "feed"], FEED) == [] and wire.parse({"articles": None}, FEED) == []


def test_an_article_is_a_staged_tick_on_each_market_it_touches_and_stays_out_of_the_record():
    db, bus = store.connect(":memory:"), Bus()
    markets(db)
    (a,) = wire.parse({"articles": [article()]}, FEED)
    assert asyncio.run(wire.ingest_article(db, bus, up, a, "news.example", now=PUBLISHED + 3)) == 1
    [t] = store.ticks(db, "fed")
    assert (t["kind"], t["source"], t["url"], t["verdict"]) == ("article", "news.example", a["url"], "up")
    assert t["test"] is True and t["published_ts"] == PUBLISHED and store.ticks(db, "iran") == []
    # we wrote the article ourselves: it is on the tape, never in the record or told to the scorer as reported
    assert record(db, now=PUBLISHED + 5000, since=0)["called"] == 0 and store.recent_headlines(db, "fed") == []
    assert asyncio.run(wire.ingest_article(db, bus, up, a, "news.example", now=PUBLISHED + 9)) == 0  # seen before


def test_only_articles_published_after_the_start_are_scored_and_a_failed_scoring_is_tried_again():
    db, bus, calls = store.connect(":memory:"), Bus(), []
    markets(db)
    new = article("new", headline="Fed cuts rates")  # stamped hours ago, like every article of the site
    reads = [{"articles": [article("old")]},          # there at the start: not news
             {"articles": [new, article("old")]},     # scoring fails this time
             {"articles": [new, article("old")]},
             {"articles": [new, article("old")]}]
    started = time.time()

    async def read(feed):
        if not reads:
            raise asyncio.CancelledError
        return wire.parse(reads.pop(0), feed)

    async def scorer(context, item, gate):
        calls.append(item)
        if len(calls) == 1:
            raise ScoringError("down")
        return Score(0.84, 0.12, 0.04, 0.8)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(wire.wire_loop(db, bus, scorer, FEED, interval=0, read=read))
    [t] = store.ticks(db, "fed")
    assert t["headline"] == "Fed cuts rates" and len(calls) == 2
    # It was not on the site when we last looked, so it was published after that, whatever its stamp says.
    # The second try keeps the time found at the first.
    assert started <= t["published_ts"] <= t["ts"] and "Published 1 minute ago" in calls[0] and calls[1] == calls[0]
