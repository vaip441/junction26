import asyncio
import time

from terminal import db as store
from terminal import poller
from terminal.bus import Bus
from terminal.pricing import history, nudge
from terminal.scoring import Score


def test_history_walks_back_from_the_price_and_ends_on_it():
    points = history(60.0, [(100.0, 0.5), (200.0, -1.0)], lead=10)
    assert [ts for ts, _ in points] == [90.0, 100.0, 200.0]
    assert points[-1][1] == 60.0
    before_last = nudge(60.0, 1.0)            # the down call undone
    assert abs(points[1][1] - before_last) < 1e-9
    assert abs(points[0][1] - nudge(before_last, -0.5)) < 1e-9
    assert abs(nudge(nudge(points[0][1], 0.5), -1.0) - 60.0) < 1e-6  # played forward it arrives at the price


def test_history_without_items_is_empty_and_one_moment_is_one_step():
    assert history(50.0, []) == []
    assert len(history(50.0, [(100.0, 0.5), (100.0, 0.5)])) == 2


def _market(db):
    store.add_market(db, id="mu-x", venue="made_up", venue_ref=None, title="Will the Fed hold?", rules="Resolves yes if it holds",
                     url=None, queries=["fed rates hold"], poll_seconds=180)
    return store.get_market(db, "mu-x")


def test_first_fill_of_a_made_up_market_draws_its_chart_from_the_coverage(tmp_path):
    db, bus = store.connect(str(tmp_path / "t.db")), Bus()
    m, now = _market(db), time.time()

    async def scorer(context, item, gate):
        return Score(0.8, 0.1, 0.1, 0.6)

    async def gnews(query):
        return [{"url": "https://news.example/a", "title": "Fed officials signal a long hold", "description": "",
                 "text": "", "source": "news.example", "published": now - 7200},
                {"url": "https://news.example/b", "title": "Inflation cools faster than expected", "description": "",
                 "text": "", "source": "news.example", "published": now - 3600}]

    async def nothing(*a, **k):
        return []

    async def fetch(db, bus, scorer, market, *, backfill, num_results):
        return await poller.fetch_articles(db, bus, scorer, market, backfill=backfill, num_results=num_results,
                                           search=nothing, news=nothing, gnews=gnews, bluesky=nothing)

    async def starting_price(title, rules, headlines):
        return 70.0

    async def companies(title, rules):
        return []

    asyncio.run(poller.article_pass(db, bus, scorer, {}, now=now, fetch=fetch, starting_price=starting_price,
                                    companies_for=companies))
    prices = store.prices(db, m["id"])
    assert [round(p["ts"]) for p in prices] == [round(now - 10800), round(now - 7200), round(now - 3600), round(now)]
    assert prices[-1]["price"] == prices[-2]["price"] == 70.0
    assert prices[0]["price"] < prices[1]["price"] < 70.0      # two up calls: the line climbs to the starting odds
    assert poller.draw_history(db, m["id"]) == []              # again: nothing more to add
    assert len(store.prices(db, m["id"])) == 4
