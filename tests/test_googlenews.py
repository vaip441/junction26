import asyncio
from datetime import UTC, datetime

from terminal import googlenews

FEED = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>"fed" - Google News</title>
<item><title>Fed likely to need to raise rates amid worsening inflation: Daly - Reuters</title>
<link>https://news.google.com/rss/articles/CBMiAAA?oc=5</link><guid isPermaLink="false">CBMiAAA</guid>
<pubDate>Fri, 13 Nov 2026 21:01:00 GMT</pubDate><description>&lt;a href="x"&gt;Fed likely&lt;/a&gt;</description>
<source url="https://www.reuters.com">Reuters</source></item>
<item><title>Kevin Warsh’s Plan to Remake the Fed - WSJ</title><link>https://news.google.com/rss/articles/CBMiBBB?oc=5</link>
<pubDate>Sat, 14 Nov 2026 09:30:00 GMT</pubDate><source url="https://www.wsj.com">WSJ</source></item>
<item><title>No publisher given</title><link>https://news.google.com/rss/articles/CBMiCCC?oc=5</link></item>
<item><title>Clock unreadable - CFO Dive</title><link>https://news.google.com/rss/articles/CBMiDDD?oc=5</link>
<pubDate>sometime</pubDate><source url="https://www.cfodive.com">CFO Dive</source></item>
</channel></rss>"""


def test_a_google_news_feed_gives_headline_publisher_and_time_newest_first():
    rows = googlenews.parse(FEED)
    assert rows[0] == {"url": "https://news.google.com/rss/articles/CBMiBBB?oc=5", "title": "Kevin Warsh’s Plan to Remake the Fed",
                       "description": "", "text": "", "source": "wsj.com",
                       "published": datetime(2026, 11, 14, 9, 30, tzinfo=UTC).timestamp()}
    assert [(r["source"], r["title"]) for r in rows[1:]] == [
        ("reuters.com", "Fed likely to need to raise rates amid worsening inflation: Daly"),  # the publisher is cut off
        ("cfodive.com", "Clock unreadable")]  # no time, so last; an item naming no publisher is dropped
    assert rows[2]["published"] is None


def test_only_the_newest_items_of_a_feed_are_kept():
    item = ('<item><title>Story {i} - Reuters</title><link>https://news.google.com/rss/articles/C{i}</link>'
            '<pubDate>Sat, 14 Nov 2026 09:{i:02d}:00 GMT</pubDate><source url="https://www.reuters.com">Reuters</source></item>')
    rows = googlenews.parse("<rss><channel>" + "".join(item.format(i=i) for i in range(40)) + "</channel></rss>")
    assert len(rows) == googlenews.MAX_ITEMS == 20 and rows[0]["title"] == "Story 39"


def test_the_feed_is_asked_for_the_last_day(monkeypatch):
    seen = []

    async def get(params):
        seen.append(params)
        return FEED

    monkeypatch.setattr(googlenews, "_get", get)
    assert len(asyncio.run(googlenews.search("Fed rate decision"))) == 3
    assert seen == [{"q": "Fed rate decision when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"}]
