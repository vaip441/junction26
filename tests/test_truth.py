import asyncio
import json

from terminal import db as store
from terminal import truth
from terminal.bus import Bus
from terminal.scoring import Score

POST = {"id": "117611608680849019", "created_at": "2026-11-13T22:58:48.161Z", "detected_at": "2026-11-13T22:59:01.329Z",
        "delay_seconds": 13.168, "live": True, "source": "poll", "type": "post", "retruth_of": None,
        "text": "Iran has agreed to a ceasefire.\nBig day!", "quote_of": None, "quote_text": None, "link_title": None,
        "link_url": None, "media": [], "url": "https://truthsocial.com/@realDonaldTrump/117611608680849019"}
POSTED = 1794610728.161


def test_a_feed_line_becomes_an_item_to_score():
    assert truth.item(POST) == {"url": POST["url"], "headline": "Iran has agreed to a ceasefire. Big day!",
                                "body": "Iran has agreed to a ceasefire.\nBig day!", "published": POSTED}
    shared = truth.item({**POST, "type": "retruth", "retruth_of": "SecRubio", "text": "Talks went well",
                         "quote_text": "the quoted post", "link_title": "Ceasefire signed"})
    assert shared["headline"] == "Retruth of @SecRubio: Talks went well"
    assert shared["body"] == "Talks went well\nthe quoted post\nCeasefire signed"
    assert truth.item({**POST, "text": "", "link_title": "Lilly breaks ground"})["headline"] == "Lilly breaks ground"
    assert truth.item({**POST, "text": ""}) is None  # only a picture or a video: nothing to read


def test_only_whole_new_lines_are_read_from_the_feed_file(tmp_path):
    feed = tmp_path / "feed.jsonl"
    assert truth.read_new(str(feed), 0) == ([], 0)  # the scraper has not written anything yet
    feed.write_text(json.dumps(POST) + "\n" + '{"id": "half a li')
    posts, offset = truth.read_new(str(feed), 0)
    assert [p["id"] for p in posts] == [POST["id"]]
    assert truth.read_new(str(feed), offset) == ([], offset)  # the unfinished line waits for its end
    with feed.open("a") as f:
        f.write('ne"}\nnot json\n')
    posts, offset = truth.read_new(str(feed), offset)
    assert posts == [{"id": "half a line"}] and offset == feed.stat().st_size  # a damaged line is passed over
    feed.write_text(json.dumps(POST) + "\n")  # replaced by a shorter file: read again from its start
    assert [p["id"] for p in truth.read_new(str(feed), offset)[0]] == [POST["id"]]


def markets(db):
    add = lambda id, queries, **kw: store.add_market(db, id=id, venue="kalshi", venue_ref=id, title=id, rules="r", url=None,
                                                     queries=queries, **kw)
    add("iran", ["Iran ceasefire talks"])
    add("fed", ["FOMC December rate decision"])
    add("rival", ["Iran ceasefire talks"], lead_id="iran")  # a related contract is not scored on its own
    add("unpolled", ["Iran ceasefire talks"], poll_seconds=0)


def test_a_post_is_scored_once_for_each_market_whose_queries_it_touches():
    db, bus, scored = store.connect(":memory:"), Bus(), []
    markets(db)

    async def scorer(context, item, gate):
        scored.append(item)
        return Score(0.84, 0.12, 0.04, 0.8)

    assert asyncio.run(truth.ingest_post(db, bus, scorer, POST, now=POSTED + 20)) == 1
    [t] = store.ticks(db, "iran")
    assert (t["kind"], t["source"], t["url"]) == ("post", "truthsocial.com/@realDonaldTrump", POST["url"])
    assert t["published_ts"] == POSTED and t["backfill"] is False and "Iran has agreed" in scored[0]
    assert store.ticks(db, "fed") == [] and store.ticks(db, "unpolled") == [] and store.ticks(db, "rival") == []
    # read again after a restart: nothing is scored twice
    assert asyncio.run(truth.ingest_post(db, bus, scorer, POST, now=POSTED + 500)) == 0 and len(scored) == 1


def test_an_old_post_and_one_made_while_the_scraper_was_down():
    db, bus = store.connect(":memory:"), Bus()
    markets(db)

    async def scorer(context, item, gate):
        return Score(0.84, 0.12, 0.04, 0.8)

    # a feed read from its start after a restart reaches back days: only the last day counts
    assert asyncio.run(truth.ingest_post(db, bus, scorer, POST, now=POSTED + 2 * 86400)) == 0
    assert asyncio.run(truth.ingest_post(db, bus, scorer, {**POST, "live": False}, now=POSTED + 7200)) == 1
    assert store.ticks(db, "iran")[0]["backfill"] is True  # history, not a live tick
